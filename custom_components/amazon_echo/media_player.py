"""Media player: one per device and per speaker group."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from amazon_echo import BluetoothDevice, MediaState

from . import AmazonEchoConfigEntry
from .const import (
    DEFAULT_MUSIC_PROVIDER,
    DOMAIN,
    MEDIA_TYPE_ROUTINE,
    MEDIA_TYPE_SKILL,
    MEDIA_TYPE_SOUND,
    MEDIA_TYPE_TEXT_COMMAND,
    MEDIA_TYPE_TTS,
    SOURCE_LOCAL_SPEAKER,
)
from .entity import AmazonEchoEntity, async_add_dynamic

PARALLEL_UPDATES = 0

DESCRIPTION = MediaPlayerEntityDescription(
    key="media_player", device_class=MediaPlayerDeviceClass.SPEAKER
)
BASE_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.PLAY_MEDIA
)
STATES = {"playing": MediaPlayerState.PLAYING, "paused": MediaPlayerState.PAUSED}
UNMUTE_FALLBACK_VOLUME = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one media player per device and speaker group."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: data.devices,
        lambda serial: AmazonEchoMediaPlayer(entry.runtime_data, DESCRIPTION, serial),
    )


class AmazonEchoMediaPlayer(AmazonEchoEntity, MediaPlayerEntity):
    """An Echo, Fire TV, tablet or speaker group."""

    _attr_name = None
    _attr_media_image_remotely_accessible = True
    _previous_volume: int | None = None

    @property
    def _media(self) -> MediaState:
        return self.data.media.get(self.device.serial) or MediaState()

    @property
    def _paired(self) -> list[BluetoothDevice]:
        return self.data.bluetooth.get(self.device.serial, [])

    @property
    def _volume(self) -> int | None:
        if (volume := self.data.volumes.get(self.device.serial)) is not None:
            return volume[0]
        return self._media.volume

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Seek only when the player allows it, sources only with Bluetooth."""
        features = BASE_FEATURES
        if self._media.can_seek:
            features |= MediaPlayerEntityFeature.SEEK
        if self.device.serial in self.data.bluetooth:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        return features

    @property
    def state(self) -> MediaPlayerState:
        """Off while the device is offline, otherwise what it is playing."""
        if not self.device.online:
            return MediaPlayerState.OFF
        return STATES.get(self._media.state, MediaPlayerState.IDLE)

    @property
    def volume_level(self) -> float | None:
        """Volume 0..1."""
        return None if (volume := self._volume) is None else volume / 100

    @property
    def is_volume_muted(self) -> bool:
        """The mute flag of the API, or volume zero."""
        volume = self.data.volumes.get(self.device.serial)
        return bool(volume and volume[1]) or self._media.muted or self._volume == 0

    @property
    def media_title(self) -> str | None:
        """Title."""
        return self._media.title

    @property
    def media_artist(self) -> str | None:
        """Artist."""
        return self._media.artist

    @property
    def media_album_name(self) -> str | None:
        """Album."""
        return self._media.album

    @property
    def media_image_url(self) -> str | None:
        """Cover art."""
        return self._media.image_url

    @property
    def media_duration(self) -> float | None:
        """Duration in seconds."""
        return self._media.duration

    @property
    def media_position(self) -> float | None:
        """Position in seconds."""
        return self._media.position

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was read."""
        return self._media.position_updated_at

    @property
    def media_content_type(self) -> MediaType | None:
        """Everything Alexa plays is treated as music."""
        return MediaType.MUSIC if self._media.title else None

    @property
    def app_name(self) -> str | None:
        """Music provider."""
        return self._media.provider

    @property
    def shuffle(self) -> bool | None:
        """Shuffle."""
        return self._media.shuffle

    @property
    def repeat(self) -> RepeatMode | None:
        """Repeat (Alexa only knows on and off)."""
        if self._media.repeat is None:
            return None
        return RepeatMode.ALL if self._media.repeat else RepeatMode.OFF

    @property
    def source_list(self) -> list[str]:
        """Paired Bluetooth devices plus the device's own speaker."""
        return [p.name or p.address for p in self._paired] + [SOURCE_LOCAL_SPEAKER]

    @property
    def source(self) -> str:
        """The connected Bluetooth device, or the local speaker."""
        return next(
            (p.name or p.address for p in self._paired if p.connected),
            SOURCE_LOCAL_SPEAKER,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Members of a speaker group / groups a device belongs to."""
        devices = self.data.devices

        def names(serials: tuple[str, ...]) -> list[str]:
            return [devices[s].name for s in serials if s in devices]

        return {
            "members": names(self.device.cluster_members),
            "groups": names(self.device.parent_clusters),
        }

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    async def _async_command(
        self, command: str, state: str | None = None, **kwargs: Any
    ) -> None:
        """Send a transport command; push confirms the optimistic state."""
        await self.coordinator.async_write(
            self.coordinator.client.media_command(self.device, command, **kwargs)
        )
        if state:
            self.data.media.setdefault(self.device.serial, MediaState()).state = state
            self.coordinator.async_update_listeners()

    async def async_media_play(self) -> None:
        """Play."""
        await self._async_command("play", "playing")

    async def async_media_pause(self) -> None:
        """Pause."""
        await self._async_command("pause", "paused")

    async def async_media_stop(self) -> None:
        """Stop whatever the device is doing."""
        await self.coordinator.async_write(self.coordinator.client.stop(self.device))
        self.data.media.setdefault(self.device.serial, MediaState()).state = "idle"
        self.coordinator.async_update_listeners()

    async def async_media_next_track(self) -> None:
        """Next."""
        await self._async_command("next")

    async def async_media_previous_track(self) -> None:
        """Previous."""
        await self._async_command("previous")

    async def async_media_seek(self, position: float) -> None:
        """Alexa cannot seek to a position, only skip forward or back."""
        forward = position >= (self._media.position or 0)
        await self._async_command("forward" if forward else "rewind")

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Shuffle on/off."""
        await self._async_command("shuffle", enabled=shuffle)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Repeat on/off."""
        await self._async_command("repeat", enabled=repeat != RepeatMode.OFF)

    async def _async_set_volume(self, volume: int) -> None:
        await self.coordinator.async_write(
            self.coordinator.client.set_volume(self.device, volume)
        )
        self.data.volumes[self.device.serial] = (volume, False)
        self.coordinator.async_update_listeners()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume."""
        await self._async_set_volume(round(volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        """Alexa has no mute command: go to zero and back to the previous volume."""
        if mute:
            self._previous_volume = self._volume or self._previous_volume
            await self._async_set_volume(0)
        else:
            await self._async_set_volume(
                self._previous_volume or UNMUTE_FALLBACK_VOLUME
            )

    async def async_select_source(self, source: str) -> None:
        """Connect a paired Bluetooth device, or go back to the local speaker."""
        client = self.coordinator.client
        if source == SOURCE_LOCAL_SPEAKER:
            action = client.bluetooth_disconnect(self.device)
        else:
            paired = next(
                (p for p in self._paired if source in (p.name, p.address)), None
            )
            if paired is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="bluetooth_not_paired",
                    translation_placeholders={"address": source},
                )
            action = client.bluetooth_connect(self.device, paired.address)
        await self.coordinator.async_write(action, refresh="bluetooth")

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play music, run a routine, play a sound, open a skill, or talk."""
        client, device = self.coordinator.client, self.device
        if media_type == MediaType.MUSIC:
            provider, _, phrase = media_id.partition(":")
            if not phrase or provider not in self.data.music_providers:
                provider, phrase = DEFAULT_MUSIC_PROVIDER, media_id
            action = client.play_music(device, provider, phrase)
        elif media_type == MEDIA_TYPE_ROUTINE:
            action = client.run_routine(self.coordinator.routine(media_id), device)
        elif media_type == MEDIA_TYPE_SOUND:
            action = client.play_sound(device, media_id)
        elif media_type == MEDIA_TYPE_SKILL:
            action = client.launch_skill(device, media_id)
        elif media_type == MEDIA_TYPE_TEXT_COMMAND:
            action = client.text_command(device, media_id)
        elif media_type == MEDIA_TYPE_TTS:
            action = client.speak(device, media_id)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )
        await self.coordinator.async_write(action)
