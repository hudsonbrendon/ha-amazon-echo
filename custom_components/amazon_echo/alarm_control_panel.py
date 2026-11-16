"""Alexa Guard as an alarm panel (only for accounts that have Guard)."""

from __future__ import annotations

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityDescription,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmazonEchoConfigEntry
from .const import CAP_GUARD
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

GUARD = AlarmControlPanelEntityDescription(key="guard", translation_key="guard")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the Guard panel once the account turns out to have one."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: [GUARD.key] if data.guard is not None else [],
        lambda _key: AmazonEchoGuard(entry.runtime_data, GUARD),
    )


class AmazonEchoGuard(AmazonEchoEntity, AlarmControlPanelEntity):
    """Alexa Guard: away (armed) or home (disarmed)."""

    _attr_supported_features = AlarmControlPanelEntityFeature.ARM_AWAY
    _attr_code_arm_required = False

    @property
    def available(self) -> bool:
        """Unavailable if the account lost Guard."""
        return super().available and self.data.guard is not None

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Armed away, or disarmed for every other state Guard reports."""
        guard = self.data.guard
        if guard is None or guard.state is None:
            return None
        if guard.armed:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    async def _async_set(self, armed: bool) -> None:
        guard = self.data.guard
        assert guard is not None
        # The app sends the command through an Echo that has Guard.
        echo = next(
            (
                device
                for device in self.data.devices.values()
                if device.online and device.supports(CAP_GUARD)
            ),
            None,
        )
        await self.coordinator.async_write(
            self.coordinator.client.set_guard(guard, armed, echo), refresh="guard"
        )

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Switch Guard to away."""
        await self._async_set(True)

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Switch Guard to home."""
        await self._async_set(False)
