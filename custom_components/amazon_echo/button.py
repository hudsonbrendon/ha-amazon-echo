"""Buttons: reboot a device, run a routine."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import Routine

from . import AmazonEchoConfigEntry
from .const import CAP_REBOOT
from .coordinator import AmazonEchoCoordinator
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

REBOOT = ButtonEntityDescription(
    key="reboot",
    translation_key="reboot",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the reboot buttons and one button per enabled routine."""
    coordinator = entry.runtime_data
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (
            device.serial
            for device in data.devices.values()
            if device.supports(CAP_REBOOT)
        ),
        lambda serial: AmazonEchoRebootButton(coordinator, REBOOT, serial),
    )
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (routine.id for routine in data.routines if routine.enabled),
        lambda routine_id: AmazonEchoRoutineButton(coordinator, routine_id),
    )


class AmazonEchoRebootButton(AmazonEchoEntity, ButtonEntity):
    """Reboot a device."""

    async def async_press(self) -> None:
        """Reboot."""
        await self.coordinator.async_write(self.coordinator.client.reboot(self.device))


class AmazonEchoRoutineButton(AmazonEchoEntity, ButtonEntity):
    """Run a routine of the account."""

    _attr_translation_key = "routine"

    def __init__(self, coordinator: AmazonEchoCoordinator, routine_id: str) -> None:
        """Initialise the button of one routine."""
        super().__init__(
            coordinator, ButtonEntityDescription(key=f"routine_{routine_id}")
        )
        self._routine_id = routine_id
        self._attr_translation_placeholders = {
            "name": coordinator.routine(routine_id).name
        }

    @property
    def _routine(self) -> Routine | None:
        return next(
            (
                routine
                for routine in self.data.routines
                if routine.id == self._routine_id and routine.enabled
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """Unavailable once the routine is disabled or deleted."""
        return super().available and self._routine is not None

    async def async_press(self) -> None:
        """Run the routine on its own device."""
        if (routine := self._routine) is not None:
            await self.coordinator.async_write(
                self.coordinator.client.run_routine(routine)
            )
