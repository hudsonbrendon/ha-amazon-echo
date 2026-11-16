"""Event entity fired when a device hears a voice command."""

from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import VoiceRecord

from . import AmazonEchoConfigEntry
from .const import EVENT_VOICE_COMMAND, SIGNAL_VOICE
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

VOICE = EventEntityDescription(
    key="voice", translation_key="voice", event_types=[EVENT_VOICE_COMMAND]
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one voice event entity per device."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (d.serial for d in data.devices.values() if not d.is_group),
        lambda serial: AmazonEchoVoiceEvent(entry.runtime_data, VOICE, serial),
    )


class AmazonEchoVoiceEvent(AmazonEchoEntity, EventEntity):
    """Fires ``voice_command`` with what was said and what Alexa answered."""

    async def async_added_to_hass(self) -> None:
        """Subscribe to the voice records of this account."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_VOICE}_{self.coordinator.config_entry.entry_id}",
                self._handle_record,
            )
        )

    @callback
    def _handle_record(self, record: VoiceRecord) -> None:
        if record.device_serial != self._serial:
            return
        self._trigger_event(
            EVENT_VOICE_COMMAND,
            {
                "utterance": record.utterance,
                "response": record.response,
                "intent": record.intent,
                "person": record.person,
            },
        )
        self.async_write_ha_state()
