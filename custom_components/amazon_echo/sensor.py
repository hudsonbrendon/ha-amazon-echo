"""Sensors: next alarm/timer/reminder, environment, network, last called."""

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
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfDensity,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from amazon_echo import Device, Endpoint, Notification

from . import AmazonEchoConfigEntry
from .const import CAP_REMINDERS, CAP_TIMERS_AND_ALARMS
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
        key=lambda n: n.when.timestamp() if n.when else float("inf"),
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
        """Describe the next one, and list them all."""
        now = dt_util.utcnow()
        every = _notifications(data, device, kinds)
        active = [n for n in every if n.is_active and n.when and n.when >= now]
        upcoming = active[0] if active else None
        return {
            "label": upcoming.label if upcoming else None,
            "sub_label": upcoming.raw.get("reminderSubLabel") if upcoming else None,
            "recurrence": upcoming.recurrence if upcoming else None,
            "status": upcoming.status if upcoming else None,
            "total_active": len(active),
            "total_all": len(every),
            "items": [
                {
                    "id": n.id,
                    "label": n.label,
                    "when": n.when.isoformat() if n.when else None,
                    "status": n.status,
                    "recurrence": n.recurrence,
                }
                for n in every
            ],
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


def _time_zone(data: AmazonEchoData, device: Device) -> str | None:
    """Time zone from the device setting, else from the account's preferences."""
    zone: str | None = data.setting(device, "timeZone") or data.device_preferences.get(
        device.serial, {}
    ).get("time_zone")
    return zone


def _setting(key: str, setting: str, **kwargs: Any) -> AmazonEchoSensorDescription:
    return AmazonEchoSensorDescription(
        key=key,
        translation_key=key,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: data.setting(device, setting) is not None,
        value_fn=lambda data, device: data.setting(device, setting),
        **kwargs,
    )


# What an endpoint (Alexa device or smart-home device) can measure, by the key
# of the value in its GraphQL state. An entity is created once a value shows up.
MEASUREMENTS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="illuminance",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
    ),
    SensorEntityDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    ),
    SensorEntityDescription(
        key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
    ),
    SensorEntityDescription(
        key="co",
        device_class=SensorDeviceClass.CO,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
    ),
    # Amazon reports VOC as an index, which has no device class.
    SensorEntityDescription(key="voc"),
    SensorEntityDescription(key="air_quality", device_class=SensorDeviceClass.AQI),
    SensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _measurement(description: SensorEntityDescription) -> AmazonEchoSensorDescription:
    """Sensor of an Alexa device fed by its GraphQL endpoint state."""
    key = description.key
    return AmazonEchoSensorDescription(
        key=key,
        translation_key=key,
        device_class=description.device_class,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=description.native_unit_of_measurement,
        exists_fn=lambda data, device: data.endpoint(device, key) is not None,
        value_fn=lambda data, device: data.endpoint(device, key),
    )


@dataclass(frozen=True, kw_only=True)
class AmazonEchoEndpointSensorDescription(SensorEntityDescription):
    """Sensor of a smart-home endpoint."""

    exists_fn: Callable[[Endpoint], bool]


ENDPOINT_SENSORS: tuple[AmazonEchoEndpointSensorDescription, ...] = tuple(
    AmazonEchoEndpointSensorDescription(
        key=description.key,
        translation_key=description.key,
        device_class=description.device_class,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=description.native_unit_of_measurement,
        entity_category=description.entity_category,
        exists_fn=lambda endpoint, key=description.key: (
            endpoint.state.get(key) is not None
        ),
    )
    for description in MEASUREMENTS
)

SENSORS: tuple[AmazonEchoSensorDescription, ...] = (
    _next("next_alarm", CAP_TIMERS_AND_ALARMS, "alarm", "music_alarm"),
    _next("next_timer", CAP_TIMERS_AND_ALARMS, "timer"),
    _next("next_reminder", CAP_REMINDERS, "reminder"),
    # The battery of an Alexa device comes from the device list (below).
    *(_measurement(d) for d in MEASUREMENTS if d.key != "battery"),
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
    AmazonEchoSensorDescription(
        key="time_zone",
        translation_key="time_zone",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda data, device: _time_zone(data, device) is not None,
        value_fn=lambda data, device: _time_zone(data, device),
    ),
    _setting("wake_word_sensitivity", "wakeWordSensitivity"),
)

LAST_CALLED = SensorEntityDescription(key="last_called", translation_key="last_called")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors."""
    async_add_device_entities(entry, async_add_entities, SENSORS, AmazonEchoSensor)
    async_add_endpoint_entities(
        entry, async_add_entities, ENDPOINT_SENSORS, AmazonEchoEndpointSensor
    )
    async_add_entities([AmazonEchoLastCalledSensor(entry.runtime_data, LAST_CALLED)])


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


class AmazonEchoEndpointSensor(AmazonEchoEndpointEntity, SensorEntity):
    """Sensor of a smart-home endpoint."""

    @property
    def native_value(self) -> StateType:
        """Current value."""
        value: StateType = self.value(self.entity_description.key)
        return value


class AmazonEchoLastCalledSensor(AmazonEchoEntity, SensorEntity):
    """The device that answered the last voice request (account device)."""

    @property
    def native_value(self) -> str | None:
        """Name of the device, None until someone talks to Alexa."""
        if (record := self.data.last_called) is None:
            return None
        device = self.data.devices.get(record.device_serial or "")
        return device.name if device else record.device_serial

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """What was said, what Alexa answered, when and to whom."""
        if (record := self.data.last_called) is None:
            return None
        return {
            "utterance": record.utterance,
            "response": record.response,
            "timestamp": record.timestamp.isoformat(),
            "person": record.person,
            "intent": record.intent,
        }
