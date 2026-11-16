"""Integration actions: voice commands, pushes, routines, alarms, Bluetooth..."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util
import voluptuous as vol

from amazon_echo import Device, Notification
from amazon_echo.const import INFO_SKILLS

from .const import (
    ATTR_ADDRESS,
    ATTR_ALARM_TYPE,
    ATTR_DEVICE_ID,
    ATTR_DURATION,
    ATTR_ENDPOINT_ID,
    ATTR_FEATURE,
    ATTR_INSTANCE,
    ATTR_LABEL,
    ATTR_LIMIT,
    ATTR_MESSAGE,
    ATTR_METHOD,
    ATTR_MUSIC_ENTITY,
    ATTR_MUSIC_PROVIDER,
    ATTR_NOTIFICATION_ID,
    ATTR_OPERATION,
    ATTR_PAYLOAD,
    ATTR_RECURRENCE,
    ATTR_ROUTINE,
    ATTR_SKILL,
    ATTR_SKILL_ID,
    ATTR_SOUND,
    ATTR_TEXT,
    ATTR_TIME,
    ATTR_TITLE,
    DOMAIN,
    SERVICE_BLUETOOTH_CONNECT,
    SERVICE_BLUETOOTH_DISCONNECT,
    SERVICE_CALL_FEATURE,
    SERVICE_CREATE_ALARM,
    SERVICE_CREATE_REMINDER,
    SERVICE_CREATE_TIMER,
    SERVICE_DELETE_NOTIFICATION,
    SERVICE_DISABLE_ALARM,
    SERVICE_ENABLE_ALARM,
    SERVICE_GET_NOTIFICATIONS,
    SERVICE_GET_VOICE_HISTORY,
    SERVICE_LAUNCH_SKILL,
    SERVICE_PLAY_SOUND,
    SERVICE_REPEAT_LAST_MESSAGE,
    SERVICE_RESTORE_VOLUME,
    SERVICE_RUN_ROUTINE,
    SERVICE_SEND_ANNOUNCEMENT,
    SERVICE_SEND_DROP_IN_NOTIFICATION,
    SERVICE_SEND_INFO_SKILL,
    SERVICE_SEND_MOBILE_PUSH,
    SERVICE_SEND_TEXT_COMMAND,
    SERVICE_SKIP_NEXT_ALARM,
    SERVICE_UPDATE_LAST_CALLED,
)
from .coordinator import notification_as_dict

if TYPE_CHECKING:
    from .coordinator import AmazonEchoCoordinator

DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}
MESSAGE = {vol.Required(ATTR_MESSAGE): cv.string, vol.Optional(ATTR_TITLE): cv.string}
NOTIFICATION = vol.Schema({**DEVICE, vol.Required(ATTR_NOTIFICATION_ID): cv.string})

SCHEMAS: dict[str, vol.Schema] = {
    SERVICE_SEND_TEXT_COMMAND: vol.Schema(
        {**DEVICE, vol.Required(ATTR_TEXT): cv.string}
    ),
    SERVICE_PLAY_SOUND: vol.Schema({**DEVICE, vol.Required(ATTR_SOUND): cv.string}),
    SERVICE_RUN_ROUTINE: vol.Schema({**DEVICE, vol.Required(ATTR_ROUTINE): cv.string}),
    SERVICE_LAUNCH_SKILL: vol.Schema(
        {**DEVICE, vol.Required(ATTR_SKILL_ID): cv.string}
    ),
    SERVICE_CREATE_ALARM: vol.Schema(
        {
            **DEVICE,
            vol.Required(ATTR_TIME): cv.datetime,
            vol.Optional(ATTR_RECURRENCE): cv.string,
            vol.Optional(ATTR_ALARM_TYPE, default="default"): vol.In(
                ("default", "music")
            ),
            vol.Optional(ATTR_MUSIC_PROVIDER): cv.string,
            vol.Optional(ATTR_MUSIC_ENTITY): cv.string,
        }
    ),
    SERVICE_CREATE_TIMER: vol.Schema(
        {
            **DEVICE,
            vol.Required(ATTR_DURATION): cv.positive_time_period,
            vol.Optional(ATTR_LABEL): cv.string,
        }
    ),
    SERVICE_CREATE_REMINDER: vol.Schema(
        {
            **DEVICE,
            vol.Required(ATTR_TIME): cv.datetime,
            vol.Required(ATTR_LABEL): cv.string,
        }
    ),
    SERVICE_DELETE_NOTIFICATION: vol.Schema(
        {**DEVICE, vol.Required(ATTR_NOTIFICATION_ID): cv.string}
    ),
    SERVICE_GET_NOTIFICATIONS: vol.Schema(DEVICE),
    SERVICE_GET_VOICE_HISTORY: vol.Schema(
        {
            **DEVICE,
            vol.Optional(ATTR_LIMIT, default=10): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=50)
            ),
        }
    ),
    SERVICE_BLUETOOTH_CONNECT: vol.Schema(
        {**DEVICE, vol.Required(ATTR_ADDRESS): cv.string}
    ),
    SERVICE_BLUETOOTH_DISCONNECT: vol.Schema(DEVICE),
    SERVICE_CALL_FEATURE: vol.Schema(
        {
            **DEVICE,
            vol.Required(ATTR_FEATURE): cv.string,
            vol.Required(ATTR_OPERATION): cv.string,
            vol.Optional(ATTR_ENDPOINT_ID): cv.string,
            vol.Optional(ATTR_INSTANCE): cv.string,
            vol.Optional(ATTR_PAYLOAD): dict,
        }
    ),
    SERVICE_SEND_INFO_SKILL: vol.Schema(
        {**DEVICE, vol.Required(ATTR_SKILL): vol.In(INFO_SKILLS)}
    ),
    SERVICE_SEND_MOBILE_PUSH: vol.Schema({**DEVICE, **MESSAGE}),
    SERVICE_SEND_DROP_IN_NOTIFICATION: vol.Schema({**DEVICE, **MESSAGE}),
    SERVICE_SEND_ANNOUNCEMENT: vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
            **MESSAGE,
            vol.Optional(ATTR_METHOD, default="all"): vol.In(("all", "speak", "show")),
        }
    ),
    SERVICE_ENABLE_ALARM: NOTIFICATION,
    SERVICE_DISABLE_ALARM: NOTIFICATION,
    SERVICE_SKIP_NEXT_ALARM: NOTIFICATION,
    SERVICE_UPDATE_LAST_CALLED: vol.Schema(DEVICE),
    SERVICE_RESTORE_VOLUME: vol.Schema(DEVICE),
    SERVICE_REPEAT_LAST_MESSAGE: vol.Schema(DEVICE),
}
RESPONSES = {
    SERVICE_CREATE_ALARM: SupportsResponse.OPTIONAL,
    SERVICE_CREATE_TIMER: SupportsResponse.OPTIONAL,
    SERVICE_CREATE_REMINDER: SupportsResponse.OPTIONAL,
    SERVICE_GET_NOTIFICATIONS: SupportsResponse.ONLY,
    SERVICE_GET_VOICE_HISTORY: SupportsResponse.ONLY,
}


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def _identify(hass: HomeAssistant, device_id: str) -> tuple[AmazonEchoCoordinator, str]:
    """Return the coordinator and Amazon identifier behind a device id.

    The identifier is a serial number, a smart-home endpoint id or the
    account's own id.
    """
    device_entry = dr.async_get(hass).async_get(device_id)
    entry = (
        hass.config_entries.async_get_entry(device_entry.config_entry_id)
        if device_entry
        else None
    )
    if device_entry is None or entry is None or entry.domain != DOMAIN:
        raise _error("device_not_found", device_id=device_id)
    if entry.state is not ConfigEntryState.LOADED:
        raise _error("entry_not_loaded", device_id=device_id)
    coordinator: AmazonEchoCoordinator = entry.runtime_data
    return coordinator, next(i[1] for i in device_entry.identifiers if i[0] == DOMAIN)


def _resolve(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[AmazonEchoCoordinator, Device | None]:
    """Return the coordinator and device behind ``device_id``.

    The device is None when the account (service) device was picked.
    """
    coordinator, identifier = _identify(hass, call.data[ATTR_DEVICE_ID])
    if identifier in coordinator.data.smart_home:
        # a lamp or a plug cannot speak, ring or run a routine
        raise _error("device_required")
    return coordinator, coordinator.data.devices.get(identifier)


def _resolve_device(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[AmazonEchoCoordinator, Device]:
    """Like ``_resolve`` for actions that need a real device."""
    coordinator, device = _resolve(hass, call)
    if device is None:
        raise _error("device_required")
    return coordinator, device


def _find(coordinator: AmazonEchoCoordinator, call: ServiceCall) -> Notification:
    """Return the alarm, timer or reminder named by ``notification_id``."""
    wanted = call.data[ATTR_NOTIFICATION_ID]
    for notification in coordinator.data.notifications:
        if notification.id == wanted:
            return notification
    raise _error("notification_not_found", notification_id=wanted)


def _music_alarm(
    coordinator: AmazonEchoCoordinator, call: ServiceCall
) -> Notification | None:
    """Return the existing music alarm whose station a new one reuses.

    Amazon has no public search for stations, so a music alarm can only wake
    with a station that an alarm created in the Alexa app (on any device of
    the account) already has. None for an ordinary alarm.
    """
    provider: str = call.data.get(ATTR_MUSIC_PROVIDER, "")
    entity: str = call.data.get(ATTR_MUSIC_ENTITY, "")
    if call.data[ATTR_ALARM_TYPE] != "music":
        if provider or entity:
            raise _error("music_alarm_fields")
        return None
    if not provider or not entity:
        raise _error("music_alarm_fields")
    wanted = (provider.strip().casefold(), entity.strip().casefold())
    for notification in coordinator.data.notifications:
        raw = notification.raw
        if notification.kind == "music_alarm" and wanted == (
            str(raw.get("provider") or "").strip().casefold(),
            str(raw.get("musicEntity") or "").strip().casefold(),
        ):
            return notification
    raise _error("no_music_alarm", music_provider=provider, music_entity=entity)


def _local(value: datetime) -> datetime:
    """Treat a naive time as local time."""
    return dt_util.as_local(value)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions once per Home Assistant instance."""

    async def send_text_command(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        await c.async_write(c.client.text_command(device, call.data[ATTR_TEXT]))
        c.async_schedule_voice_refresh()

    async def play_sound(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        await c.async_write(c.client.play_sound(device, call.data[ATTR_SOUND]))

    async def run_routine(call: ServiceCall) -> None:
        c, device = _resolve(hass, call)
        routine = c.routine(call.data[ATTR_ROUTINE])
        await c.async_write(c.client.run_routine(routine, device))

    async def launch_skill(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        await c.async_write(c.client.launch_skill(device, call.data[ATTR_SKILL_ID]))

    async def create_alarm(call: ServiceCall) -> ServiceResponse:
        c, device = _resolve_device(hass, call)
        music = _music_alarm(c, call)
        created = await c.async_write(
            c.client.create_alarm(
                device,
                _local(call.data[ATTR_TIME]),
                recurrence=call.data.get(ATTR_RECURRENCE),
                music=music,
            ),
            refresh="notifications",
        )
        return notification_as_dict(created) if call.return_response else None

    async def create_timer(call: ServiceCall) -> ServiceResponse:
        c, device = _resolve_device(hass, call)
        created = await c.async_write(
            c.client.create_timer(
                device, call.data[ATTR_DURATION], label=call.data.get(ATTR_LABEL)
            ),
            refresh="notifications",
        )
        c.async_schedule_voice_refresh()  # a timer is a typed request too
        return notification_as_dict(created) if call.return_response else None

    async def create_reminder(call: ServiceCall) -> ServiceResponse:
        c, device = _resolve_device(hass, call)
        created = await c.async_write(
            c.client.create_reminder(
                device, _local(call.data[ATTR_TIME]), call.data[ATTR_LABEL]
            ),
            refresh="notifications",
        )
        return notification_as_dict(created) if call.return_response else None

    async def delete_notification(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_write(
            c.client.delete_notification(_find(c, call)), refresh="notifications"
        )

    async def enable_alarm(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_write(
            c.client.enable_alarm(_find(c, call)), refresh="notifications"
        )

    async def disable_alarm(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_write(
            c.client.disable_alarm(_find(c, call)), refresh="notifications"
        )

    async def skip_next_alarm(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_write(
            c.client.skip_next_alarm(_find(c, call)), refresh="notifications"
        )

    async def get_notifications(call: ServiceCall) -> ServiceResponse:
        c, device = _resolve(hass, call)
        return {
            "notifications": [
                notification_as_dict(n)
                for n in c.data.notifications
                if device is None or n.device_serial == device.serial
            ]
        }

    async def get_voice_history(call: ServiceCall) -> ServiceResponse:
        c, device = _resolve(hass, call)
        records = await c.async_write(
            c.client.get_voice_history(limit=call.data[ATTR_LIMIT])
        )
        return {
            "records": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat(),
                    "device_serial": r.device_serial,
                    "utterance": r.utterance,
                    "response": r.response,
                    "intent": r.intent,
                    "person": r.person,
                }
                for r in records
                if device is None or r.device_serial == device.serial
            ]
        }

    async def bluetooth_connect(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        wanted: str = call.data[ATTR_ADDRESS]
        paired = next(
            (
                p
                for p in c.data.bluetooth.get(device.serial, [])
                if wanted.casefold()
                in (p.address.casefold(), (p.name or "").casefold())
            ),
            None,
        )
        if paired is None:
            raise _error("bluetooth_not_paired", address=wanted)
        await c.async_write(
            c.client.bluetooth_connect(device, paired.address), refresh="bluetooth"
        )

    async def bluetooth_disconnect(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        await c.async_write(c.client.bluetooth_disconnect(device), refresh="bluetooth")

    async def send_info_skill(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        await c.async_write(c.client.info_skill(device, call.data[ATTR_SKILL]))

    async def send_mobile_push(call: ServiceCall) -> None:
        c, device = _resolve(hass, call)
        await c.async_write(
            c.client.send_mobile_push(
                call.data[ATTR_MESSAGE], title=call.data.get(ATTR_TITLE), device=device
            )
        )

    async def send_drop_in_notification(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_write(
            c.client.send_drop_in_notification(
                call.data[ATTR_MESSAGE], title=call.data.get(ATTR_TITLE)
            )
        )

    async def send_announcement(call: ServiceCall) -> None:
        """One announcement for every picked device (per Amazon account)."""
        targets: dict[AmazonEchoCoordinator, list[Device]] = {}
        for device_id in call.data[ATTR_DEVICE_ID]:
            c, identifier = _identify(hass, device_id)
            if (device := c.data.devices.get(identifier)) is None:
                raise _error("device_required")
            targets.setdefault(c, []).append(device)
        for c, devices in targets.items():
            await c.async_say(
                "announce",
                devices,
                call.data[ATTR_MESSAGE],
                call.data.get(ATTR_TITLE),
                call.data[ATTR_METHOD],
            )

    async def update_last_called(call: ServiceCall) -> None:
        c, _ = _resolve(hass, call)
        await c.async_update_last_called()

    async def restore_volume(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        if (volume := c.data.previous_volumes.get(device.serial)) is None:
            raise _error("no_previous_volume")
        await c.async_write(c.client.set_volume(device, volume))
        c.async_set_volume(device.serial, volume)
        c.async_update_listeners()

    async def repeat_last_message(call: ServiceCall) -> None:
        c, device = _resolve_device(hass, call)
        if (last := c.last_messages.get(device.serial)) is None:
            raise _error("no_last_message")
        kind, message, title, _ = last
        await c.async_say(kind, [device], message, title)

    async def call_feature(call: ServiceCall) -> None:
        c, identifier = _identify(hass, call.data[ATTR_DEVICE_ID])
        device = c.data.devices.get(identifier)
        endpoint_id = (
            call.data.get(ATTR_ENDPOINT_ID)
            or (device.endpoint_id if device else None)
            or (identifier if identifier in c.data.smart_home else None)
        )
        if not endpoint_id:
            raise _error("no_endpoint")
        await c.async_write(
            c.client.call_feature(
                endpoint_id,
                call.data[ATTR_FEATURE],
                call.data[ATTR_OPERATION],
                instance=call.data.get(ATTR_INSTANCE),
                payload=call.data.get(ATTR_PAYLOAD),
            )
        )

    for name, handler in (
        (SERVICE_SEND_TEXT_COMMAND, send_text_command),
        (SERVICE_PLAY_SOUND, play_sound),
        (SERVICE_RUN_ROUTINE, run_routine),
        (SERVICE_LAUNCH_SKILL, launch_skill),
        (SERVICE_CREATE_ALARM, create_alarm),
        (SERVICE_CREATE_TIMER, create_timer),
        (SERVICE_CREATE_REMINDER, create_reminder),
        (SERVICE_DELETE_NOTIFICATION, delete_notification),
        (SERVICE_GET_NOTIFICATIONS, get_notifications),
        (SERVICE_GET_VOICE_HISTORY, get_voice_history),
        (SERVICE_BLUETOOTH_CONNECT, bluetooth_connect),
        (SERVICE_BLUETOOTH_DISCONNECT, bluetooth_disconnect),
        (SERVICE_CALL_FEATURE, call_feature),
        (SERVICE_SEND_INFO_SKILL, send_info_skill),
        (SERVICE_SEND_MOBILE_PUSH, send_mobile_push),
        (SERVICE_SEND_DROP_IN_NOTIFICATION, send_drop_in_notification),
        (SERVICE_SEND_ANNOUNCEMENT, send_announcement),
        (SERVICE_ENABLE_ALARM, enable_alarm),
        (SERVICE_DISABLE_ALARM, disable_alarm),
        (SERVICE_SKIP_NEXT_ALARM, skip_next_alarm),
        (SERVICE_UPDATE_LAST_CALLED, update_last_called),
        (SERVICE_RESTORE_VOLUME, restore_volume),
        (SERVICE_REPEAT_LAST_MESSAGE, repeat_last_message),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=SCHEMAS[name],
            supports_response=RESPONSES.get(name, SupportsResponse.NONE),
        )
