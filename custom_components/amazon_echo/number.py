"""Numbers: equalizer, alarm volume and speaking rate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import Device

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .data import AmazonEchoData
from .entity import AmazonEchoEntity, async_add_device_entities

PARALLEL_UPDATES = 0

SPEAKING_RATE = "alexaSpeakingRate"


@dataclass(frozen=True, kw_only=True)
class AmazonEchoNumberDescription(NumberEntityDescription):
    """Number of a device; ``refresh`` is what gets re-read after a write."""

    exists_fn: Callable[[AmazonEchoData, Device], bool]
    value_fn: Callable[[AmazonEchoData, Device], float | None]
    set_fn: Callable[[AmazonEchoCoordinator, Device, float], Awaitable[Any]]
    refresh: str


def _band(band: str) -> AmazonEchoNumberDescription:
    def set_value(c: AmazonEchoCoordinator, device: Device, value: float) -> Any:
        return c.client.set_equalizer(
            device, **{**c.data.setting(device, "equalizer"), band: int(value)}
        )

    return AmazonEchoNumberDescription(
        key=band,
        translation_key=band,
        entity_category=EntityCategory.CONFIG,
        native_min_value=-6,
        native_max_value=6,
        native_step=1,
        exists_fn=lambda data, device: (
            band in (data.setting(device, "equalizer") or {})
        ),
        value_fn=lambda data, device: data.setting(device, "equalizer")[band],
        set_fn=set_value,
        refresh="equalizer",
    )


NUMBERS: tuple[AmazonEchoNumberDescription, ...] = (
    _band("bass"),
    _band("mid"),
    _band("treble"),
    AmazonEchoNumberDescription(
        key="alarm_volume",
        translation_key="alarm_volume",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        exists_fn=lambda data, device: device.serial in data.alarm_volumes,
        value_fn=lambda data, device: data.alarm_volumes.get(device.serial),
        set_fn=lambda c, device, value: c.client.set_alarm_volume(device, int(value)),
        refresh="alarm_volumes",
    ),
    AmazonEchoNumberDescription(
        key="speaking_rate",
        translation_key="speaking_rate",
        entity_category=EntityCategory.CONFIG,
        # The accepted range was not established; this is what the app offers.
        native_min_value=0.75,
        native_max_value=2.0,
        native_step=0.05,
        exists_fn=lambda data, device: isinstance(
            data.setting(device, SPEAKING_RATE), int | float
        ),
        value_fn=lambda data, device: data.setting(device, SPEAKING_RATE),
        set_fn=lambda c, device, value: c.client.set_setting(
            device, SPEAKING_RATE, value
        ),
        refresh=SPEAKING_RATE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the numbers."""
    async_add_device_entities(entry, async_add_entities, NUMBERS, AmazonEchoNumber)


class AmazonEchoNumber(AmazonEchoEntity, NumberEntity):
    """Number of a device."""

    entity_description: AmazonEchoNumberDescription

    @property
    def native_value(self) -> float | None:
        """Current value."""
        return self.entity_description.value_fn(self.data, self.device)

    async def async_set_native_value(self, value: float) -> None:
        """Write the value."""
        description = self.entity_description
        await self.coordinator.async_write(
            description.set_fn(self.coordinator, self.device, value),
            refresh=description.refresh,
            device=self.device,
        )
