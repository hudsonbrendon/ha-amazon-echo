"""Binary sensors: connectivity, AUX cable, charging, motion and contact."""

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

from amazon_echo import Device, Endpoint

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import (
    AmazonEchoEndpointEntity,
    AmazonEchoEntity,
    async_add_device_entities,
    async_add_endpoint_entities,
)

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
    AmazonEchoBinarySensorDescription(
        key="motion",
        translation_key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        exists_fn=lambda data, device: data.endpoint(device, "motion") is not None,
        is_on_fn=lambda data, device: data.endpoint(device, "motion"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class AmazonEchoEndpointBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor of a smart-home endpoint, named after its state key."""

    exists_fn: Callable[[Endpoint], bool]


ENDPOINT_BINARY_SENSORS: tuple[AmazonEchoEndpointBinarySensorDescription, ...] = tuple(
    AmazonEchoEndpointBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=device_class,
        exists_fn=lambda endpoint, key=key: endpoint.state.get(key) is not None,
    )
    for key, device_class in (
        ("contact", BinarySensorDeviceClass.DOOR),
        ("motion", BinarySensorDeviceClass.MOTION),
    )
)


PUSH_CONNECTED = BinarySensorEntityDescription(
    key="push_connected",
    translation_key="push_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
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
    async_add_entities([AmazonEchoPushSensor(entry.runtime_data, PUSH_CONNECTED)])
    async_add_endpoint_entities(
        entry,
        async_add_entities,
        ENDPOINT_BINARY_SENSORS,
        AmazonEchoEndpointBinarySensor,
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


class AmazonEchoPushSensor(AmazonEchoEntity, BinarySensorEntity):
    """Whether real-time updates are arriving (account device)."""

    _local = True  # says "off" instead of going unavailable with the cloud

    @property
    def is_on(self) -> bool:
        """True while the push stream is open."""
        return bool(self.coordinator.push_connected)


class AmazonEchoEndpointBinarySensor(AmazonEchoEndpointEntity, BinarySensorEntity):
    """Contact or motion sensor linked to Alexa."""

    @property
    def is_on(self) -> bool | None:
        """Open / motion detected."""
        value: bool | None = self.value(self.entity_description.key)
        return value
