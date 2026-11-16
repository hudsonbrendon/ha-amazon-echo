"""Binary sensors: cloud and LAN connectivity, AUX cable, charging."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import Device

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import AmazonEchoEntity, async_add_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AmazonEchoBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor of a device; ``local`` ones are fed by the LAN probe."""

    exists_fn: Callable[[AmazonEchoData, Device], bool]
    is_on_fn: Callable[[AmazonEchoData, Device], bool | None]
    local: bool = False


BINARY_SENSORS: tuple[AmazonEchoBinarySensorDescription, ...] = (
    AmazonEchoBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: not device.is_group,
        is_on_fn=lambda data, device: device.online,
    ),
    AmazonEchoBinarySensorDescription(
        key="local_reachable",
        translation_key="local_reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        local=True,
        exists_fn=lambda data, device: device.serial in data.reachable,
        is_on_fn=lambda data, device: data.reachable.get(device.serial),
    ),
    AmazonEchoBinarySensorDescription(
        key="aux_plugged",
        translation_key="aux_plugged",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: bool(data.setting(device, "aux")),
        is_on_fn=lambda data, device: any(
            port.plugged for port in data.setting(device, "aux")
        ),
    ),
    AmazonEchoBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: device.charging is not None,
        is_on_fn=lambda data, device: device.charging,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the binary sensors."""
    async_add_device_entities(
        entry, async_add_entities, BINARY_SENSORS, AmazonEchoBinarySensor
    )


class AmazonEchoBinarySensor(AmazonEchoEntity, BinarySensorEntity):
    """Binary sensor of a device."""

    entity_description: AmazonEchoBinarySensorDescription

    def __init__(
        self,
        coordinator: AmazonEchoCoordinator,
        description: AmazonEchoBinarySensorDescription,
        serial: str,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description, serial)
        self._local = description.local

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        return self.entity_description.is_on_fn(self.data, self.device)
