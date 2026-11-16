"""Every platform: states, what gets created for which device, and writes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amazon_echo import (
    AmazonEchoAuthenticationError,
    AmazonEchoError,
    AmazonEchoNotSupportedError,
    Routine,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    BUDS,
    CUSTOMER_ID,
    ECHO,
    ECHO_HOST,
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


async def _call(
    hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any
) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


# ---------------------------------------------------------------------- #
# What exists
# ---------------------------------------------------------------------- #
async def test_entities_follow_what_each_device_reports(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    by_device: dict[str, set[str]] = {}
    for entry in registry.entities.values():
        owner, _, key = entry.unique_id.partition("_")
        by_device.setdefault(owner, set()).add(f"{entry.domain}.{key}")
        assert entry.translation_key or entry.domain == "media_player"
        assert entry.has_entity_name and entry.disabled_by is None

    assert by_device[ECHO] == {
        "media_player.media_player",
        "notify.speak",
        "notify.announce",
        "event.voice",
        "button.reboot",
        "switch.do_not_disturb",
        "switch.ascending_alarm",
        "switch.wake_word_sound",
        "switch.end_of_request_sound",
        "switch.communications",
        "switch.announcements",
        "switch.amazon_kids",
        "number.bass",
        "number.mid",
        "number.treble",
        "number.alarm_volume",
        "select.wake_word",
        "select.alarm_sound",
        "select.aux_direction",
        "select.drop_in",
        "select.amazon_kids_profile",
        "sensor.next_alarm",
        "sensor.next_timer",
        "sensor.next_reminder",
        "sensor.temperature",
        "sensor.wifi_ssid",
        "sensor.ip_address",
        "sensor.bluetooth_device",
        "sensor.spotify_user",
        "sensor.time_zone",
        "binary_sensor.online",
        "binary_sensor.local_reachable",
        "binary_sensor.aux_plugged",
    }
    # Per-device setting keys only exist on the Echo Show.
    assert by_device[SHOW] >= {
        "switch.adaptive_listening",
        "switch.captions",
        "switch.gestures",
        "switch.night_mode",
        "switch.smart_motion",
        "switch.visual_gesture",
        "switch.tap_gestures",
        "number.speaking_rate",
        "select.time_format",
        "sensor.time_zone",
        "sensor.wake_word_sensitivity",
        # Echo Show display settings.
        "switch.display_power",
        "switch.adaptive_brightness",
        "number.display_brightness",
        # Sensors the Show reports through its GraphQL endpoint.
        "sensor.illuminance",
        "sensor.humidity",
        "binary_sensor.motion",
        "switch.amazon_kids",
        "select.amazon_kids_profile",
    }
    assert not by_device[SHOW] & {
        "number.bass",
        "sensor.temperature",
        "sensor.battery",
        "sensor.pm25",
        "select.drop_in",
        "switch.communications",
    }
    assert by_device[FIRE_TV] == {
        "media_player.media_player",
        "notify.speak",
        "notify.announce",
        "event.voice",
        "switch.do_not_disturb",
        "switch.ambient_mode",
        "sensor.remote_battery",
        "binary_sensor.online",
    }
    assert by_device[BUDS] >= {"sensor.battery", "binary_sensor.charging"}
    # Speaker group: a player and an announce target, nothing else.
    assert by_device["GROUP000000001"] == {
        "media_player.media_player",
        "notify.announce",
    }
    # No Guard on this account: no alarm panel. No smart-home devices either.
    assert by_device[CUSTOMER_ID] == {
        "binary_sensor.push_connected",
        "sensor.last_called",
        "select.default_device",
        "notify.speak_last_called",
        "switch.whisper_mode",
        "switch.adaptive_volume",
        "button.routine_routine-1",
        "todo.list_list-shop",
        "todo.list_list-todo",
        "todo.list_list-custom",
    }


async def test_states(hass: HomeAssistant) -> None:
    expected = {
        "switch.kitchen_echo_do_not_disturb": STATE_OFF,
        "switch.office_show_do_not_disturb": STATE_ON,
        "switch.kitchen_echo_ascending_alarm": STATE_ON,
        "switch.kitchen_echo_start_of_request_sound": STATE_ON,
        "switch.kitchen_echo_end_of_request_sound": STATE_OFF,
        "switch.living_room_tv_ambient_mode": STATE_ON,
        "switch.office_show_adaptive_listening": STATE_OFF,
        "switch.office_show_captions": STATE_ON,
        "switch.office_show_gestures": STATE_ON,
        "switch.office_show_night_mode": STATE_ON,
        "switch.office_show_smart_motion": STATE_OFF,
        "switch.office_show_visual_gesture": STATE_OFF,
        "switch.office_show_tap_gestures": STATE_OFF,
        "switch.test_account_whisper_mode": STATE_OFF,
        "switch.test_account_adaptive_volume": STATE_ON,
        "number.kitchen_echo_bass": "1",
        "number.kitchen_echo_midrange": "0",
        "number.kitchen_echo_treble": "-2",
        "number.kitchen_echo_alarm_volume": "60",
        "number.office_show_speaking_rate": "1.0",
        "select.kitchen_echo_wake_word": "ALEXA",
        "select.kitchen_echo_alarm_sound": "Simple",
        "select.kitchen_echo_aux_direction": "input",
        "select.office_show_time_format": "24_hours",
        "sensor.kitchen_echo_temperature": "24.5",
        "sensor.kitchen_echo_wi_fi_network": "FakeWiFi",
        "sensor.kitchen_echo_ip_address": ECHO_HOST,
        "sensor.kitchen_echo_bluetooth_device": "Phone",
        "sensor.kitchen_echo_spotify_user": "fake-spotify-user",
        "sensor.test_buds_battery": "80",
        "sensor.living_room_tv_remote_battery": "55",
        "sensor.office_show_time_zone": "America/Sao_Paulo",
        "sensor.office_show_wake_word_sensitivity": "0",
        "sensor.office_show_next_alarm": "unknown",
        "binary_sensor.kitchen_echo_online": STATE_ON,
        "binary_sensor.living_room_tv_online": STATE_OFF,
        "binary_sensor.kitchen_echo_reachable_on_the_local_network": STATE_ON,
        "binary_sensor.kitchen_echo_aux_cable_plugged_in": STATE_ON,
        "binary_sensor.test_buds_charging": STATE_OFF,
        "media_player.kitchen_echo": "playing",
        "media_player.office_show": "idle",
        "media_player.living_room_tv": "off",
        "todo.test_account_shopping_list": "1",
        "todo.test_account_to_do_list": "0",
        "todo.test_account_camping": "0",  # custom lists keep their own name
    }
    assert {entity_id: _state(hass, entity_id) for entity_id in expected} == expected


async def test_next_notification_sensors(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    soon = next(
        n for n in mock_client.get_notifications.return_value if n.id == "alarm-soon"
    )
    state = hass.states.get("sensor.kitchen_echo_next_alarm")
    # The soonest *active* alarm; the switched-off one that is sooner is skipped.
    assert state.state == soon.when.isoformat(timespec="seconds")
    assert [item["id"] for item in state.attributes["items"]] == [
        "alarm-off",
        "alarm-soon",
        "alarm-late",
        "alarm-off-untimed-1",
        "alarm-off-untimed-2",
    ]
    assert state.attributes["items"][-1]["when"] is None
    assert state.attributes["items"][1]["label"] == "Soon"
    timer = hass.states.get("sensor.kitchen_echo_next_timer")
    assert [item["id"] for item in timer.attributes["items"]] == ["timer-1"]
    assert _state(hass, "sensor.kitchen_echo_next_reminder") == "unknown"


# ---------------------------------------------------------------------- #
# Writes
# ---------------------------------------------------------------------- #
async def test_switches(hass: HomeAssistant, mock_client: MagicMock) -> None:
    mock_client.get_dnd.return_value = {ECHO: True}
    await _call(hass, "switch", "turn_on", "switch.kitchen_echo_do_not_disturb")
    device, enabled = mock_client.set_dnd.await_args.args
    assert (device.serial, enabled) == (ECHO, True)
    assert _state(hass, "switch.kitchen_echo_do_not_disturb") == STATE_ON

    await _call(hass, "switch", "turn_off", "switch.kitchen_echo_ascending_alarm")
    assert mock_client.set_ascending_alarm.await_args.args[1] is False

    # Earcons are written together: the other one keeps its value.
    await _call(hass, "switch", "turn_on", "switch.kitchen_echo_end_of_request_sound")
    assert mock_client.set_earcons.await_args.kwargs == {
        "wake_word": True,
        "end_of_speech": True,
    }

    await _call(hass, "switch", "turn_off", "switch.living_room_tv_ambient_mode")
    call = mock_client.call_feature.await_args
    assert call.args == ("endpoint-firetv", "toggle", "turnOff")
    assert call.kwargs == {"instance": "FTV.AmbientMode"}

    await _call(hass, "switch", "turn_on", "switch.test_account_whisper_mode")
    mock_client.set_whisper_mode.assert_awaited_once_with(True)
    await _call(hass, "switch", "turn_off", "switch.test_account_adaptive_volume")
    mock_client.set_adaptive_volume.assert_awaited_once_with(False)


@pytest.mark.parametrize(
    ("entity", "service", "key", "value"),
    [
        ("adaptive_listening", "turn_on", "adaptiveListening", "ENABLED"),
        ("captions", "turn_off", "alexaCaptions", "DISABLED"),
        ("gestures", "turn_off", "alexaGestures", False),
        ("smart_motion", "turn_on", "smartMotion", "ON"),
        ("visual_gesture", "turn_on", "visualGesture", "ENABLED"),
        # Object settings: only the toggled member changes.
        (
            "night_mode",
            "turn_off",
            "deviceNightMode",
            {"nightModeEnablement": "DISABLED", "nightModeType": "AUTOMATIC"},
        ),
        (
            "tap_gestures",
            "turn_on",
            "tapGestures",
            {"enablement": "ENABLED", "gestureActionsMap": []},
        ),
    ],
)
async def test_setting_switches(
    hass: HomeAssistant,
    mock_client: MagicMock,
    entity: str,
    service: str,
    key: str,
    value: Any,
) -> None:
    mock_client.get_setting.reset_mock()
    await _call(hass, "switch", service, f"switch.office_show_{entity}")
    device, written_key, written = mock_client.set_setting.await_args.args
    assert (device.serial, written_key, written) == (SHOW, key, value)
    # Only the written key is read back, not the whole slow tier.
    assert [c.args[1] for c in mock_client.get_setting.await_args_list] == [key]


async def test_numbers(hass: HomeAssistant, mock_client: MagicMock) -> None:
    await _call(hass, "number", "set_value", "number.kitchen_echo_treble", value=4)
    assert mock_client.set_equalizer.await_args.kwargs == {
        "bass": 1,
        "mid": 0,
        "treble": 4,
    }
    await _call(
        hass, "number", "set_value", "number.kitchen_echo_alarm_volume", value=35
    )
    assert mock_client.set_alarm_volume.await_args.args[1] == 35
    await _call(
        hass, "number", "set_value", "number.office_show_speaking_rate", value=1.25
    )
    assert mock_client.set_setting.await_args.args[1:] == ("alexaSpeakingRate", 1.25)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", "number.kitchen_echo_bass", value=7)


async def test_selects(hass: HomeAssistant, mock_client: MagicMock) -> None:
    state = hass.states.get("select.kitchen_echo_wake_word")
    assert state.attributes["options"] == ["ALEXA", "ECHO", "COMPUTER"]
    await _call(
        hass, "select", "select_option", "select.kitchen_echo_wake_word", option="ECHO"
    )
    assert mock_client.set_wake_word.await_args.args[1] == "ECHO"

    await _call(
        hass,
        "select",
        "select_option",
        "select.kitchen_echo_alarm_sound",
        option="Nimble",
    )
    assert mock_client.set_default_alarm_sound.await_args.args[1] == "sound-2"

    await _call(
        hass,
        "select",
        "select_option",
        "select.kitchen_echo_aux_direction",
        option="output",
    )
    assert mock_client.set_aux_direction.await_args.args[1:] == ("aux0", "OUTPUT")

    await _call(
        hass,
        "select",
        "select_option",
        "select.office_show_time_format",
        option="12_hours",
    )
    assert mock_client.set_setting.await_args.args[1:] == ("timeFormat", "12_HOURS")


async def test_buttons(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    await _call(hass, "button", "press", "button.kitchen_echo_reboot")
    assert mock_client.reboot.await_args.args[0].serial == ECHO

    assert hass.states.get("button.test_account_disabled_one") is None
    await _call(hass, "button", "press", "button.test_account_good_night")
    assert mock_client.run_routine.await_args.args[0].id == "routine-1"

    # A new routine gets its button without a reload; a deleted one goes away.
    coordinator = mock_config_entry.runtime_data
    coordinator.data.routines = [Routine(id="routine-3", name="Movie time")]
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert _state(hass, "button.test_account_movie_time") == "unknown"
    assert _state(hass, "button.test_account_good_night") == STATE_UNAVAILABLE


async def test_notify(hass: HomeAssistant, mock_client: MagicMock) -> None:
    await _call(
        hass, "notify", "send_message", "notify.kitchen_echo_speak", message="Hello"
    )
    device, text = mock_client.speak.await_args.args
    assert (device.serial, text) == (ECHO, "Hello")

    await _call(
        hass,
        "notify",
        "send_message",
        "notify.kitchen_echo_announce",
        message="Dinner",
        title="Kitchen",
    )
    targets, text = mock_client.announce.await_args.args
    assert [d.serial for d in targets] == [ECHO] and text == "Dinner"
    assert mock_client.announce.await_args.kwargs == {
        "title": "Kitchen",
        "method": "all",
    }

    # A group announces on its members.
    await _call(
        hass, "notify", "send_message", "notify.everywhere_announce", message="Hi"
    )
    assert [d.serial for d in mock_client.announce.await_args.args[0]] == [ECHO, SHOW]


async def test_todo(hass: HomeAssistant, mock_client: MagicMock) -> None:
    entity_id = "todo.test_account_shopping_list"
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
        return_response=True,
    )
    assert [(i["summary"], i["status"]) for i in response[entity_id]["items"]] == [
        ("Milk", "needs_action"),
        ("Bread", "completed"),
    ]

    await _call(hass, "todo", "add_item", entity_id, item="Eggs")
    mock_client.add_list_item.assert_awaited_once_with("list-shop", "Eggs")

    await _call(hass, "todo", "update_item", entity_id, item="Milk", status="completed")
    args, kwargs = mock_client.update_list_item.await_args
    assert (args[0], args[1].id) == ("list-shop", "item-1")
    assert kwargs == {"name": "Milk", "completed": True}

    mock_client.get_lists.reset_mock()
    await _call(hass, "todo", "remove_item", entity_id, item=["Milk", "Bread"])
    assert [c.args[1].id for c in mock_client.delete_list_item.await_args_list] == [
        "item-1",
        "item-2",
    ]
    mock_client.get_lists.assert_awaited_once()  # one re-read for the batch


async def test_media_player_state(hass: HomeAssistant) -> None:
    state = hass.states.get("media_player.kitchen_echo")
    attrs = state.attributes
    assert attrs["volume_level"] == 0.4 and attrs["is_volume_muted"] is False
    assert (
        attrs["media_title"] == "Fake Song" and attrs["media_artist"] == "Fake Artist"
    )
    assert attrs["media_album_name"] == "Fake Album"
    assert attrs["media_duration"] == 200 and attrs["media_position"] == 30
    assert attrs["entity_picture"] == "https://example.com/cover.jpg"
    assert attrs["app_name"] == "Spotify"
    assert attrs["shuffle"] is False and attrs["repeat"] == "all"
    assert attrs["source_list"] == ["Soundbar", "Phone", "Local speaker"]
    assert attrs["source"] == "Phone"
    assert attrs["groups"] == ["Everywhere"] and attrs["members"] == []
    assert attrs["device_class"] == "speaker"

    group = hass.states.get("media_player.everywhere").attributes
    assert group["members"] == ["Kitchen Echo", "Office Show"]
    # No Bluetooth and nothing seekable on the Show: no source list, no seek.
    show = hass.states.get("media_player.office_show").attributes
    assert "source_list" not in show
    from homeassistant.components.media_player import MediaPlayerEntityFeature as F

    assert attrs["supported_features"] & F.SEEK
    assert attrs["supported_features"] & F.SELECT_SOURCE
    assert not show["supported_features"] & (F.SEEK | F.SELECT_SOURCE)


async def test_media_player_commands(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entity_id = "media_player.kitchen_echo"

    async def command(service: str, **data: Any) -> tuple[Any, ...]:
        mock_client.media_command.reset_mock()
        await _call(hass, "media_player", service, entity_id, **data)
        call = mock_client.media_command.await_args
        assert call.args[0].serial == ECHO
        return (call.args[1], call.kwargs)

    assert await command("media_pause") == ("pause", {})
    assert _state(hass, entity_id) == "paused"
    assert await command("media_play") == ("play", {})
    assert _state(hass, entity_id) == "playing"
    assert await command("media_next_track") == ("next", {})
    assert await command("media_previous_track") == ("previous", {})
    assert await command("shuffle_set", shuffle=True) == ("shuffle", {"enabled": True})
    assert await command("repeat_set", repeat="off") == ("repeat", {"enabled": False})
    assert await command("repeat_set", repeat="one") == ("repeat", {"enabled": True})
    # Alexa has no absolute seek: forward or rewind relative to the position (30 s).
    assert await command("media_seek", seek_position=90) == ("forward", {})
    assert await command("media_seek", seek_position=5) == ("rewind", {})

    await _call(hass, "media_player", "media_stop", entity_id)
    assert mock_client.stop.await_args.args[0].serial == ECHO
    assert _state(hass, entity_id) == "idle"

    await _call(hass, "media_player", "volume_set", entity_id, volume_level=0.55)
    assert mock_client.set_volume.await_args.args[1] == 55
    await _call(hass, "media_player", "volume_up", entity_id)
    assert mock_client.set_volume.await_args.args[1] == 65

    # Mute remembers the volume and restores it.
    await _call(hass, "media_player", "volume_mute", entity_id, is_volume_muted=True)
    assert mock_client.set_volume.await_args.args[1] == 0
    assert hass.states.get(entity_id).attributes["is_volume_muted"] is True
    await _call(hass, "media_player", "volume_mute", entity_id, is_volume_muted=False)
    assert mock_client.set_volume.await_args.args[1] == 65

    await _call(hass, "media_player", "select_source", entity_id, source="Soundbar")
    assert mock_client.bluetooth_connect.await_args.args[1] == "11:22:33:44:55:66"
    await _call(
        hass, "media_player", "select_source", entity_id, source="Local speaker"
    )
    mock_client.bluetooth_disconnect.assert_awaited_once()
    with pytest.raises(ServiceValidationError):
        await _call(hass, "media_player", "select_source", entity_id, source="Nope")


@pytest.mark.parametrize(
    ("media_type", "media_id", "method", "args"),
    [
        ("music", "SPOTIFY:lo-fi beats", "play_music", ("SPOTIFY", "lo-fi beats")),
        ("music", "jazz", "play_music", ("DEFAULT", "jazz")),
        # An unknown prefix is part of the phrase, not a provider.
        (
            "music",
            "AC/DC: Back in Black",
            "play_music",
            ("DEFAULT", "AC/DC: Back in Black"),
        ),
        (
            "sound",
            "amzn_sfx_doorbell_chime_01",
            "play_sound",
            ("amzn_sfx_doorbell_chime_01",),
        ),
        ("skill", "amzn1.ask.skill.fake", "launch_skill", ("amzn1.ask.skill.fake",)),
        ("text_command", "turn on the lights", "text_command", ("turn on the lights",)),
        ("tts", "Hello there", "speak", ("Hello there",)),
    ],
)
async def test_play_media(
    hass: HomeAssistant,
    mock_client: MagicMock,
    media_type: str,
    media_id: str,
    method: str,
    args: tuple[str, ...],
) -> None:
    await _call(
        hass,
        "media_player",
        "play_media",
        "media_player.kitchen_echo",
        media_content_type=media_type,
        media_content_id=media_id,
    )
    call = getattr(mock_client, method).await_args
    assert call.args[0].serial == ECHO and call.args[1:] == args


async def test_play_media_routine_and_errors(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    async def play(media_type: str, media_id: str) -> None:
        await _call(
            hass,
            "media_player",
            "play_media",
            "media_player.kitchen_echo",
            media_content_type=media_type,
            media_content_id=media_id,
        )

    await play("routine", "good NIGHT")
    routine, device = mock_client.run_routine.await_args.args
    assert (routine.id, device.serial) == ("routine-1", ECHO)
    with pytest.raises(ServiceValidationError) as err:
        await play("routine", "does not exist")
    assert err.value.translation_key == "routine_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await play("video", "x")
    assert err.value.translation_key == "unsupported_media_type"


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (AmazonEchoNotSupportedError("nope"), "not_supported"),
        (AmazonEchoError("500"), "communication_error"),
        (AmazonEchoAuthenticationError("expired"), "invalid_auth"),
    ],
)
async def test_write_errors_are_translated(
    hass: HomeAssistant, mock_client: MagicMock, error: Exception, key: str
) -> None:
    mock_client.set_dnd.side_effect = error
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "switch", "turn_on", "switch.kitchen_echo_do_not_disturb")
    assert err.value.translation_key == key
    assert err.value.translation_domain == "amazon_echo"
    await hass.async_block_till_done()
    reauth = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == "reauth"
    ]
    assert len(reauth) == (1 if key == "invalid_auth" else 0)
