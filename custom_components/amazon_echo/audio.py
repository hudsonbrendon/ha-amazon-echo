"""Audio files as announcements.

Alexa cannot be handed a stream, but its speech markup has an ``<audio>`` tag
that plays a short MP3 from an HTTPS address. An audio file (a URL, local
media, a Home Assistant text-to-speech result) is transcoded into that format,
published under ``/local/amazon_echo`` and spoken.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
import time

import aiohttp
from homeassistant.components import media_source
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CONF_PUBLIC_URL, DOMAIN

# What Alexa plays in <audio>: MP3, 48 kbit/s, 24 kHz. The same arguments
# Alexa Media Player gives ffmpeg (its media_player.py, async_play_tts_cloud_say).
FFMPEG_ARGS = (
    "-ac",
    "2",
    "-codec:a",
    "libmp3lame",
    "-b:a",
    "48k",
    "-ar",
    "24000",
    "-write_xing",
    "0",
)
MAX_AGE_SECONDS = 24 * 60 * 60
# ponytail: Alexa stops an <audio> clip at 240 s; anything this large is not one.
MAX_AUDIO_BYTES = 50 * 1024 * 1024
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)
TRANSCODE_TIMEOUT = 60


def is_audio_source(media_id: str) -> bool:
    """Whether a media id names a file: a media source, a URL or a local path."""
    return media_source.is_media_source_id(media_id) or media_id.startswith(
        ("http://", "https://", "/")
    )


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def _public_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the HTTPS address Alexa reaches Home Assistant at."""
    base: str = entry.options.get(CONF_PUBLIC_URL) or ""
    if not base:
        try:
            base = get_url(hass, allow_internal=False, prefer_external=True)
        except NoURLAvailableError:
            base = ""
    if not base.startswith("https://"):
        raise _error("no_public_url")
    return base.rstrip("/")


def _ffmpeg_binary(hass: HomeAssistant) -> str:
    """Return Home Assistant's ffmpeg, or fail when it is not set up."""
    try:
        # Imported here: the component needs a package Home Assistant only
        # installs once ffmpeg is set up.
        from homeassistant.components.ffmpeg import get_ffmpeg_manager

        return get_ffmpeg_manager(hass).binary
    except (ImportError, ValueError) as err:
        raise _error("ffmpeg_unavailable") from err


async def _read(hass: HomeAssistant, media_id: str, entity_id: str) -> bytes:
    """Return the bytes of a media source, a URL or a path of Home Assistant."""
    if media_source.is_media_source_id(media_id):
        media = await media_source.async_resolve_media(hass, media_id, entity_id)
        if media.path is not None:
            return await hass.async_add_executor_job(media.path.read_bytes)
        media_id = media.url
    url = async_process_play_media_url(hass, media_id)
    data = bytearray()
    try:
        async with async_get_clientsession(hass).get(
            url, timeout=DOWNLOAD_TIMEOUT
        ) as response:
            response.raise_for_status()
            async for chunk in response.content.iter_chunked(65536):
                data += chunk
                if len(data) > MAX_AUDIO_BYTES:
                    raise _error("audio_download_failed", error="file too large")
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        raise _error("audio_download_failed", error=str(err) or repr(err)) from err
    return bytes(data)


def _prepare(directory: Path) -> bool:
    """Create the folder and drop day-old files; True when ``www`` was missing."""
    missing = not directory.parent.is_dir()
    directory.mkdir(parents=True, exist_ok=True)
    limit = time.time() - MAX_AGE_SECONDS
    for file in directory.iterdir():
        if file.stat().st_mtime < limit:
            file.unlink(missing_ok=True)
    return missing


def _write_temp(data: bytes) -> str:
    # A file, not a pipe: ffmpeg must seek in some containers (M4A, WAV).
    with tempfile.NamedTemporaryFile(delete=False, prefix=f"{DOMAIN}_") as file:
        file.write(data)
        return file.name


async def _transcode(hass: HomeAssistant, binary: str, data: bytes, out: Path) -> None:
    """Write ``data`` to ``out`` in the format Alexa plays."""
    source = await hass.async_add_executor_job(_write_temp, data)
    part = out.with_suffix(".part")
    process = await asyncio.create_subprocess_exec(
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        *FFMPEG_ARGS,
        "-f",
        "mp3",
        str(part),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(TRANSCODE_TIMEOUT):
            _, stderr = await process.communicate()
        if process.returncode:
            raise _error(
                "transcode_failed",
                error=stderr.decode(errors="replace").strip()[-300:],
            )
        await hass.async_add_executor_job(os.replace, part, out)
    except TimeoutError as err:
        process.kill()
        raise _error("transcode_failed", error="timed out") from err
    finally:
        await hass.async_add_executor_job(_discard, Path(source), part)


def _discard(*files: Path) -> None:
    for file in files:
        file.unlink(missing_ok=True)


async def async_audio_ssml(
    hass: HomeAssistant, entry: ConfigEntry, media_id: str, entity_id: str
) -> str:
    """Publish an audio file for Alexa and return the markup that plays it."""
    base = _public_url(hass, entry)
    binary = _ffmpeg_binary(hass)
    data = await _read(hass, media_id, entity_id)
    directory = Path(hass.config.path("www", DOMAIN))
    if (
        await hass.async_add_executor_job(_prepare, directory)
        and "http" in hass.config.components
    ):
        # Home Assistant serves /local only when www existed as it started.
        await hass.http.async_register_static_paths(
            [StaticPathConfig(f"/local/{DOMAIN}", str(directory), False)]
        )
    out = directory / f"{hashlib.sha256(data).hexdigest()[:32]}.mp3"
    if await hass.async_add_executor_job(out.is_file):
        # the same sound again: keep it for another day
        await hass.async_add_executor_job(os.utime, out)
    else:
        await _transcode(hass, binary, data, out)
    return f'<audio src="{base}/local/{DOMAIN}/{out.name}"/>'
