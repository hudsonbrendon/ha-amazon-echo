"""Notify entities: speak on a device, announce (with a chime and a title)."""

from __future__ import annotations

from homeassistant.components.notify import (
    NotifyEntity,
    NotifyEntityDescription,
    NotifyEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmazonEchoConfigEntry
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

SPEAK = NotifyEntityDescription(key="speak", translation_key="speak")
ANNOUNCE = NotifyEntityDescription(key="announce", translation_key="announce")


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


class AmazonEchoSpeak(AmazonEchoEntity, NotifyEntity):
    """Make Alexa say something on one device."""

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Speak the message."""
        await self.coordinator.async_write(
            self.coordinator.client.speak(self.device, message)
        )


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
        await self.coordinator.async_write(
            self.coordinator.client.announce(targets, message, title=title)
        )
