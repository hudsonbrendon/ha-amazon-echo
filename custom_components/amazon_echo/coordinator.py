"""Data update coordinator: cloud polling tiers, push events and LAN probing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from amazon_echo import (
    AmazonEchoAuthenticationError,
    AmazonEchoClient,
    AmazonEchoError,
    AmazonEchoNotSupportedError,
    Device,
    EchoList,
    ListItem,
    MediaState,
    PushClient,
    PushEvent,
    Routine,
    is_reachable,
    probe_local,
)

from .const import (
    CAP_AUDIO_PLAYER,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_PUSH,
    CONF_HOSTS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOCAL_INTERVAL,
    LOGGER,
    PUSH_DOWN_SCAN_INTERVAL,
    SETTING_KEYS,
    SIGNAL_VOICE,
    SLOW_INTERVAL,
)
from .data import AmazonEchoData

if TYPE_CHECKING:
    from . import AmazonEchoConfigEntry

WRITE_SETTLE_SECONDS = 1.0
PUSH_DEBOUNCE_SECONDS = 2.0
SLOW_CONCURRENCY = 4

type AccountFetcher = Callable[[AmazonEchoClient], Awaitable[Any]]
type DeviceFetcher = Callable[[AmazonEchoClient, Device], Awaitable[Any]]


async def _get_lists(
    client: AmazonEchoClient,
) -> dict[str, tuple[EchoList, list[ListItem]]]:
    lists = await client.get_lists()
    items = await asyncio.gather(*(client.get_list_items(lst.id) for lst in lists))
    return {lst.id: (lst, its) for lst, its in zip(lists, items, strict=True)}


# Each fetcher fills the AmazonEchoData attribute of the same name.
FAST_FETCHERS: dict[str, AccountFetcher] = {
    "dnd": lambda c: c.get_dnd(),
    "volumes": lambda c: c.get_volumes(),
    "bluetooth": lambda c: c.get_bluetooth(),
    "notifications": lambda c: c.get_notifications(),
    "endpoints": lambda c: c.get_endpoint_states(),
}
SLOW_FETCHERS: dict[str, AccountFetcher] = {
    "alarm_volumes": lambda c: c.get_alarm_volumes(),
    "wake_words": lambda c: c.get_wake_words(),
    "ascending_alarms": lambda c: c.get_ascending_alarms(),
    "whisper_mode": lambda c: c.get_whisper_mode(),
    "adaptive_volume": lambda c: c.get_adaptive_volume(),
    "routines": lambda c: c.get_routines(),
    "music_providers": lambda c: c.get_music_providers(),
    "lists": _get_lists,
}
ACCOUNT_FETCHERS = FAST_FETCHERS | SLOW_FETCHERS
# Each fetcher fills AmazonEchoData.settings[serial][name]. Names must not
# collide with ACCOUNT_FETCHERS: a refresh is addressed by name alone.
DEVICE_FETCHERS: dict[str, DeviceFetcher] = {
    "wifi": lambda c, d: c.get_wifi(d),
    "equalizer": lambda c, d: c.get_equalizer(d),
    "earcons": lambda c, d: c.get_earcons(d),
    "aux": lambda c, d: c.get_aux(d),
    "available_wake_words": lambda c, d: c.get_available_wake_words(d),
    "alarm_sounds": lambda c, d: c.get_alarm_sounds(d),
    "alarm_sound": lambda c, d: c.get_default_alarm_sound(d),
    **{key: lambda c, d, key=key: c.get_setting(d, key) for key in SETTING_KEYS},
}
assert not ACCOUNT_FETCHERS.keys() & DEVICE_FETCHERS.keys()

AUDIO_PLAYER_STATES = {"PLAYING": "playing", "INTERRUPTED": "paused"}
# Push command -> what to fetch again (debounced).
PUSH_REFETCH = {
    "PUSH_AUDIO_PLAYER_STATE": "media",
    "PUSH_MEDIA_CHANGE": "media",
    "PUSH_MEDIA_QUEUE_CHANGE": "media",
    "PUSH_MEDIA_PROGRESS_CHANGE": "media",
    "PUSH_CONTENT_FOCUS_CHANGE": "media",
    "PUSH_BLUETOOTH_STATE_CHANGE": "bluetooth",
    "PUSH_NOTIFICATION_CHANGE": "notifications",
    "PUSH_LIST_ITEM_CHANGE": "lists",
    "PUSH_LIST_CHANGE": "lists",
    # Amazon pushes an equalizer event when a device answers a voice request.
    "PUSH_ACTIVITY": "voice",
    "PUSH_EQUALIZER_STATE_CHANGE": "voice",
}
PUSH_IN_PLACE = {
    "PUSH_VOLUME_CHANGE",
    "PUSH_DND_STATE_CHANGE",
    "PUSH_DOPPLER_CONNECTION_CHANGE",
}


class AmazonEchoCoordinator(DataUpdateCoordinator[AmazonEchoData]):
    """Keep one Amazon account in sync and expose writes to the platforms."""

    config_entry: AmazonEchoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AmazonEchoConfigEntry,
        client: AmazonEchoClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} {entry.title}",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.push_connected: bool | None = None
        self._push: PushClient | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._unsupported: set[tuple[str, str]] = set()
        self._discovered: dict[str, str] = {}
        self._pending: set[tuple[str, str | None]] = set()
        self._last_voice = dt_util.utcnow()
        self._push_debouncer = Debouncer(
            hass,
            LOGGER,
            cooldown=PUSH_DEBOUNCE_SECONDS,
            immediate=False,
            function=self._async_flush_push,
            background=True,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def async_start(self) -> None:
        """Start the slow tier timer, LAN probing and the push channel."""
        entry = self.config_entry
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_poll_slow, SLOW_INTERVAL)
        )
        if entry.options.get(CONF_ENABLE_LOCAL, True):
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self.async_poll_local, LOCAL_INTERVAL
                )
            )
            entry.async_create_background_task(
                self.hass, self.async_poll_local(), f"{DOMAIN}_local"
            )
        if entry.options.get(CONF_ENABLE_PUSH, True):
            self._push = PushClient(
                self.client, self._handle_push, on_state=self._handle_push_state
            )
            try:
                await self._push.start()
            except AmazonEchoError as err:
                LOGGER.warning("Push channel unavailable, polling instead: %s", err)
                self._handle_push_state(False)

    async def async_stop(self) -> None:
        """Stop timers and the push channel."""
        while self._unsubs:
            self._unsubs.pop()()
        self._push_debouncer.async_shutdown()
        if self._push is not None:
            await self._push.stop()
            self._push = None

    # ------------------------------------------------------------------ #
    # Cloud polling
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> AmazonEchoData:
        """Fast tier; the first refresh also runs the slow tier."""
        first = self.data is None
        data = AmazonEchoData() if first else self.data
        try:
            devices = await self.client.get_devices()
            data.devices = {d.serial: d for d in devices if not d.is_app}
            await _gather(self._async_fetch(data, key) for key in FAST_FETCHERS)
            await _gather(
                self._async_fetch(data, "media", device)
                for device in data.devices.values()
                if (device.supports(CAP_AUDIO_PLAYER) or device.is_group)
                and device.online
                # with push connected only playing devices need a progress poll
                and (
                    first
                    or not self.push_connected
                    or data.media.get(device.serial, MediaState()).state == "playing"
                )
            )
            if first:
                await self._async_update_slow(data)
        except AmazonEchoAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except AmazonEchoError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        self._async_remove_stale_devices(data)
        return data

    async def _async_update_slow(self, data: AmazonEchoData) -> None:
        """Settings that rarely change: account wide and per device."""
        semaphore = asyncio.Semaphore(SLOW_CONCURRENCY)

        async def fetch(key: str, device: Device | None = None) -> None:
            async with semaphore:
                await self._async_fetch(data, key, device)

        await _gather(
            [
                *(fetch(key) for key in SLOW_FETCHERS),
                *(
                    fetch(key, device)
                    for device in data.devices.values()
                    if not device.is_group
                    for key in DEVICE_FETCHERS
                    if (device.serial, key) not in self._unsupported
                ),
            ]
        )

    async def _async_fetch(
        self, data: AmazonEchoData, key: str, device: Device | None = None
    ) -> None:
        """Fetch one value; only an authentication error is allowed to escape."""
        try:
            if key in ACCOUNT_FETCHERS:
                setattr(data, key, await ACCOUNT_FETCHERS[key](self.client))
            elif device is None:
                return
            elif key == "media":
                data.media[device.serial] = await self.client.get_media(device)
            else:
                value = await DEVICE_FETCHERS[key](self.client, device)
                data.settings.setdefault(device.serial, {})[key] = value
        except AmazonEchoAuthenticationError:
            raise
        except AmazonEchoNotSupportedError:
            if device is not None:
                self._unsupported.add((device.serial, key))
        except AmazonEchoError as err:
            LOGGER.debug(
                "Could not fetch %s%s: %s",
                key,
                f" of {device.name}" if device else "",
                err,
            )

    async def _async_poll_slow(self, _now: datetime | None = None) -> None:
        """Periodic slow tier; skipped while the cloud is unreachable."""
        if not self.last_update_success:
            return
        try:
            await self._async_update_slow(self.data)
        except AmazonEchoAuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
            return
        self.async_update_listeners()

    @callback
    def _async_remove_stale_devices(self, data: AmazonEchoData) -> None:
        """Drop devices that left the Amazon account."""
        if not data.devices:
            # An empty answer is far more likely a cloud glitch than an account
            # that lost everything; removing would also wipe user customisation.
            return
        entry = self.config_entry
        valid = {(DOMAIN, serial) for serial in data.devices}
        valid.add((DOMAIN, entry.unique_id or entry.entry_id))
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            if not device.identifiers & valid:
                registry.async_remove_device(device.id)

    # ------------------------------------------------------------------ #
    # Push
    # ------------------------------------------------------------------ #
    @callback
    def _handle_push_state(self, connected: bool) -> None:
        """Poll faster while the push channel is down; resync when it is back."""
        previous, self.push_connected = self.push_connected, connected
        scan = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.update_interval = timedelta(
            seconds=scan if connected else min(scan, PUSH_DOWN_SCAN_INTERVAL)
        )
        if previous is None and connected:
            return  # first connection right after the first refresh
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN}_push_resync"
        )

    @callback
    def _handle_push(self, event: PushEvent) -> None:
        """Apply a push event to the snapshot and schedule what must be re-read."""
        data = self.data
        if data is None:
            return
        serial, payload = event.device_serial, event.payload
        device = data.devices.get(serial) if serial else None
        if event.command == "PUSH_VOLUME_CHANGE" and serial:
            if (volume := payload.get("volumeSetting")) is not None:
                data.volumes[serial] = (int(volume), bool(payload.get("isMuted")))
        elif event.command == "PUSH_DND_STATE_CHANGE" and serial:
            if "enabled" in payload:
                data.dnd[serial] = bool(payload["enabled"])
        elif event.command == "PUSH_DOPPLER_CONNECTION_CHANGE" and device:
            device.online = payload.get("dopplerConnectionState") == "ONLINE"
        elif event.command == "PUSH_AUDIO_PLAYER_STATE" and serial:
            data.media.setdefault(serial, MediaState()).state = AUDIO_PLAYER_STATES.get(
                payload.get("audioPlayerState", ""), "idle"
            )
        elif event.command == "PUSH_EQUALIZER_STATE_CHANGE" and device:
            bands = {
                "bass": payload.get("bass"),
                "mid": payload.get("midrange", payload.get("mid")),
                "treble": payload.get("treble"),
            }
            if all(isinstance(value, int) for value in bands.values()):
                data.settings.setdefault(device.serial, {})["equalizer"] = bands

        if refetch := PUSH_REFETCH.get(event.command):
            if refetch == "media":
                self._pending.update(
                    ("media", target)
                    for target in (serial, *(device.parent_clusters if device else ()))
                    if target
                )
            else:
                self._pending.add((refetch, None))
            self._push_debouncer.async_schedule_call()
        elif event.command not in PUSH_IN_PLACE:
            LOGGER.debug("Unhandled push %s: %s", event.command, payload)
        self._async_pushed()

    @callback
    def _async_pushed(self) -> None:
        # ponytail: not async_set_updated_data on purpose. It restarts the poll
        # timer, so a chatty push stream would starve the fallback poll (and
        # with it everything push does not carry, e.g. temperature).
        self.async_update_listeners()

    async def _async_flush_push(self) -> None:
        """Re-read what the debounced push events invalidated."""
        pending, self._pending = self._pending, set()
        data = self.data
        try:
            for kind, serial in sorted(pending, key=str):
                if kind == "voice":
                    await self._async_fetch_voice()
                else:
                    await self._async_fetch(data, kind, data.devices.get(serial or ""))
        except AmazonEchoAuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
            return
        self._async_pushed()

    async def _async_fetch_voice(self) -> None:
        """Fire the voice event for interactions newer than the last one seen."""
        try:
            records = await self.client.get_voice_history(
                since=self._last_voice, limit=5
            )
        except AmazonEchoAuthenticationError:
            raise
        except AmazonEchoError as err:
            LOGGER.debug("Could not fetch the voice history: %s", err)
            return
        for record in sorted(records, key=lambda r: r.timestamp):
            if record.timestamp <= self._last_voice:
                continue
            self._last_voice = record.timestamp
            async_dispatcher_send(
                self.hass, f"{SIGNAL_VOICE}_{self.config_entry.entry_id}", record
            )

    # ------------------------------------------------------------------ #
    # Local network
    # ------------------------------------------------------------------ #
    def host_for(self, device: Device) -> str | None:
        """LAN host of a device: by MAC (DHCP) or by name (zeroconf)."""
        mac = self.data.mac(device)
        hosts: dict[str, str] = self.config_entry.data.get(CONF_HOSTS, {})
        return (hosts.get(mac) if mac else None) or self._discovered.get(
            device.name.casefold()
        )

    @callback
    def async_add_discovered(self, name: str, host: str) -> None:
        """Remember a host announced over zeroconf and probe it right away."""
        if not self.config_entry.options.get(CONF_ENABLE_LOCAL, True):
            return
        self._discovered[name.casefold()] = host
        self.config_entry.async_create_background_task(
            self.hass, self.async_poll_local(), f"{DOMAIN}_local"
        )

    async def async_poll_local(self, _now: datetime | None = None) -> None:
        """Probe every device with a known host; never touches the cloud."""
        data = self.data
        session = async_get_clientsession(self.hass)
        learned: dict[str, str] = {}

        async def probe(device: Device, host: str) -> None:
            try:
                info = await probe_local(host, session=session)
                reachable = info is not None or await is_reachable(host)
            except AmazonEchoError, OSError, TimeoutError:
                info, reachable = None, False
            data.hosts[device.serial] = host
            data.reachable[device.serial] = reachable
            if info is not None:
                data.local[device.serial] = info
            if reachable and (mac := data.mac(device)):
                learned[mac] = host

        await asyncio.gather(
            *(
                probe(device, host)
                for device in data.devices.values()
                if not device.is_group and (host := self.host_for(device))
            )
        )
        entry = self.config_entry
        stored: dict[str, str] = entry.data.get(CONF_HOSTS, {})
        if any(stored.get(mac) != host for mac, host in learned.items()):
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_HOSTS: {**stored, **learned}}
            )
        self.async_update_listeners()

    # ------------------------------------------------------------------ #
    # Helpers used by entities and actions
    # ------------------------------------------------------------------ #
    async def async_write(
        self,
        action: Awaitable[Any],
        *,
        refresh: str | None = None,
        device: Device | None = None,
    ) -> Any:
        """Run a cloud write, translate errors and re-read ``refresh``."""
        try:
            result = await action
            if refresh:
                await asyncio.sleep(WRITE_SETTLE_SECONDS)
                await self._async_fetch(self.data, refresh, device)
        except AmazonEchoAuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except AmazonEchoNotSupportedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_supported",
                translation_placeholders={"error": str(err)},
            ) from err
        except AmazonEchoError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self.async_update_listeners()
        return result

    def routine(self, name_or_id: str) -> Routine:
        """Find a routine by id or (case-insensitive) name."""
        wanted = name_or_id.casefold()
        for routine in self.data.routines:
            if routine.id == name_or_id or routine.name.casefold() == wanted:
                return routine
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="routine_not_found",
            translation_placeholders={"routine": name_or_id},
        )


async def _gather(coroutines: Iterable[Awaitable[None]]) -> None:
    """Run fetches concurrently and re-raise the first failure, if any."""
    for result in await asyncio.gather(*coroutines, return_exceptions=True):
        if isinstance(result, BaseException):
            raise result
