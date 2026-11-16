"""Selects: wake word, alarm sound, AUX, time format, Drop In, default device."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from amazon_echo import Device

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import AmazonEchoEntity, async_add_device_entities
from .media_player import is_player

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AmazonEchoSelectDescription(SelectEntityDescription):
    """Select of a device; ``options_fn`` when the choices come from the device."""

    exists_fn: Callable[[AmazonEchoData, Device], bool]
    current_fn: Callable[[AmazonEchoData, Device], str | None]
    select_fn: Callable[[AmazonEchoCoordinator, Device, str], Awaitable[Any]]
    refresh: str
    options_fn: Callable[[AmazonEchoData, Device], list[str]] | None = None


def _alarm_sounds(data: AmazonEchoData, device: Device) -> dict[str, str]:
    sounds: dict[str, str] = data.setting(device, "alarm_sounds") or {}
    return sounds


def _select_alarm_sound(c: AmazonEchoCoordinator, device: Device, option: str) -> Any:
    sounds = _alarm_sounds(c.data, device)
    sound_id = next(key for key, name in sounds.items() if name == option)
    return c.client.set_default_alarm_sound(device, sound_id)


def _aux(data: AmazonEchoData, device: Device) -> Any:
    ports = data.setting(device, "aux")
    return ports[0] if ports else None


def _select_child(c: AmazonEchoCoordinator, device: Device, option: str) -> Any:
    child_id = next(key for key, name in c.data.children.items() if name == option)
    return c.set_kids_mode(device, child_id)


SELECTS: tuple[AmazonEchoSelectDescription, ...] = (
    AmazonEchoSelectDescription(
        key="wake_word",
        translation_key="wake_word",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: (
            device.serial in data.wake_words
            and bool(data.setting(device, "available_wake_words"))
        ),
        options_fn=lambda data, device: list(
            data.setting(device, "available_wake_words")
        ),
        current_fn=lambda data, device: data.wake_words.get(device.serial),
        select_fn=lambda c, device, option: c.client.set_wake_word(device, option),
        refresh="wake_words",
    ),
    AmazonEchoSelectDescription(
        key="alarm_sound",
        translation_key="alarm_sound",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: bool(_alarm_sounds(data, device)),
        options_fn=lambda data, device: list(_alarm_sounds(data, device).values()),
        current_fn=lambda data, device: _alarm_sounds(data, device).get(
            data.setting(device, "alarm_sound")
        ),
        select_fn=_select_alarm_sound,
        refresh="alarm_sound",
    ),
    AmazonEchoSelectDescription(
        key="aux_direction",
        translation_key="aux_direction",
        entity_category=EntityCategory.CONFIG,
        options=["input", "output"],
        exists_fn=lambda data, device: _aux(data, device) is not None,
        current_fn=lambda data, device: _aux(data, device).direction.lower(),
        select_fn=lambda c, device, option: c.client.set_aux_direction(
            device, _aux(c.data, device).id, option.upper()
        ),
        refresh="aux",
    ),
    AmazonEchoSelectDescription(
        key="time_format",
        translation_key="time_format",
        entity_category=EntityCategory.CONFIG,
        options=["12_hours", "24_hours"],
        exists_fn=lambda data, device: isinstance(
            data.setting(device, "timeFormat"), str
        ),
        current_fn=lambda data, device: data.setting(device, "timeFormat").lower(),
        select_fn=lambda c, device, option: c.client.set_setting(
            device, "timeFormat", option.upper()
        ),
        refresh="timeFormat",
    ),
    AmazonEchoSelectDescription(
        key="drop_in",
        translation_key="drop_in",
        entity_category=EntityCategory.CONFIG,
        options=["all", "home", "off"],
        exists_fn=lambda data, device: (
            "drop_in" in (data.setting(device, "comms") or {})
        ),
        current_fn=lambda data, device: data.setting(device, "comms")["drop_in"],
        select_fn=lambda c, device, option: c.client.set_drop_in(device, option),
        refresh="comms",
    ),
    AmazonEchoSelectDescription(
        key="amazon_kids_profile",
        translation_key="amazon_kids_profile",
        entity_category=EntityCategory.CONFIG,
        exists_fn=lambda data, device: (
            bool(data.children) and data.setting(device, "kids_mode") is not None
        ),
        options_fn=lambda data, device: list(data.children.values()),
        current_fn=lambda data, device: data.children.get(
            data.setting(device, "kids_profile") or ""
        ),
        select_fn=_select_child,
        refresh="kids_mode",
    ),
)


DEFAULT_DEVICE = SelectEntityDescription(
    key="default_device",
    translation_key="default_device",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the selects."""
    async_add_device_entities(entry, async_add_entities, SELECTS, AmazonEchoSelect)
    async_add_entities(
        [AmazonEchoDefaultDeviceSelect(entry.runtime_data, DEFAULT_DEVICE)]
    )


class AmazonEchoSelect(AmazonEchoEntity, SelectEntity):
    """Select of a device."""

    entity_description: AmazonEchoSelectDescription

    @property
    def options(self) -> list[str]:
        """Choices, from the device when they are not fixed."""
        description = self.entity_description
        if description.options_fn is None:
            return description.options or []
        return description.options_fn(self.data, self.device)

    @property
    def current_option(self) -> str | None:
        """Current choice (None when the device reports one that is not offered)."""
        current = self.entity_description.current_fn(self.data, self.device)
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Write the choice."""
        description = self.entity_description
        await self.coordinator.async_write(
            description.select_fn(self.coordinator, self.device, option),
            refresh=description.refresh,
            device=self.device,
        )


class AmazonEchoDefaultDeviceSelect(AmazonEchoEntity, SelectEntity, RestoreEntity):
    """The device that routines run on when they have none of their own.

    A routine started by voice acts on "the device that heard it"; started
    from a button there is no such device, so this one stands in. The choice
    lives in Home Assistant (restored on restart), not at Amazon.
    """

    async def async_added_to_hass(self) -> None:
        """Restore the last choice."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self.coordinator.default_device = self._serial_of(last.state)

    def _serial_of(self, name: str) -> str | None:
        return next(
            (d.serial for d in self.data.devices.values() if d.name == name), None
        )

    @property
    def options(self) -> list[str]:
        """Every device that can play something."""
        return sorted(d.name for d in self.data.devices.values() if is_player(d))

    @property
    def current_option(self) -> str | None:
        """Name of the chosen device, None while none is chosen."""
        device = self.data.devices.get(self.coordinator.default_device or "")
        return device.name if device else None

    async def async_select_option(self, option: str) -> None:
        """Choose the device."""
        self.coordinator.default_device = self._serial_of(option)
        self.async_write_ha_state()
