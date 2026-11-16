"""Audio files played as announcements (ffmpeg and the network are mocked)."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
import hashlib
import os
from pathlib import Path
import sys
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo.audio import FFMPEG_ARGS
from custom_components.amazon_echo.const import CONF_PUBLIC_URL

from .conftest import ECHO, FakePush, setup_integration

AUDIO = "custom_components.amazon_echo.audio"
SOUND = b"RIFF-not-really-a-wav"
NAME = f"{hashlib.sha256(SOUND).hexdigest()[:32]}.mp3"
TTS = "media-source://tts/fake_engine?message=Dinner+is+ready"


class FakeResponse:
    """What ``session.get`` returns: an async context manager with a body."""

    def __init__(self, *chunks: bytes, error: Exception | None = None) -> None:
        self.chunks, self.error = chunks, error
        self.content = self

    async def __aenter__(self) -> FakeResponse:
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def iter_chunked(self, _size: int) -> Any:
        for chunk in self.chunks:
            yield chunk


@pytest.fixture(autouse=True)
async def loaded(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
    tmp_path: Path,
) -> None:
    hass.config.config_dir = str(tmp_path)
    await async_process_ha_core_config(hass, {"external_url": "https://ha.example.com"})
    await setup_integration(hass, mock_config_entry)


@pytest.fixture
def session() -> Generator[MagicMock]:
    """The HTTP session audio is downloaded with."""
    session = MagicMock()
    session.get.return_value = FakeResponse(SOUND[:4], SOUND[4:])
    with patch(f"{AUDIO}.async_get_clientsession", return_value=session):
        yield session


@pytest.fixture
def ffmpeg() -> Generator[AsyncMock]:
    """Home Assistant's ffmpeg: set up, and a process that writes its output."""
    process = MagicMock(returncode=0, kill=MagicMock())
    process.communicate = AsyncMock(return_value=(b"", b""))

    async def run(*args: str, **_: Any) -> MagicMock:
        if not process.returncode:
            Path(args[-1]).write_bytes(b"mp3")
        return process

    component = MagicMock()
    component.get_ffmpeg_manager.return_value.binary = "/usr/bin/fake-ffmpeg"
    with (
        patch.dict(sys.modules, {"homeassistant.components.ffmpeg": component}),
        patch(f"{AUDIO}.asyncio.create_subprocess_exec", side_effect=run) as execute,
    ):
        execute.process = process
        yield execute


async def _play(hass: HomeAssistant, media_id: str, **data: Any) -> None:
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.kitchen_echo",
            "media_content_type": "music",
            "media_content_id": media_id,
            **data,
        },
        blocking=True,
    )


async def test_text_to_speech_is_transcoded_published_and_spoken(
    hass: HomeAssistant,
    mock_client: MagicMock,
    session: MagicMock,
    ffmpeg: AsyncMock,
    tmp_path: Path,
) -> None:
    resolved = PlayMedia(url="/api/tts_proxy/abc.mp3", mime_type="audio/mpeg")
    with patch(
        f"{AUDIO}.media_source.async_resolve_media", AsyncMock(return_value=resolved)
    ) as resolve:
        await _play(hass, TTS, announce=True)
    assert resolve.await_args.args[1:] == (TTS, "media_player.kitchen_echo")
    # downloaded from Home Assistant itself
    assert session.get.call_args.args[0].endswith("/api/tts_proxy/abc.mp3")

    # the arguments Alexa Media Player gives ffmpeg: MP3, 48 kbit/s, 24 kHz
    command = ffmpeg.call_args.args
    assert command[0] == "/usr/bin/fake-ffmpeg"
    assert FFMPEG_ARGS == (
        *("-ac", "2", "-codec:a", "libmp3lame"),
        *("-b:a", "48k", "-ar", "24000", "-write_xing", "0"),
    )
    index = command.index("-i")
    assert command[index + 2 : index + 2 + len(FFMPEG_ARGS)] == FFMPEG_ARGS
    assert not Path(command[index + 1]).exists()  # the download was removed

    folder = tmp_path / "www" / "amazon_echo"
    assert [file.name for file in folder.iterdir()] == [NAME]
    device, ssml = mock_client.speak.await_args.args
    assert device.serial == ECHO
    assert ssml == f'<audio src="https://ha.example.com/local/amazon_echo/{NAME}"/>'
    attributes = hass.states.get("media_player.kitchen_echo").attributes
    assert attributes["last_message"] == ssml
    assert attributes["last_message_timestamp"] is not None

    # the same sound again is not transcoded twice
    with patch(
        f"{AUDIO}.media_source.async_resolve_media", AsyncMock(return_value=resolved)
    ):
        await _play(hass, TTS, announce=True)
    assert ffmpeg.call_count == 1
    assert mock_client.speak.await_count == 2


async def test_url_with_the_public_url_option(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    session: MagicMock,
    ffmpeg: AsyncMock,
) -> None:
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_PUBLIC_URL: "https://public.example.com/"}
    )
    await _play(
        hass,
        "https://example.com/bell.wav",
        announce=True,
        media_content_type="audio",
    )
    assert session.get.call_args.args[0] == "https://example.com/bell.wav"
    assert mock_client.speak.await_args.args[1] == (
        f'<audio src="https://public.example.com/local/amazon_echo/{NAME}"/>'
    )


