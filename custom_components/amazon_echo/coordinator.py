"""Data update coordinator: cloud polling tiers, push events and LAN probing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from amazon_echo import (
    AmazonEchoAuthenticationError,
    AmazonEchoClient,
    AmazonEchoError,
    AmazonEchoNotSupportedError,
    Device,
    EchoList,
    Endpoint,
    ListItem,
    MediaState,
    Notification,
    PushClient,
    PushEvent,
    Routine,
    VoiceRecord,
    is_reachable,
    probe_local,
)

from .const import (
    ALEXA_MEDIA_DOMAIN,
    BUS_ALARM_DISMISSED,
    BUS_LAST_CALLED,
    BUS_NOTIFICATION,
    BUS_VOICE_COMMAND,
    CAP_AUDIO_PLAYER,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_PUSH,
    CONF_HOSTS,
    CONF_SCAN_INTERVAL,
    CONF_SMART_HOME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EMULATED_HUE,
    HA_BRIDGE_MANUFACTURERS,
    HUE_MANUFACTURER,
    ISSUE_SHARED_SESSION,
    KIDS_FAMILIES,
    LOCAL_INTERVAL,
    LOGGER,
    PUSH_DOWN_SCAN_INTERVAL,
    PUSH_SMART_HOME,
    SETTING_KEYS,
    SIGNAL_VOICE,
    SLOW_INTERVAL,
)
from .data import AmazonEchoData

SPOTIFY_CONNECT_TYPE = "_spotify-connect._tcp.local."

if TYPE_CHECKING:
    from . import AmazonEchoConfigEntry

WRITE_SETTLE_SECONDS = 1.0
PUSH_DEBOUNCE_SECONDS = 2.0
SLOW_CONCURRENCY = 4
FAST_TIMEOUT_SECONDS = 90
LAST_CALLED_LOOKBACK = timedelta(days=7)

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
    # One GraphQL answer feeds both (the library shares the request).
    "endpoints": lambda c: c.get_endpoint_states(),
    "smart_home": lambda c: c.get_smart_home_endpoints(),
    "guard": lambda c: c.get_guard(),
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
    "device_preferences": lambda c: c.get_device_preferences(),
    "children": lambda c: c.get_children(),
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
    "comms": lambda c, d: c.get_communication_preferences(d),
    "kids_mode": lambda c, d: c.get_kids_mode(d),
    "kids_profile": lambda c, d: c.get_kids_profile(d),
    **{key: lambda c, d, key=key: c.get_setting(d, key) for key in SETTING_KEYS},
}
assert not ACCOUNT_FETCHERS.keys() & DEVICE_FETCHERS.keys()
# Fetchers that only make sense for some device families.
DEVICE_FETCHER_FAMILIES = {"kids_mode": KIDS_FAMILIES, "kids_profile": KIDS_FAMILIES}

AUDIO_PLAYER_STATES = {"PLAYING": "playing", "INTERRUPTED": "paused"}
# Push command -> what to fetch again (debounced).
PUSH_REFETCH = {
    "PUSH_AUDIO_PLAYER_STATE": "media",
    "PUSH_MEDIA_CHANGE": "media",
    "PUSH_MEDIA_QUEUE_CHANGE": "media",
    "PUSH_MEDIA_PROGRESS_CHANGE": "media",
    "PUSH_CONTENT_FOCUS_CHANGE": "media",
    "NotifyMediaSessionsUpdated": "media",
    "NotifyNowPlayingUpdated": "media",
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
    PUSH_SMART_HOME,
}
DISMISSIBLE = ("ON", "SNOOZED")


def notification_as_dict(notification: Notification) -> dict[str, Any]:
    """Describe an alarm, timer or reminder (action responses and events)."""
    remaining = notification.remaining
    return {
        "id": notification.id,
        "kind": notification.kind,
        "status": notification.status,
        "device_serial": notification.device_serial,
        "label": notification.label,
        "when": notification.when.isoformat() if notification.when else None,
        "remaining": remaining.total_seconds() if remaining else None,
        "recurrence": notification.recurrence,
        "sound": notification.sound,
        "music_provider": notification.raw.get("provider"),
        "music_entity": notification.raw.get("musicEntity"),
    }


def _just_dismissed(old: Notification, new: Notification) -> bool:
    """Tell a dismissal from an edit: Amazon bumps the version by exactly one."""
    try:
        before, after = int(old.raw["version"]), int(new.raw["version"])
    except KeyError, TypeError, ValueError:
        return False
    return (
        new.kind in ("alarm", "music_alarm")
        and old.status in DISMISSIBLE
        and new.status in ("ON", "OFF")
        and after == before + 1
    )


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
        # Device (serial) that routines without a device of their own run on.
        self.default_device: str | None = None
        # serial -> (kind, message, title) of the last speak/announce.
        # serial → (speak / announce, message, title, when it was sent)
        self.last_messages: dict[str, tuple[str, str, str | None, str]] = {}
        self._smart_home = bool(entry.options.get(CONF_SMART_HOME, False))
        self._smart_home_fetched = False
        self._unsub_due: CALLBACK_TYPE | None = None
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
        # Hundreds of per-device calls: far too slow for entry setup, so the
        # setting entities appear a little after the rest (added by listener).
        entry.async_create_background_task(
            self.hass, self._async_poll_slow(), f"{DOMAIN}_slow"
        )
        # Who answered last, without firing events for what was said before.
        entry.async_create_background_task(
            self.hass, self.async_update_last_called(seed=True), f"{DOMAIN}_voice"
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
            await self._async_browse_lan()
        if not entry.options.get(CONF_ENABLE_PUSH, True):
            return
        self._push = PushClient(
            self.client, self._handle_push, on_state=self._handle_push_state
        )
        # Amazon allows one push stream per app registration and the newest
        # connection wins: on a session imported from Alexa Media Player the
        # two integrations would close each other's stream about every second.
        shared = self.client.credentials.source == ALEXA_MEDIA_DOMAIN and any(
            not other.disabled_by
            for other in self.hass.config_entries.async_entries(ALEXA_MEDIA_DOMAIN)
        )
        if shared:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_SHARED_SESSION}_{entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_SHARED_SESSION,
                translation_placeholders={"name": entry.title},
            )
            self._handle_push_state(False)
            return
        try:
            await self._push.start()
        except AmazonEchoError as err:
            LOGGER.warning("Push channel unavailable, polling instead: %s", err)
            self._handle_push_state(False)

    async def async_stop(self) -> None:
        """Stop timers and the push channel."""
        # Re-created on the next setup if the session is still shared.
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_SHARED_SESSION}_{self.config_entry.entry_id}"
        )
        while self._unsubs:
            self._unsubs.pop()()
        if self._unsub_due is not None:
            self._unsub_due()
            self._unsub_due = None
        self._push_debouncer.async_shutdown()
        # Cleared first: stopping reports "disconnected", which must not resync.
        push, self._push = self._push, None
        if push is not None:
            await push.stop()

    # ------------------------------------------------------------------ #
    # Cloud polling
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> AmazonEchoData:
        """Fast tier only; the slow tier runs in the background (see async_start)."""
        first = self.data is None
        data = AmazonEchoData() if first else self.data
        try:
            # Bounded so a slow network at boot makes HA retry the entry instead
            # of cancelling its setup (a cancelled setup is never retried).
            async with asyncio.timeout(FAST_TIMEOUT_SECONDS):
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
                        or data.media.get(device.serial, MediaState()).state
                        == "playing"
                    )
                )
                if not first and not self.push_connected:
                    # no push to say that a device heard something
                    await self._async_fetch_voice(data)
        except AmazonEchoAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except (AmazonEchoError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err) or "timeout"},
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
                    and device.family
                    in DEVICE_FETCHER_FAMILIES.get(key, {device.family})
                ),
            ]
        )

    async def _async_fetch(
        self, data: AmazonEchoData, key: str, device: Device | None = None
    ) -> None:
        """Fetch one value; only an authentication error is allowed to escape."""
        try:
            if key in ACCOUNT_FETCHERS:
                value = await ACCOUNT_FETCHERS[key](self.client)
                if key == "smart_home":
                    value = self._wanted_endpoints(data, value)
                previous = data.notifications
                setattr(data, key, value)
                if key == "notifications":
                    self._async_notifications_changed(previous, value)
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

    def _wanted_endpoints(
        self, data: AmazonEchoData, endpoints: list[Endpoint]
    ) -> dict[str, Endpoint]:
        """Keep Amazon's own hardware, and the rest only when asked for.

        What Home Assistant itself bridged to Alexa is never taken back.
        """
        self._smart_home_fetched = True
        bridged = set(HA_BRIDGE_MANUFACTURERS)
        if EMULATED_HUE in self.hass.config.components:
            bridged.add(HUE_MANUFACTURER)
        return {
            endpoint.id: endpoint
            for endpoint in endpoints
            if (endpoint.is_amazon_device and endpoint.serial not in data.devices)
            or (
                self._smart_home
                and (endpoint.manufacturer or "").casefold() not in bridged
            )
        }

    @callback
    def _async_remove_stale_devices(self, data: AmazonEchoData) -> None:
        """Drop devices that left the Amazon account."""
        if not data.devices:
            # An empty answer is far more likely a cloud glitch than an account
            # that lost everything; removing would also wipe user customisation.
            return
        entry = self.config_entry
        valid = {(DOMAIN, key) for key in (*data.devices, *data.smart_home)}
        valid.add((DOMAIN, entry.unique_id or entry.entry_id))
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            # Smart-home devices are the ones attached to the account device;
            # without a smart-home answer nothing can be said about them.
            if device.via_device_id and not self._smart_home_fetched:
                continue
            if not device.identifiers & valid:
                registry.async_remove_device(device.id)

    # ------------------------------------------------------------------ #
    # Alarms, timers and reminders: events on the bus
    # ------------------------------------------------------------------ #
    def _notification_event(self, notification: Notification) -> dict[str, Any]:
        device = (
            self.data.devices.get(notification.device_serial) if self.data else None
        )
        return {
            **notification_as_dict(notification),
            "device_id": self._device_id(notification.device_serial),
            "name": device.name if device else None,
        }

    def _device_id(self, serial: str | None) -> str | None:
        """Home Assistant device id of an Amazon serial number."""
        entry = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, serial or ""), self.config_entry.entry_id
        )
        return entry.id if entry else None

    @callback
    def _async_notifications_changed(
        self, previous: list[Notification], current: list[Notification]
    ) -> None:
        """Fire the dismissal event and re-arm the "it is due" event."""
        before = {notification.id: notification for notification in previous}
        for notification in current:
            old = before.get(notification.id)
            if old is not None and _just_dismissed(old, notification):
                self.hass.bus.async_fire(
                    BUS_ALARM_DISMISSED, self._notification_event(notification)
                )
        self._async_schedule_due(current)

    @callback
    def _async_schedule_due(self, notifications: list[Notification]) -> None:
        """Fire an event when the next alarm, timer or reminder goes off."""
        if self._unsub_due is not None:
            self._unsub_due()
            self._unsub_due = None
        now = dt_util.utcnow()
        upcoming = [n for n in notifications if n.is_active and n.when and n.when > now]
        if not upcoming:
            return
        when = min(n.when for n in upcoming if n.when)

        @callback
        def due(_now: datetime) -> None:
            self._unsub_due = None
            for notification in upcoming:
                if notification.when == when:
                    self.hass.bus.async_fire(
                        BUS_NOTIFICATION, self._notification_event(notification)
                    )
            self._async_schedule_due(self.data.notifications)

        self._unsub_due = async_track_point_in_utc_time(self.hass, due, when)

    # ------------------------------------------------------------------ #
    # Push
    # ------------------------------------------------------------------ #
    @callback
    def _handle_push_state(self, connected: bool) -> None:
        """Poll faster while the push channel is down; resync when it is back."""
        if self._push is None:
            return
        previous, self.push_connected = self.push_connected, connected
        scan = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.update_interval = timedelta(
            seconds=scan if connected else min(scan, PUSH_DOWN_SCAN_INTERVAL)
        )
        self.async_update_listeners()
        if previous is None and connected:
            return  # first connection right after the first refresh
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN}_push_resync"
        )

    @callback
    def _handle_push(self, event: PushEvent) -> None:
        """Apply a push event to the snapshot and schedule what must be re-read."""
        data = self.data
        serial, payload = event.device_serial, event.payload
        device = data.devices.get(serial) if serial else None
        if event.command == "PUSH_VOLUME_CHANGE" and serial:
            if (volume := payload.get("volumeSetting")) is not None:
                self.async_set_volume(serial, int(volume), bool(payload.get("isMuted")))
        elif event.command == PUSH_SMART_HOME:
            self._async_apply_endpoint_update(payload)
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
                # an event that names no device is about whatever is playing
                targets = (
                    (serial, *(device.parent_clusters if device else ()))
                    if serial
                    else tuple(s for s, m in data.media.items() if m.state != "idle")
                )
                self._pending.update(("media", target) for target in targets)
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

    @callback
    def _async_apply_endpoint_update(self, payload: dict[str, Any]) -> None:
        """Apply a pushed smart-home state change to the snapshot."""
        if (update := self.client.parse_endpoint_update(payload)) is None:
            return
        endpoint_id, values = update
        data = self.data
        if (endpoint := data.smart_home.get(endpoint_id)) is not None:
            endpoint.state.update(values)
            return
        for state in data.endpoints.values():
            if state.get("endpoint_id") == endpoint_id:
                state.update(values)

    @callback
    def async_set_volume(self, serial: str, volume: int, muted: bool = False) -> None:
        """Store a volume, remembering the one it replaces."""
        volumes = self.data.volumes
        if (old := volumes.get(serial)) is not None and old[0] != volume:
            self.data.previous_volumes[serial] = old[0]
        volumes[serial] = (volume, muted)

    def _voice_event(self, record: VoiceRecord) -> dict[str, Any]:
        device = self.data.devices.get(record.device_serial or "")
        return {
            "device_id": self._device_id(record.device_serial),
            "serial": record.device_serial,
            "name": device.name if device else None,
            "timestamp": record.timestamp.isoformat(),
            "utterance": record.utterance,
            "response": record.response,
            "intent": record.intent,
            "person": record.person,
        }

    async def _async_fetch_voice(
        self, data: AmazonEchoData | None = None, *, seed: bool = False
    ) -> None:
        """Fire the voice events for interactions newer than the last one seen.

        With ``seed`` nothing is fired: the last interaction of the past week
        only tells which device was called last.
        """
        data = data or self.data
        since = dt_util.utcnow() - LAST_CALLED_LOOKBACK if seed else self._last_voice
        try:
            records = await self.client.get_voice_history(
                since=since, limit=1 if seed else 5
            )
        except AmazonEchoAuthenticationError:
            raise
        except AmazonEchoError as err:
            LOGGER.debug("Could not fetch the voice history: %s", err)
            return
        for record in sorted(records, key=lambda r: r.timestamp):
            previous = data.last_called
            if previous is None or record.timestamp > previous.timestamp:
                data.last_called = record
            if seed or record.timestamp <= self._last_voice:
                continue
            self._last_voice = record.timestamp
            async_dispatcher_send(
                self.hass, f"{SIGNAL_VOICE}_{self.config_entry.entry_id}", record
            )
            self.hass.bus.async_fire(BUS_VOICE_COMMAND, self._voice_event(record))
            if previous is None or previous.device_serial != record.device_serial:
                self.hass.bus.async_fire(BUS_LAST_CALLED, self._voice_event(record))

    async def async_update_last_called(self, *, seed: bool = False) -> None:
        """Read the voice history now (action, startup)."""
        try:
            await self._async_fetch_voice(seed=seed)
        except AmazonEchoAuthenticationError:
            self.config_entry.async_start_reauth(self.hass)
            return
        self.async_update_listeners()

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

    async def _async_browse_lan(self) -> None:
        """Find the Echos on the LAN ourselves instead of waiting for discovery flows.

        Discovery flows only fire when a device announces itself again, which can
        take hours after the entry is created.
        """
        aiozc = await ha_zeroconf.async_get_async_instance(self.hass)

        async def resolve(service_type: str, name: str) -> None:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(aiozc.zeroconf, 3000):
                return
            session = async_get_clientsession(self.hass)
            for host in info.parsed_addresses(IPVersion.V4Only):
                with suppress(AmazonEchoError, OSError, TimeoutError):
                    local = await probe_local(host, session=session)
                    if local is not None and local.name:
                        self.async_add_discovered(local.name, host)
                        return

        def on_change(
            zeroconf: Any,
            service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change is not ServiceStateChange.Removed:
                self.config_entry.async_create_background_task(
                    self.hass, resolve(service_type, name), f"{DOMAIN}_zeroconf"
                )

        browser = AsyncServiceBrowser(
            aiozc.zeroconf, SPOTIFY_CONNECT_TYPE, handlers=[on_change]
        )
        self._unsubs.append(lambda: self.hass.async_create_task(browser.async_cancel()))

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
        except ValueError as err:  # the library refused an argument
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        self.async_update_listeners()
        return result

    async def async_call_endpoint(
        self,
        endpoint: Endpoint,
        feature: str,
        operation: str,
        *,
        instance: str | None = None,
        payload: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        """Run a smart-home operation; ``state`` is what it leaves behind.

        ponytail: the state is applied at once and confirmed by push or by the
        next poll. Reading it back right away costs the whole endpoint list
        and often returns what the device's own cloud has not updated yet.
        """
        await self.async_write(
            self.client.call_feature(
                endpoint.id, feature, operation, instance=instance, payload=payload
            )
        )
        endpoint.state.update(state or {})
        self.async_update_listeners()

    async def async_say(
        self,
        kind: str,
        devices: list[Device],
        message: str,
        title: str | None = None,
        method: str = "all",
    ) -> None:
        """Speak (``speak``) or announce (``announce``) and remember it."""
        if kind == "speak":
            await self.async_write(self.client.speak(devices[0], message))
        else:
            await self.async_write(
                self.client.announce(devices, message, title=title, method=method)
            )
        for device in devices:
            self.last_messages[device.serial] = (
                kind,
                message,
                title,
                dt_util.utcnow().isoformat(),
            )
        self.async_update_listeners()

    async def set_kids_mode(self, device: Device, child_id: str | None) -> None:
        """Put a device in Amazon Kids mode for a child, or take it out (None)."""
        await self.client.set_kids_mode(device, child_id)
        self.data.settings.setdefault(device.serial, {})["kids_profile"] = child_id

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
