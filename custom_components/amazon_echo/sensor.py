"""Sensors: next alarm/timer/reminder, temperature, network, batteries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from amazon_echo import Device, Notification

from . import AmazonEchoConfigEntry
from .const import CAP_REMINDERS, CAP_TIMERS_AND_ALARMS
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import AmazonEchoEntity, async_add_device_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AmazonEchoSensorDescription(SensorEntityDescription):
    """Sensor of a device; ``local`` ones are fed by the LAN probe."""

    exists_fn: Callable[[AmazonEchoData, Device], bool]
    value_fn: Callable[[AmazonEchoData, Device], StateType | datetime]
    attributes_fn: Callable[[AmazonEchoData, Device], dict[str, Any]] | None = None
    local: bool = False


def _notifications(
    data: AmazonEchoData, device: Device, kinds: tuple[str, ...]
) -> list[Notification]:
    """Notifications of a device, soonest first (the ones without a time last)."""
    return sorted(
        (
            n
            for n in data.notifications
            if n.device_serial == device.serial and n.kind in kinds
        ),
        key=lambda n: (n.when is None, n.when),
    )


def _next(key: str, capability: str, *kinds: str) -> AmazonEchoSensorDescription:
    def value(data: AmazonEchoData, device: Device) -> datetime | None:
        now = dt_util.utcnow()
        return next(
            (
                n.when
                for n in _notifications(data, device, kinds)
                if n.is_active and n.when and n.when >= now
            ),
            None,
        )

    def attributes(data: AmazonEchoData, device: Device) -> dict[str, Any]:
        return {
            "items": [
                {
                    "id": n.id,
                    "label": n.label,
                    "when": n.when.isoformat() if n.when else None,
                    "status": n.status,
                    "recurrence": n.recurrence,
                }
                for n in _notifications(data, device, kinds)
            ]
        }

    return AmazonEchoSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TIMESTAMP,
        exists_fn=lambda data, device: (
            not device.is_group and device.supports(capability)
        ),
        value_fn=value,
        attributes_fn=attributes,
    )


def _connected_bluetooth(data: AmazonEchoData, device: Device) -> str | None:
    return next(
        (
            paired.name or paired.address
            for paired in data.bluetooth.get(device.serial, [])
            if paired.connected
        ),
        None,
    )


def _setting(key: str, setting: str, **kwargs: Any) -> AmazonEchoSensorDescription:
    return AmazonEchoSensorDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: data.setting(device, setting) is not None,
        value_fn=lambda data, device: data.setting(device, setting),
        **kwargs,
    )


SENSORS: tuple[AmazonEchoSensorDescription, ...] = (
    _next("next_alarm", CAP_TIMERS_AND_ALARMS, "alarm", "music_alarm"),
    _next("next_timer", CAP_TIMERS_AND_ALARMS, "timer"),
    _next("next_reminder", CAP_REMINDERS, "reminder"),
    AmazonEchoSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        exists_fn=lambda data, device: data.endpoint(device, "temperature") is not None,
        value_fn=lambda data, device: data.endpoint(device, "temperature"),
    ),
    AmazonEchoSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: bool(
            (data.setting(device, "wifi") or (None,))[0]
        ),
        value_fn=lambda data, device: data.setting(device, "wifi")[0],
    ),
    AmazonEchoSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        local=True,
        exists_fn=lambda data, device: device.serial in data.hosts,
        value_fn=lambda data, device: data.hosts.get(device.serial),
    ),
    AmazonEchoSensorDescription(
        key="bluetooth_device",
        translation_key="bluetooth_device",
        exists_fn=lambda data, device: device.serial in data.bluetooth,
        value_fn=_connected_bluetooth,
    ),
    AmazonEchoSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: device.battery_level is not None,
        value_fn=lambda data, device: device.battery_level,
    ),
    AmazonEchoSensorDescription(
        key="remote_battery",
        translation_key="remote_battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: (
            data.endpoint(device, "remote_battery") is not None
        ),
        value_fn=lambda data, device: data.endpoint(device, "remote_battery"),
    ),
    AmazonEchoSensorDescription(
        key="spotify_user",
        translation_key="spotify_user",
        local=True,
        exists_fn=lambda data, device: device.serial in data.local,
        value_fn=lambda data, device: data.local[device.serial].spotify_user,
    ),
    _setting("time_zone", "timeZone"),
    _setting("wake_word_sensitivity", "wakeWordSensitivity"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors."""
    async_add_device_entities(entry, async_add_entities, SENSORS, AmazonEchoSensor)


class AmazonEchoSensor(AmazonEchoEntity, SensorEntity):
    """Sensor of a device."""

    entity_description: AmazonEchoSensorDescription

    def __init__(
        self,
        coordinator: AmazonEchoCoordinator,
        description: AmazonEchoSensorDescription,
        serial: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description, serial)
        self._local = description.local

    @property
    def native_value(self) -> StateType | datetime:
        """Current value."""
        return self.entity_description.value_fn(self.data, self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes (the full list for the next-* sensors)."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.data, self.device)
