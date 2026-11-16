"""Switches: do not disturb, sounds, settings, account modes and smart plugs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import Device, Endpoint

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import (
    AmazonEchoEndpointEntity,
    AmazonEchoEntity,
    async_add_device_entities,
    async_add_dynamic,
    async_add_endpoint_entities,
)
from .light import is_light

PARALLEL_UPDATES = 0

# The Fire TV ambient mode is a GraphQL toggle feature with this instance.
AMBIENT_INSTANCE = "FTV.AmbientMode"


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


def _comms(key: str, method: str) -> AmazonEchoSwitchDescription:
    """Switch of a communication preference (calls and messages, announcements)."""
    return AmazonEchoSwitchDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: key in (data.setting(device, "comms") or {}),
        is_on_fn=lambda data, device: data.setting(device, "comms")[key],
        set_fn=lambda c, device, enabled: getattr(c.client, method)(device, enabled),
        refresh="comms",
    )


def _kids_child(data: AmazonEchoData, device: Device) -> str:
    """The child a device goes to: the one it has, else the first of the house."""
    child: str = data.setting(device, "kids_profile") or next(iter(data.children))
    return child


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
    _comms("communications", "set_communications"),
    _comms("announcements", "set_announcements"),
    AmazonEchoSwitchDescription(
        key="amazon_kids",
        translation_key="amazon_kids",
        entity_category=EntityCategory.CONFIG,
        # nothing to switch on without a child profile in the household
        exists_fn=lambda data, device: (
            bool(data.children) and data.setting(device, "kids_mode") is not None
        ),
        is_on_fn=lambda data, device: data.setting(device, "kids_mode"),
        set_fn=lambda c, device, enabled: c.set_kids_mode(
            device, _kids_child(c.data, device) if enabled else None
        ),
        refresh="kids_mode",
    ),
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
            device.endpoint_id or "",
            "toggle",
            "turnOn" if enabled else "turnOff",
            instance=AMBIENT_INSTANCE,
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
    _setting("display_power", "displayPower", on="ON", off="OFF"),
    _setting("adaptive_brightness", "adaptiveBrightness", on="ON", off="OFF"),
)


@dataclass(frozen=True, kw_only=True)
class AmazonEchoEndpointSwitchDescription(SwitchEntityDescription):
    """Switch of a smart-home endpoint: a state key and the feature behind it."""

    exists_fn: Callable[[Endpoint], bool]
    feature: str
    instance: str | None = None


ENDPOINT_SWITCHES: tuple[AmazonEchoEndpointSwitchDescription, ...] = (
    # A plug, a wall switch, or anything else that only turns on and off.
    AmazonEchoEndpointSwitchDescription(
        key="power",
        name=None,
        exists_fn=lambda endpoint: (
            "power" in endpoint.state
            and endpoint.supports("power", "turnOn")
            and not is_light(endpoint)
        ),
        feature="power",
    ),
    # The LED of the Amazon Air Quality Monitor.
    AmazonEchoEndpointSwitchDescription(
        key="aqm_led",
        translation_key="aqm_led",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda endpoint: "aqm_led" in endpoint.state,
        feature="toggle",
        instance="11",
    ),
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
    async_add_endpoint_entities(
        entry, async_add_entities, ENDPOINT_SWITCHES, AmazonEchoEndpointSwitch
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


class AmazonEchoEndpointSwitch(AmazonEchoEndpointEntity, SwitchEntity):
    """Switch of a smart-home endpoint."""

    entity_description: AmazonEchoEndpointSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        value: bool | None = self.value(self.entity_description.key)
        return value

    async def _async_set(self, enabled: bool) -> None:
        description = self.entity_description
        await self._async_call(
            description.feature,
            "turnOn" if enabled else "turnOff",
            instance=description.instance,
            state={description.key: enabled},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._async_set(False)