async def test_local_media_is_read_from_disk(
    hass: HomeAssistant,
    mock_client: MagicMock,
    session: MagicMock,
    ffmpeg: AsyncMock,
    tmp_path: Path,
) -> None:
    source = tmp_path / "chime.flac"
    source.write_bytes(SOUND)
    resolved = PlayMedia(url="/media/local/chime.flac", mime_type="a", path=source)
    with patch(
        f"{AUDIO}.media_source.async_resolve_media", AsyncMock(return_value=resolved)
    ):
        await _play(hass, "media-source://media_source/local/chime.flac", announce=True)
    session.get.assert_not_called()
    assert NAME in mock_client.speak.await_args.args[1]


async def test_old_files_are_removed_and_a_new_folder_is_served(
    hass: HomeAssistant,
    session: MagicMock,
    ffmpeg: AsyncMock,
    tmp_path: Path,
) -> None:
    # Home Assistant only serves /local when www exists at startup: the first
    # time, the folder is published by the integration itself.
    hass.config.components.add("http")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await _play(hass, "https://example.com/a.mp3", announce=True)
    (served,) = hass.http.async_register_static_paths.await_args.args[0]
    folder = tmp_path / "www" / "amazon_echo"
    assert (served.url_path, served.path) == ("/local/amazon_echo", str(folder))

    old, fresh = folder / "old.mp3", folder / NAME
    old.write_bytes(b"x")
    two_days_ago = time.time() - 2 * 24 * 60 * 60
    os.utime(old, (two_days_ago, two_days_ago))
    os.utime(fresh, (two_days_ago + 24 * 60 * 60 + 600, two_days_ago))
    await _play(hass, "https://example.com/a.mp3", announce=True)
    assert [file.name for file in folder.iterdir()] == [NAME]
    assert fresh.stat().st_mtime > time.time() - 60  # kept for another day
    assert hass.http.async_register_static_paths.await_count == 1


async def test_announce_is_required(hass: HomeAssistant, ffmpeg: AsyncMock) -> None:
    for media_id in (TTS, "https://example.com/song.mp3", "/local/song.mp3"):
        with pytest.raises(ServiceValidationError) as err:
            await _play(hass, media_id)
        assert err.value.translation_key == "announce_required"
    ffmpeg.assert_not_called()


async def test_needs_an_https_address(
    hass: HomeAssistant, mock_client: MagicMock, ffmpeg: AsyncMock
) -> None:
    for external in ("http://ha.example.com", None):
        hass.config.external_url = external
        with pytest.raises(HomeAssistantError) as err:
            await _play(hass, "https://example.com/a.mp3", announce=True)
        assert err.value.translation_key == "no_public_url"
        assert err.value.translation_domain == "amazon_echo"
    ffmpeg.assert_not_called()
    mock_client.speak.assert_not_awaited()


@pytest.mark.parametrize("failure", [ImportError("no haffmpeg"), ValueError("not set")])
async def test_ffmpeg_not_set_up(
    hass: HomeAssistant, session: MagicMock, failure: Exception
) -> None:
    component = MagicMock()
    component.get_ffmpeg_manager.side_effect = failure
    with (
        patch.dict(sys.modules, {"homeassistant.components.ffmpeg": component}),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _play(hass, "https://example.com/a.mp3", announce=True)
    assert err.value.translation_key == "ffmpeg_unavailable"
    session.get.assert_not_called()


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (FakeResponse(error=aiohttp.ClientError("refused")), "refused"),
        (FakeResponse(error=TimeoutError()), "TimeoutError()"),
        (FakeResponse(b"x" * (50 * 1024 * 1024 + 1)), "file too large"),
    ],
)
async def test_download_failures(
    hass: HomeAssistant,
    mock_client: MagicMock,
    session: MagicMock,
    ffmpeg: AsyncMock,
    response: FakeResponse,
    reason: str,
) -> None:
    session.get.return_value = response
    with pytest.raises(HomeAssistantError) as err:
        await _play(hass, "https://example.com/a.mp3", announce=True)
    assert err.value.translation_key == "audio_download_failed"
    assert err.value.translation_placeholders == {"error": reason}
    ffmpeg.assert_not_called()
    mock_client.speak.assert_not_awaited()


async def test_transcode_failures(
    hass: HomeAssistant,
    mock_client: MagicMock,
    session: MagicMock,
    ffmpeg: AsyncMock,
    tmp_path: Path,
) -> None:
    process = ffmpeg.process
    process.returncode = 1
    process.communicate.return_value = (b"", b"Invalid data found\n")
    with pytest.raises(HomeAssistantError) as err:
        await _play(hass, "https://example.com/a.mp3", announce=True)
    assert err.value.translation_key == "transcode_failed"
    assert err.value.translation_placeholders == {"error": "Invalid data found"}

    async def hang() -> tuple[bytes, bytes]:
        await asyncio.sleep(3600)
        return b"", b""

    process.communicate.side_effect = hang
    with (
        patch(f"{AUDIO}.TRANSCODE_TIMEOUT", 0),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _play(hass, "https://example.com/a.mp3", announce=True)
    assert err.value.translation_placeholders == {"error": "timed out"}
    process.kill.assert_called_once()
    # nothing half-written is left behind, nothing was spoken
    assert list((tmp_path / "www" / "amazon_echo").iterdir()) == []
    mock_client.speak.assert_not_awaited()
