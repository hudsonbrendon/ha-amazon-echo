"""Base entity and dynamic entity registration for Amazon Echo."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceEntryType,
    DeviceInfo,
)
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from amazon_echo import Device

from .const import DOMAIN, MANUFACTURER
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData

if TYPE_CHECKING:
    from . import AmazonEchoConfigEntry


def device_info(coordinator: AmazonEchoCoordinator, device: Device) -> DeviceInfo:
    """Describe an Alexa-enabled device."""
    info = DeviceInfo(
        identifiers={(DOMAIN, device.serial)},
        manufacturer=MANUFACTURER,
        name=device.name,
        model=device.model or device.family,
        model_id=device.device_type,
        sw_version=device.software_version,
        serial_number=device.serial,
    )
    if mac := coordinator.data.mac(device):
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return info


def account_device_info(coordinator: AmazonEchoCoordinator) -> DeviceInfo:
    """Describe the service device that holds the account-level entities."""
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        name=entry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


class AmazonEchoEntity(CoordinatorEntity[AmazonEchoCoordinator]):
    """Entity of a device (``serial``) or of the account (``serial`` is None)."""

    _attr_has_entity_name = True
    # Local entities stay available while the cloud is unreachable.
    _local = False

    def __init__(
        self,
        coordinator: AmazonEchoCoordinator,
        description: EntityDescription,
        serial: str | None = None,
    ) -> None:
        """Bind the entity to its device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial
        entry = coordinator.config_entry
        if serial is None:
            owner = entry.unique_id or entry.entry_id
            self._attr_device_info = account_device_info(coordinator)
        else:
            owner = serial
            self._device = coordinator.data.devices[serial]
            self._attr_device_info = device_info(coordinator, self._device)
        self._attr_unique_id = f"{owner}_{description.key}"

    @property
    def data(self) -> AmazonEchoData:
        """Shortcut to the latest snapshot."""
        return self.coordinator.data

    @property
    def device(self) -> Device:
        """The device of this entity (last known one if it left the account)."""
        assert self._serial is not None
        self._device = self.data.devices.get(self._serial, self._device)
        return self._device

    @property
    def available(self) -> bool:
        """Cloud entities follow the coordinator; local ones only need the device."""
        known = self._serial is None or self._serial in self.data.devices
        return known and (self._local or super().available)


@callback
def async_add_dynamic(
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    keys_fn: Callable[[AmazonEchoData], Iterable[Hashable]],
    factory: Callable[[Any], Entity],
) -> None:
    """Create an entity for every key now and whenever a new key shows up."""
    coordinator = entry.runtime_data
    # ponytail: keys are never forgotten; a device that leaves the account and
    # comes back gets its entities again on the next reload.
    known: set[Hashable] = set()

    @callback
    def add_new() -> None:
        new = [key for key in keys_fn(coordinator.data) if key not in known]
        if new:
            known.update(new)
            async_add_entities(factory(key) for key in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


@callback
def async_add_device_entities(
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    descriptions: Sequence[Any],
    entity_cls: Callable[[AmazonEchoCoordinator, Any, str], Entity],
) -> None:
    """Create per-device entities for the descriptions each device supports."""
    by_key = {description.key: description for description in descriptions}
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (
            (device.serial, description.key)
            for device in data.devices.values()
            for description in descriptions
            if description.exists_fn(data, device)
        ),
        lambda key: entity_cls(entry.runtime_data, by_key[key[1]], key[0]),
    )
