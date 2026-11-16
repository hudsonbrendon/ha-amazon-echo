"""Switches: do not disturb, sounds, per-device settings and account modes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import Device

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import AmazonEchoEntity, async_add_device_entities, async_add_dynamic

PARALLEL_UPDATES = 0

# GraphQL feature behind the Fire TV ambient mode toggle (see README).
AMBIENT_FEATURE = "ambientMode"


@dataclass(frozen=True, kw_only=True)
class AmazonEchoSwitchDescription(SwitchEntityDescription):
    """Switch of a device; ``refresh`` is what gets re-read after a write."""

    exists_fn: Callable[[AmazonEchoData, Device], bool]
    is_on_fn: Callable[[AmazonEchoData, Device], bool | None]
    set_fn: Callable[[AmazonEchoCoordinator, Device, bool], Awaitable[Any]]
    refresh: str


def _setting(
    key: str,
    setting: str,
    *,
    on: Any = "ENABLED",
    off: Any = "DISABLED",
    field: str | None = None,
) -> AmazonEchoSwitchDescription:
    """Switch backed by a device setting.

    ``on``/``off`` are the stored encodings; with ``field`` the setting is an
    object and only that member is toggled, the rest is sent back untouched.
    """

    def is_on(data: AmazonEchoData, device: Device) -> bool:
        value = data.setting(device, setting)
        return bool((value.get(field) if field else value) == on)

    def set_value(c: AmazonEchoCoordinator, device: Device, enabled: bool) -> Any:
        value = on if enabled else off
        if field:
            value = {**c.data.setting(device, setting), field: value}
        return c.client.set_setting(device, setting, value)

    return AmazonEchoSwitchDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: (
            isinstance(data.setting(device, setting), dict)
            if field
            else data.setting(device, setting) is not None
        ),
        is_on_fn=is_on,
        set_fn=set_value,
        refresh=setting,
    )


def _earcon(key: str, earcon: str) -> AmazonEchoSwitchDescription:
    def set_value(c: AmazonEchoCoordinator, device: Device, enabled: bool) -> Any:
        return c.client.set_earcons(
            device, **{**c.data.setting(device, "earcons"), earcon: enabled}
        )

    return AmazonEchoSwitchDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: (
            earcon in (data.setting(device, "earcons") or {})
        ),
        is_on_fn=lambda data, device: data.setting(device, "earcons")[earcon],
        set_fn=set_value,
        refresh="earcons",
    )


SWITCHES: tuple[AmazonEchoSwitchDescription, ...] = (
    AmazonEchoSwitchDescription(
        key="do_not_disturb",
        translation_key="do_not_disturb",
        exists_fn=lambda data, device: device.serial in data.dnd,
        is_on_fn=lambda data, device: data.dnd.get(device.serial),
        set_fn=lambda c, device, enabled: c.client.set_dnd(device, enabled),
        refresh="dnd",
    ),
    AmazonEchoSwitchDescription(
        key="ascending_alarm",
        translation_key="ascending_alarm",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: device.serial in data.ascending_alarms,
        is_on_fn=lambda data, device: data.ascending_alarms.get(device.serial),
        set_fn=lambda c, device, enabled: c.client.set_ascending_alarm(device, enabled),
        refresh="ascending_alarms",
    ),
    _earcon("wake_word_sound", "wake_word"),
    _earcon("end_of_request_sound", "end_of_speech"),
    AmazonEchoSwitchDescription(
        key="ambient_mode",
        translation_key="ambient_mode",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: (
            device.endpoint_id is not None
            and data.endpoint(device, "ambient_mode") is not None
        ),
        is_on_fn=lambda data, device: bool(data.endpoint(device, "ambient_mode")),
        set_fn=lambda c, device, enabled: c.client.call_feature(
            device.endpoint_id, AMBIENT_FEATURE, "turnOn" if enabled else "turnOff"
        ),
        refresh="endpoints",
    ),
    # Setting key -> stored on/off encoding.
    _setting("adaptive_listening", "adaptiveListening"),
    _setting("captions", "alexaCaptions"),
    _setting("gestures", "alexaGestures", on=True, off=False),
    _setting("night_mode", "deviceNightMode", field="nightModeEnablement"),
    _setting("smart_motion", "smartMotion", on="ON", off="OFF"),
    _setting("visual_gesture", "visualGesture"),
    _setting("tap_gestures", "tapGestures", field="enablement"),
)

# Account switches: data attribute, ``set_<key>`` client method and refresh key
# all share the description key.
ACCOUNT_SWITCHES: tuple[SwitchEntityDescription, ...] = tuple(
    SwitchEntityDescription(
        key=key, translation_key=key, entity_category=EntityCategory.CONFIG
    )
    for key in ("whisper_mode", "adaptive_volume")
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the switches."""
    async_add_device_entities(entry, async_add_entities, SWITCHES, AmazonEchoSwitch)
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (
            description
            for description in ACCOUNT_SWITCHES
            if getattr(data, description.key) is not None
        ),
        lambda description: AmazonEchoAccountSwitch(entry.runtime_data, description),
    )


class AmazonEchoSwitch(AmazonEchoEntity, SwitchEntity):
    """Switch of a device."""

    entity_description: AmazonEchoSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        return self.entity_description.is_on_fn(self.data, self.device)

    async def _async_set(self, enabled: bool) -> None:
        description = self.entity_description
        await self.coordinator.async_write(
            description.set_fn(self.coordinator, self.device, enabled),
            refresh=description.refresh,
            device=self.device,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        await self._async_set(False)


class AmazonEchoAccountSwitch(AmazonEchoEntity, SwitchEntity):
    """Switch of an account-wide preference."""

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        value: bool | None = getattr(self.data, self.entity_description.key)
        return value

    async def _async_set(self, enabled: bool) -> None:
        key = self.entity_description.key
        await self.coordinator.async_write(
            getattr(self.coordinator.client, f"set_{key}")(enabled), refresh=key
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        await self._async_set(False)
