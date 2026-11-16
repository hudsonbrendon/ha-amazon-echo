"""Notify entities: speak, announce, speak on the device that was called last."""

from __future__ import annotations

from homeassistant.components.notify import (
    NotifyEntity,
    NotifyEntityDescription,
    NotifyEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmazonEchoConfigEntry
from .const import DOMAIN
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

SPEAK = NotifyEntityDescription(key="speak", translation_key="speak")
ANNOUNCE = NotifyEntityDescription(key="announce", translation_key="announce")
SPEAK_LAST_CALLED = NotifyEntityDescription(
    key="speak_last_called", translation_key="speak_last_called"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create speak (devices) and announce (devices and groups) entities."""
    coordinator = entry.runtime_data
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (d.serial for d in data.devices.values() if not d.is_group),
        lambda serial: AmazonEchoSpeak(coordinator, SPEAK, serial),
    )
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: data.devices,
        lambda serial: AmazonEchoAnnounce(coordinator, ANNOUNCE, serial),
    )
    async_add_entities([AmazonEchoSpeakLastCalled(coordinator, SPEAK_LAST_CALLED)])


class AmazonEchoSpeak(AmazonEchoEntity, NotifyEntity):
    """Make Alexa say something on one device."""

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Speak the message."""
        await self.coordinator.async_say("speak", [self.device], message)


class AmazonEchoAnnounce(AmazonEchoEntity, NotifyEntity):
    """Announce on a device or on every member of a speaker group."""

    _attr_supported_features = NotifyEntityFeature.TITLE

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Announce the message."""
        devices = self.data.devices
        targets = [
            devices[serial]
            for serial in self.device.cluster_members
            if serial in devices
        ] or [self.device]
        await self.coordinator.async_say("announce", targets, message, title)


class AmazonEchoSpeakLastCalled(AmazonEchoEntity, NotifyEntity):
    """Answer on whichever device heard the last voice request (account device)."""

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Speak the message on the device that was called last."""
        record = self.data.last_called
        device = self.data.devices.get((record.device_serial or "") if record else "")
        if device is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_last_called"
            )
        await self.coordinator.async_say("speak", [device], message)
