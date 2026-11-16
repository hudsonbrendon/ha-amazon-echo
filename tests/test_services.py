"""Integration actions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amazon_echo import AmazonEchoError, VoiceRecord
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo.const import DOMAIN

from .conftest import (
    CUSTOMER_ID,
    ECHO,
    ENTRY_ID,
    FIRE_TV,
    SHOW,
    FakePush,
    setup_integration,
)


@pytest.fixture(autouse=True)
async def loaded(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)


def _device_id(hass: HomeAssistant, identifier: str = ECHO) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, identifier), ENTRY_ID
    )
    assert device is not None
    return device.id


async def _call(
    hass: HomeAssistant, service: str, identifier: str = ECHO, **data: Any
) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        service,
        {"device_id": _device_id(hass, identifier), **data},
        blocking=True,
        return_response=service.startswith(("get_", "create_")),
    )


async def test_every_action_is_registered(hass: HomeAssistant) -> None:
    assert set(hass.services.async_services()[DOMAIN]) == {
        "send_text_command",
        "play_sound",
        "run_routine",
        "launch_skill",
        "create_alarm",
        "create_timer",
        "create_reminder",
        "delete_notification",
        "get_notifications",
        "get_voice_history",
        "bluetooth_connect",
        "bluetooth_disconnect",
        "call_feature",
    }


async def test_voice_and_sound_actions(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await _call(hass, "send_text_command", text="good morning")
    device, text = mock_client.text_command.await_args.args
    assert (device.serial, text) == (ECHO, "good morning")

    await _call(hass, "play_sound", sound="amzn_sfx_doorbell_chime_01")
    assert mock_client.play_sound.await_args.args[1] == "amzn_sfx_doorbell_chime_01"

    await _call(hass, "launch_skill", skill_id="amzn1.ask.skill.fake")
    assert mock_client.launch_skill.await_args.args[1] == "amzn1.ask.skill.fake"


async def test_run_routine(hass: HomeAssistant, mock_client: MagicMock) -> None:
    await _call(hass, "run_routine", routine="Good night")
    routine, device = mock_client.run_routine.await_args.args
    assert (routine.id, device.serial) == ("routine-1", ECHO)
    # On the account device the routine runs on its own device.
    await _call(hass, "run_routine", CUSTOMER_ID, routine="routine-1")
    assert mock_client.run_routine.await_args.args[1] is None
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "run_routine", routine="Nope")
    assert err.value.translation_key == "routine_not_found"


async def test_create_and_delete_notifications(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    response = await _call(
        hass,
        "create_alarm",
        time="2030-01-02 07:00:00",
        recurrence="DAILY",
    )
    device, when = mock_client.create_alarm.await_args.args
    assert device.serial == ECHO
    # A naive time is local time.
    assert when == dt_util.as_local(dt_util.parse_datetime("2030-01-02 07:00:00"))
    assert when.tzinfo is not None
    assert mock_client.create_alarm.await_args.kwargs == {"recurrence": "DAILY"}
    assert response["id"] == "alarm-late" and response["kind"] == "alarm"

    # A recurrence the library does not understand is a validation error.
    mock_client.create_alarm.side_effect = ValueError("Unsupported recurrence: 'X'")
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "create_alarm", time="2030-01-02 07:00:00", recurrence="X")
    assert err.value.translation_key == "invalid_value"

    response = await _call(hass, "create_timer", duration="00:10:00", label="Pasta")
    assert mock_client.create_timer.await_args.args[1] == timedelta(minutes=10)
    assert mock_client.create_timer.await_args.kwargs == {"label": "Pasta"}

    await _call(hass, "create_reminder", time="2030-01-02 18:00:00", label="Trash")
    assert mock_client.create_reminder.await_args.args[2] == "Trash"

    mock_client.get_notifications.reset_mock()
    await _call(hass, "delete_notification", notification_id="timer-1")
    assert mock_client.delete_notification.await_args.args[0].id == "timer-1"
    mock_client.get_notifications.assert_awaited_once()  # re-read after the write
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "delete_notification", notification_id="missing")
    assert err.value.translation_key == "notification_not_found"


async def test_get_notifications(hass: HomeAssistant) -> None:
    response = await _call(hass, "get_notifications")
    assert {n["id"] for n in response["notifications"]} == {
        "alarm-late",
        "alarm-soon",
        "alarm-off",
        "alarm-off-untimed-1",
        "alarm-off-untimed-2",
        "timer-1",
    }
    timer = next(n for n in response["notifications"] if n["id"] == "timer-1")
    assert timer["remaining"] == 600 and timer["label"] == "Pasta"
    assert (await _call(hass, "get_notifications", SHOW))["notifications"] == []
    # The account device returns everything.
    everything = await _call(hass, "get_notifications", CUSTOMER_ID)
    assert len(everything["notifications"]) == 6


async def test_get_voice_history(hass: HomeAssistant, mock_client: MagicMock) -> None:
    now = dt_util.utcnow()
    mock_client.get_voice_history.return_value = [
        VoiceRecord(id="r1", timestamp=now, device_serial=ECHO, utterance="hello"),
        VoiceRecord(id="r2", timestamp=now, device_serial=SHOW, utterance="bye"),
    ]
    response = await _call(hass, "get_voice_history", limit=2)
    assert mock_client.get_voice_history.await_args.kwargs == {"limit": 2}
    assert [r["utterance"] for r in response["records"]] == ["hello"]
    assert response["records"][0]["timestamp"] == now.isoformat()
    response = await _call(hass, "get_voice_history", CUSTOMER_ID)
    assert [r["id"] for r in response["records"]] == ["r1", "r2"]


async def test_bluetooth(hass: HomeAssistant, mock_client: MagicMock) -> None:
    await _call(hass, "bluetooth_connect", address="soundbar")  # by name
    assert mock_client.bluetooth_connect.await_args.args[1] == "11:22:33:44:55:66"
    await _call(hass, "bluetooth_connect", address="11:22:33:44:55:77")
    assert mock_client.bluetooth_connect.await_args.args[1] == "11:22:33:44:55:77"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "bluetooth_connect", address="AA:AA:AA:AA:AA:AA")
    assert err.value.translation_key == "bluetooth_not_paired"
    await _call(hass, "bluetooth_disconnect")
    assert mock_client.bluetooth_disconnect.await_args.args[0].serial == ECHO


async def test_call_feature(hass: HomeAssistant, mock_client: MagicMock) -> None:
    await _call(hass, "call_feature", FIRE_TV, feature="power", operation="turnOn")
    assert mock_client.call_feature.await_args.args == (
        "endpoint-firetv",
        "power",
        "turnOn",
    )
    # Third-party endpoint through the account device.
    await _call(
        hass,
        "call_feature",
        CUSTOMER_ID,
        endpoint_id="endpoint-lamp",
        feature="brightness",
        operation="setBrightness",
        instance="main",
        payload={"brightness": 50},
    )
    call = mock_client.call_feature.await_args
    assert call.args == ("endpoint-lamp", "brightness", "setBrightness")
    assert call.kwargs == {"instance": "main", "payload": {"brightness": 50}}
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "call_feature", CUSTOMER_ID, feature="x", operation="y")
    assert err.value.translation_key == "no_endpoint"


async def test_device_resolution_errors(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "play_sound", {"device_id": "nope", "sound": "x"}, blocking=True
        )
    assert err.value.translation_key == "device_not_found"

    # Actions on a device do not accept the account.
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "play_sound", CUSTOMER_ID, sound="x")
    assert err.value.translation_key == "device_required"

    # A device of another integration.
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    foreign = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "play_sound", {"device_id": foreign.id, "sound": "x"}, blocking=True
        )
    assert err.value.translation_key == "device_not_found"

    mock_client.play_sound.side_effect = AmazonEchoError("500")
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "play_sound", sound="x")
    assert err.value.translation_key == "communication_error"

    device_id = _device_id(hass)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "play_sound", {"device_id": device_id, "sound": "x"}, blocking=True
        )
    assert err.value.translation_key == "entry_not_loaded"
