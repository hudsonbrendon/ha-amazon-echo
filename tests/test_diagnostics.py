"""Diagnostics: useful, and free of anything that identifies the account."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import ExtendedJSONEncoder
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    APP,
    BUDS,
    CUSTOMER_ID,
    ECHO,
    ECHO_HOST,
    ECHO_MAC,
    FIRE_TV,
    GROUP,
    SHOW,
    TITLE,
    FakePush,
    setup_integration,
)

SECRETS = (
    "fake-refresh-token",
    "fake-cookie",
    "user@example.com",
    CUSTOMER_ID,
    TITLE,
    ECHO,
    SHOW,
    FIRE_TV,
    BUDS,
    GROUP,
    APP,
    ECHO_MAC,
    "aa:bb:cc:00:00:02",
    ECHO_HOST,
    "11:22:33:44:55:66",
    "ACCOUNTECHO",
    "endpoint-echo",
    "fake-device-id",
    "fake-spotify-user",
    "FakeWiFi",
)


async def test_diagnostics_are_redacted(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_push.on_state(True)
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    dump = json.dumps(diagnostics, cls=ExtendedJSONEncoder)
    for secret in SECRETS:
        assert secret not in dump, secret

    assert diagnostics["push_connected"] is True
    assert diagnostics["entry"]["data"]["credentials"] == "**REDACTED**"
    data = diagnostics["data"]
    # Still useful: names, models, capabilities and values, keyed by an alias.
    echo = data["devices"]["device_0"]
    assert echo["name"] == "Kitchen Echo" and echo["model"] == "Echo Dot"
    assert echo["serial"] == "**REDACTED**" and echo["mac"] == "**REDACTED**"
    assert "AUDIO_PLAYER" in echo["capabilities"]
    assert data["dnd"] == {"device_0": False, "device_1": True, "device_2": False}
    assert data["settings"]["device_0"]["equalizer"] == {
        "bass": 1,
        "mid": 0,
        "treble": -2,
    }
    assert data["settings"]["device_1"]["timeZone"] == "America/Sao_Paulo"
    assert data["media"]["device_0"]["title"] == "Fake Song"
    assert data["reachable"] == {"device_0": True}
    assert data["routines"] == 2
    assert data["lists"] == [
        {"kind": "shopping", "items": 2},
        {"kind": "todo", "items": 0},
    ]
