"""Locks linked to Alexa (only with the smart-home option turned on)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmazonEchoConfigEntry
from .const import DOMAIN
from .entity import AmazonEchoEndpointEntity, async_add_dynamic

PARALLEL_UPDATES = 0

DESCRIPTION = LockEntityDescription(key="lock", name=None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one lock per smart-home lock."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (e.id for e in data.smart_home.values() if "lock" in e.state),
        lambda endpoint_id: AmazonEchoLock(
            entry.runtime_data, DESCRIPTION, endpoint_id
        ),
    )


class AmazonEchoLock(AmazonEchoEndpointEntity, LockEntity):
    """A lock controlled through Alexa."""

    @property
    def is_locked(self) -> bool | None:
        """Whether the lock is locked."""
        state = self.value("lock")
        return None if state is None else state == "LOCKED"

    @property
    def is_jammed(self) -> bool:
        """Whether the bolt is stuck."""
        return bool(self.value("lock") == "JAMMED")

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock."""
        await self._async_call("lock", "lock", state={"lock": "LOCKED"})

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock, when Amazon lets the app do it for this lock."""
        if not self.endpoint.supports("lock", "unlock"):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unlock_not_supported"
            )
        await self._async_call("lock", "unlock", state={"lock": "UNLOCKED"})
