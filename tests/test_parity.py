"""What Alexa Media Player and the core Alexa Devices integration have, here too."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amazon_echo import AmazonEchoAuthenticationError, Notification, VoiceRecord
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.amazon_echo.const import (
    BUS_ALARM_DISMISSED,
    BUS_LAST_CALLED,
    BUS_NOTIFICATION,
    BUS_VOICE_COMMAND,
    DOMAIN,
)

from .conftest import (
    CUSTOMER_ID,
    ECHO,
    ENTRY_ID,
    FIRE_TV,
    GROUP,
    SHOW,
    FakePush,
    build_notifications,
    setup_integration,
)

LAST_CALLED = "sensor.test_account_last_called_device"
DEFAULT_DEVICE = "select.test_account_default_device_for_routines"


async def _call(
    hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any
) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def _device_id(hass: HomeAssistant, identifier: str = ECHO) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, identifier), ENTRY_ID
    )
    assert device is not None
    return device.id


async def _action(
    hass: HomeAssistant, service: str, identifier: str | list[str] = ECHO, **data: Any
) -> None:
    device_id: str | list[str] = (
        [_device_id(hass, i) for i in identifier]
        if isinstance(identifier, list)
        else _device_id(hass, identifier)
    )
    await hass.services.async_call(
        DOMAIN, service, {"device_id": device_id, **data}, blocking=True
    )


async def _settle(hass: HomeAssistant) -> None:
    await asyncio.sleep(0.01)
    await hass.async_block_till_done(wait_background_tasks=True)


def _record(serial: str = ECHO, *, seconds: float = 5, **kwargs: Any) -> VoiceRecord:
    return VoiceRecord(
        id=f"rec-{serial}-{seconds}",
        timestamp=dt_util.utcnow() + timedelta(seconds=seconds),
        device_serial=serial,
        **kwargs,
    )


@pytest.fixture
async def loaded(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    await setup_integration(hass, mock_config_entry)
    return mock_config_entry


# ---------------------------------------------------------------------- #
# Communication preferences (core)
# ---------------------------------------------------------------------- #
async def test_communication_preferences(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    assert hass.states.get("switch.kitchen_echo_communications").state == STATE_ON
    assert hass.states.get("switch.kitchen_echo_announcements").state == STATE_OFF
    drop_in = hass.states.get("select.kitchen_echo_drop_in")
    assert drop_in.state == "home"
    assert drop_in.attributes["options"] == ["all", "home", "off"]

    # Each write is followed by a re-read of that device's preferences.
    preferences = {"communications": False, "announcements": True, "drop_in": "off"}
    mock_client.get_communication_preferences.side_effect = None
    mock_client.get_communication_preferences.return_value = preferences
    mock_client.get_communication_preferences.reset_mock()

    await _call(hass, "switch", "turn_off", "switch.kitchen_echo_communications")
    device, enabled = mock_client.set_communications.await_args.args
    assert (device.serial, enabled) == (ECHO, False)
    assert hass.states.get("switch.kitchen_echo_communications").state == STATE_OFF

    await _call(hass, "switch", "turn_on", "switch.kitchen_echo_announcements")
    assert mock_client.set_announcements.await_args.args[1] is True
    assert hass.states.get("switch.kitchen_echo_announcements").state == STATE_ON

    await _call(
        hass, "select", "select_option", "select.kitchen_echo_drop_in", option="off"
    )
    assert mock_client.set_drop_in.await_args.args[1] == "off"
    assert hass.states.get("select.kitchen_echo_drop_in").state == "off"
    assert mock_client.get_communication_preferences.await_count == 3


# ---------------------------------------------------------------------- #
# Echo Show display, sensors of the endpoint, Amazon Kids
# ---------------------------------------------------------------------- #
async def test_display_settings(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    assert hass.states.get("switch.office_show_display").state == STATE_ON
    assert hass.states.get("switch.office_show_adaptive_brightness").state == STATE_OFF
    assert hass.states.get("number.office_show_display_brightness").state == "60"

    await _call(hass, "switch", "turn_off", "switch.office_show_display")
    assert mock_client.set_setting.await_args.args[1:] == ("displayPower", "OFF")
    await _call(hass, "switch", "turn_on", "switch.office_show_adaptive_brightness")
    assert mock_client.set_setting.await_args.args[1:] == ("adaptiveBrightness", "ON")
    await _call(
        hass,
        "number",
        "set_value",
        "number.office_show_display_brightness",
        value=30,
    )
    assert mock_client.set_setting.await_args.args[1:] == ("brightness", 30)


async def test_endpoint_sensors_of_an_alexa_device(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    illuminance = hass.states.get("sensor.office_show_illuminance")
    assert illuminance.state == "120.0"
    assert illuminance.attributes["unit_of_measurement"] == "lx"
    assert illuminance.attributes["device_class"] == "illuminance"
    humidity = hass.states.get("sensor.office_show_humidity")
    assert (humidity.state, humidity.attributes["unit_of_measurement"]) == ("48.0", "%")
    motion = hass.states.get("binary_sensor.office_show_motion")
    assert (motion.state, motion.attributes["device_class"]) == (STATE_ON, "motion")
    # The time zone comes from the account preferences when there is no setting.
    assert hass.states.get("sensor.kitchen_echo_time_zone").state == "America/Sao_Paulo"


async def test_amazon_kids(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    assert hass.states.get("switch.office_show_amazon_kids").state == STATE_ON
    profile = hass.states.get("select.office_show_amazon_kids_profile")
    assert (profile.state, profile.attributes["options"]) == ("Bia", ["Ana", "Bia"])
    assert hass.states.get("switch.kitchen_echo_amazon_kids").state == STATE_OFF
    assert (
        hass.states.get("select.kitchen_echo_amazon_kids_profile").state
        == STATE_UNKNOWN
    )
    # A Fire TV cannot be put in Kids mode from here: it is not even asked.
    assert hass.states.get("switch.living_room_tv_amazon_kids") is None
    assert {c.args[0].serial for c in mock_client.get_kids_mode.await_args_list} == {
        ECHO,
        SHOW,
    }

    mock_client.get_kids_mode.side_effect = None
    mock_client.get_kids_mode.return_value = True
    # Switching on a device that has no child yet takes the first of the house.
    await _call(hass, "switch", "turn_on", "switch.kitchen_echo_amazon_kids")
    device, child = mock_client.set_kids_mode.await_args.args
    assert (device.serial, child) == (ECHO, "child-1")
    assert hass.states.get("switch.kitchen_echo_amazon_kids").state == STATE_ON
    assert hass.states.get("select.kitchen_echo_amazon_kids_profile").state == "Ana"

    await _call(
        hass,
        "select",
        "select_option",
        "select.kitchen_echo_amazon_kids_profile",
        option="Bia",
    )
    assert mock_client.set_kids_mode.await_args.args[1] == "child-2"
    assert hass.states.get("select.kitchen_echo_amazon_kids_profile").state == "Bia"

    mock_client.get_kids_mode.return_value = False
    await _call(hass, "switch", "turn_off", "switch.office_show_amazon_kids")
    assert mock_client.set_kids_mode.await_args.args[1] is None
    assert hass.states.get("switch.office_show_amazon_kids").state == STATE_OFF
    assert (
        hass.states.get("select.office_show_amazon_kids_profile").state == STATE_UNKNOWN
    )


async def test_no_amazon_kids_without_children(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_client.get_children.return_value = {}
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("switch.office_show_amazon_kids") is None
    assert hass.states.get("select.office_show_amazon_kids_profile") is None


# ---------------------------------------------------------------------- #
# Last called (Alexa Media Player)
# ---------------------------------------------------------------------- #
async def test_last_called_is_seeded_without_events(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """At startup the last interaction only tells who was called last."""
    events = async_capture_events(hass, BUS_VOICE_COMMAND)
    mock_client.get_voice_history.return_value = [
        _record(SHOW, seconds=-3600, utterance="good morning", person="Tester")
    ]
    await setup_integration(hass, mock_config_entry)
    state = hass.states.get(LAST_CALLED)
    assert state.state == "Office Show"
    assert state.attributes["utterance"] == "good morning"
    assert state.attributes["person"] == "Tester"
    kwargs = mock_client.get_voice_history.await_args.kwargs
    assert kwargs["limit"] == 1
    assert dt_util.utcnow() - kwargs["since"] > timedelta(days=6)
    assert not events
    assert hass.states.get("event.office_show_voice_command").state == STATE_UNKNOWN
    show = hass.states.get("media_player.office_show").attributes
    assert show["last_called"] is True and show["last_called_timestamp"]
    assert show["last_called_summary"] == "good morning"
    assert show["last_called_response"] is None
    echo = hass.states.get("media_player.kitchen_echo").attributes
    assert echo["last_called"] is False and echo["last_called_timestamp"] is None


async def test_last_called_follows_voice_commands(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    loaded: MockConfigEntry,
) -> None:
    assert hass.states.get(LAST_CALLED).state == STATE_UNKNOWN
    voice = async_capture_events(hass, BUS_VOICE_COMMAND)
    called = async_capture_events(hass, BUS_LAST_CALLED)

    mock_client.get_voice_history.return_value = [
        _record(
            ECHO,
            utterance="what time is it",
            response="It is noon",
            person="Tester",
            person_type="ADULT",
        )
    ]
    mock_push.emit("PUSH_ACTIVITY", ECHO)
    await _settle(hass)
    state = hass.states.get(LAST_CALLED)
    assert state.state == "Kitchen Echo"
    assert state.attributes["response"] == "It is noon"
    assert len(voice) == len(called) == 1
    assert voice[0].data == {
        "device_id": _device_id(hass),
        "serial": ECHO,
        "name": "Kitchen Echo",
        "timestamp": state.attributes["timestamp"],
        "utterance": "what time is it",
        "response": "It is noon",
        "intent": None,
        "person": "Tester",
    }
    event = hass.states.get("event.kitchen_echo_voice_command")
    assert event.attributes["person_type"] == "ADULT"

    # Same device again: a voice command, but not a new last-called device.
    mock_client.get_voice_history.return_value = [_record(ECHO, seconds=10)]
    mock_push.emit("PUSH_ACTIVITY", ECHO)
    await _settle(hass)
    assert (len(voice), len(called)) == (2, 1)

    mock_client.get_voice_history.return_value = [_record(SHOW, seconds=20)]
    mock_push.emit("PUSH_ACTIVITY", SHOW)
    await _settle(hass)
    assert hass.states.get(LAST_CALLED).state == "Office Show"
    assert (len(voice), len(called)) == (3, 2)
    assert called[-1].data["name"] == "Office Show"

    # A device that left the account is named by its serial number.
    mock_client.get_voice_history.return_value = [_record("GONE", seconds=30)]
    mock_push.emit("PUSH_ACTIVITY")
    await _settle(hass)
    assert hass.states.get(LAST_CALLED).state == "GONE"
    assert voice[-1].data["name"] is None and voice[-1].data["device_id"] is None


async def test_voice_is_polled_while_push_is_down(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    loaded: MockConfigEntry,
) -> None:
    """An imported Alexa Media Player session has no push: polling stands in."""
    coordinator = loaded.runtime_data
    mock_client.get_voice_history.return_value = [_record(ECHO, utterance="hello")]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(LAST_CALLED).state == "Kitchen Echo"
    event = hass.states.get("event.kitchen_echo_voice_command")
    assert event.attributes["utterance"] == "hello"

    mock_push.on_state(True)
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_client.get_voice_history.reset_mock()
    await coordinator.async_refresh()
    mock_client.get_voice_history.assert_not_awaited()


async def test_update_last_called_action(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    mock_client.get_voice_history.return_value = [_record(SHOW)]
    await _action(hass, "update_last_called", CUSTOMER_ID)
    assert hass.states.get(LAST_CALLED).state == "Office Show"

    mock_client.get_voice_history.side_effect = AmazonEchoAuthenticationError("gone")
    await _action(hass, "update_last_called")
    await hass.async_block_till_done()
    assert loaded.async_get_active_flows(hass, {"reauth"})


async def test_speak_on_the_last_called_device(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    entity_id = "notify.test_account_speak_on_the_last_called_device"
    with pytest.raises(ServiceValidationError, match="No device has been called"):
        await _call(hass, "notify", "send_message", entity_id, message="Hi")

    mock_client.get_voice_history.return_value = [_record(SHOW)]
    await _action(hass, "update_last_called")
    await _call(hass, "notify", "send_message", entity_id, message="On my way")
    device, text = mock_client.speak.await_args.args
    assert (device.serial, text) == (SHOW, "On my way")


# ---------------------------------------------------------------------- #
# Default device for routines (core)
# ---------------------------------------------------------------------- #
async def test_default_device_for_routines(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    state = hass.states.get(DEFAULT_DEVICE)
    assert state.state == STATE_UNKNOWN
    # everything that plays, speaker groups included; the Fire TV does not
    assert state.attributes["options"] == [
        "Everywhere",
        "Kitchen Echo",
        "Office Show",
        "Test Buds",
    ]
    await _call(hass, "button", "press", "button.test_account_good_night")
    assert mock_client.run_routine.await_args.args[1] is None

    await _call(hass, "select", "select_option", DEFAULT_DEVICE, option="Office Show")
    assert hass.states.get(DEFAULT_DEVICE).state == "Office Show"
    await _call(hass, "button", "press", "button.test_account_good_night")
    assert mock_client.run_routine.await_args.args[1].serial == SHOW


async def test_default_device_is_restored(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_restore_cache(hass, [State(DEFAULT_DEVICE, "Kitchen Echo")])
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get(DEFAULT_DEVICE).state == "Kitchen Echo"
    assert mock_config_entry.runtime_data.default_device == ECHO


# ---------------------------------------------------------------------- #
# Media player (Alexa Media Player)
# ---------------------------------------------------------------------- #
async def test_media_player_extras(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    loaded: MockConfigEntry,
) -> None:
    entity_id = "media_player.kitchen_echo"
    attrs = hass.states.get(entity_id).attributes
    assert attrs["bluetooth_list"] == ["Soundbar", "Phone"]
    assert attrs["connected_bluetooth"] == "Phone"
    assert attrs["locale"] == "pt-BR"
    assert attrs["previous_volume"] is None

    await _call(hass, "media_player", "turn_off", entity_id)
    mock_client.stop.assert_awaited_once()
    assert hass.states.get(entity_id).state == "idle"
    await _call(hass, "media_player", "turn_on", entity_id)
    assert mock_client.media_command.await_args.args[1] == "play"
    assert hass.states.get(entity_id).state == "playing"

    await _call(
        hass,
        "media_player",
        "play_media",
        entity_id,
        media_content_type="sequence",
        media_content_id="Alexa.Weather.Play",
    )
    device, kind, payload = mock_client.send_sequence.await_args.args
    assert (device.serial, kind, payload) == (ECHO, "Alexa.Weather.Play", {})
    await _call(
        hass,
        "media_player",
        "play_media",
        entity_id,
        media_content_type="sequence",
        media_content_id="Alexa.CannedTts.Speak",
        extra={"cannedTtsStringId": "alexa.cannedtts.speak.curfew"},
    )
    assert mock_client.send_sequence.await_args.args[2] == {
        "cannedTtsStringId": "alexa.cannedtts.speak.curfew"
    }
    await _call(
        hass,
        "media_player",
        "play_media",
        "media_player.office_show",
        media_content_type="image",
        media_content_id="https://example.com/photo.jpg",
    )
    device, url = mock_client.set_background_image.await_args.args
    assert (device.serial, url) == (SHOW, "https://example.com/photo.jpg")


async def test_now_playing_push_without_a_device(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    loaded: MockConfigEntry,
) -> None:
    """Amazon's "now playing" events name no device: what plays is re-read."""
    mock_client.get_media.reset_mock()
    mock_push.emit("NotifyNowPlayingUpdated", update={"nowPlayingData": {}})
    mock_push.emit("NotifyMediaSessionsUpdated", SHOW)
    await _settle(hass)
    assert {c.args[0].serial for c in mock_client.get_media.await_args_list} == {
        ECHO,  # the only device playing
        SHOW,  # named by the second event,
        GROUP,  # and the group it belongs to
    }


async def test_restore_volume(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    loaded: MockConfigEntry,
) -> None:
    with pytest.raises(ServiceValidationError, match="no earlier volume"):
        await _action(hass, "restore_volume")

    mock_push.emit("PUSH_VOLUME_CHANGE", ECHO, volumeSetting=80, isMuted=False)
    mock_push.emit("PUSH_VOLUME_CHANGE", ECHO, volumeSetting=80, isMuted=False)
    entity_id = "media_player.kitchen_echo"
    assert hass.states.get(entity_id).attributes["previous_volume"] == 40
    await _action(hass, "restore_volume")
    device, volume = mock_client.set_volume.await_args.args
    assert (device.serial, volume) == (ECHO, 40)
    attrs = hass.states.get(entity_id).attributes
    assert (attrs["volume_level"], attrs["previous_volume"]) == (0.4, 80)


# ---------------------------------------------------------------------- #
# Actions
# ---------------------------------------------------------------------- #
async def test_send_info_skill(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    await _action(hass, "send_info_skill", skill="weather")
    device, skill = mock_client.info_skill.await_args.args
    assert (device.serial, skill) == (ECHO, "weather")
    with pytest.raises(Exception, match="skill"):
        await _action(hass, "send_info_skill", skill="Alexa.Weather.Play")
    with pytest.raises(ServiceValidationError, match="needs a device"):
        await _action(hass, "send_info_skill", CUSTOMER_ID, skill="joke")


async def test_app_notifications(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    await _action(
        hass, "send_mobile_push", CUSTOMER_ID, message="Washer done", title="Laundry"
    )
    assert mock_client.send_mobile_push.await_args.args == ("Washer done",)
    assert mock_client.send_mobile_push.await_args.kwargs == {
        "title": "Laundry",
        "device": None,
    }
    await _action(hass, "send_mobile_push", message="Hi")
    kwargs = mock_client.send_mobile_push.await_args.kwargs
    assert (kwargs["title"], kwargs["device"].serial) == (None, ECHO)

    await _action(hass, "send_drop_in_notification", message="At the door")
    assert mock_client.send_drop_in_notification.await_args.args == ("At the door",)
    assert mock_client.send_drop_in_notification.await_args.kwargs == {"title": None}


async def test_send_announcement_and_repeat(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="not sent a message"):
        await _action(hass, "repeat_last_message")

    await _action(
        hass,
        "send_announcement",
        [ECHO, SHOW],
        message="Dinner",
        title="Kitchen",
        method="show",
    )
    targets, text = mock_client.announce.await_args.args
    assert ([d.serial for d in targets], text) == ([ECHO, SHOW], "Dinner")
    assert mock_client.announce.await_args.kwargs == {
        "title": "Kitchen",
        "method": "show",
    }
    mock_client.announce.assert_awaited_once()  # one announcement for both
    with pytest.raises(ServiceValidationError, match="needs a device"):
        await _action(hass, "send_announcement", [ECHO, CUSTOMER_ID], message="Hi")

    # Each device repeats what it was last told.
    await _action(hass, "repeat_last_message", SHOW)
    targets, text = mock_client.announce.await_args.args
    assert ([d.serial for d in targets], text) == ([SHOW], "Dinner")
    assert mock_client.announce.await_args.kwargs["title"] == "Kitchen"

    await _call(
        hass, "notify", "send_message", "notify.kitchen_echo_speak", message="Hello"
    )
    echo = hass.states.get("media_player.kitchen_echo").attributes
    assert (echo["last_message"], echo["last_message_type"]) == ("Hello", "speak")
    mock_client.speak.reset_mock()
    await _action(hass, "repeat_last_message")
    device, text = mock_client.speak.await_args.args
    assert (device.serial, text) == (ECHO, "Hello")


async def test_alarm_switching_actions(
    hass: HomeAssistant, mock_client: MagicMock, loaded: MockConfigEntry
) -> None:
    mock_client.get_notifications.reset_mock()
    for action in ("enable_alarm", "disable_alarm", "skip_next_alarm"):
        await _action(hass, action, CUSTOMER_ID, notification_id="alarm-off")
        assert getattr(mock_client, action).await_args.args[0].id == "alarm-off"
    assert mock_client.get_notifications.await_count == 3  # re-read after each
    with pytest.raises(ServiceValidationError, match="no alarm"):
        await _action(hass, "disable_alarm", notification_id="nope")
    # The library refuses what is not an alarm; the user is told why.
    mock_client.enable_alarm.side_effect = ValueError("The alarm has no time")
    with pytest.raises(ServiceValidationError, match="no time"):
        await _action(hass, "enable_alarm", notification_id="alarm-off-untimed-1")


# ---------------------------------------------------------------------- #
# Events on the bus (Alexa Media Player)
# ---------------------------------------------------------------------- #
async def test_event_when_a_notification_is_due(
    hass: HomeAssistant,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    loaded: MockConfigEntry,
) -> None:
    events = async_capture_events(hass, BUS_NOTIFICATION)
    # The timer (10 minutes) comes first, then the alarm (1 hour).
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["timer-1"]
    assert events[0].data["kind"] == "timer"
    assert events[0].data["name"] == "Kitchen Echo"
    assert events[0].data["device_id"] == _device_id(hass)
    assert events[0].data["label"] == "Pasta"

    freezer.tick(timedelta(minutes=50))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["timer-1", "alarm-soon"]

    # Unloading cancels what is still scheduled (the 8 hour alarm).
    await hass.config_entries.async_unload(loaded.entry_id)
    freezer.tick(timedelta(hours=8))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(events) == 2


async def test_event_when_an_alarm_is_dismissed(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    def alarms(*versions: tuple[str, str, Any]) -> list[Notification]:
        return [
            Notification(
                id=alarm_id,
                kind="alarm",
                status=status,
                device_serial=ECHO,
                device_type="TYPEECHO",
                raw={"version": version},
            )
            for alarm_id, status, version in versions
        ]

    mock_client.get_notifications.return_value = alarms(
        ("ringing", "ON", "3"),
        ("edited", "ON", "3"),
        ("snoozed", "SNOOZED", "7"),
        ("off", "OFF", "1"),
        ("odd", "ON", None),
    )
    await setup_integration(hass, mock_config_entry)
    events = async_capture_events(hass, BUS_ALARM_DISMISSED)
    coordinator = mock_config_entry.runtime_data

    mock_client.get_notifications.return_value = alarms(
        ("ringing", "OFF", "4"),  # dismissed: the version goes up by one
        ("edited", "ON", "5"),  # edited in the app: by two or more
        ("snoozed", "ON", "8"),  # a repeating alarm stays on once dismissed
        ("off", "ON", "2"),  # switched on, it was not ringing
        ("odd", "OFF", None),
        ("new", "ON", "1"),
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["ringing", "snoozed"]
    assert events[0].data["status"] == "OFF"
    assert events[0].data["name"] == "Kitchen Echo"

    # Nothing changed: nothing is fired again.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 2


async def test_notifications_fixture_is_what_the_due_test_expects() -> None:
    kinds = {n.id: n.kind for n in build_notifications() if n.is_active}
    assert kinds == {"alarm-late": "alarm", "alarm-soon": "alarm", "timer-1": "timer"}
    assert (GROUP, FIRE_TV) == ("GROUP000000001", "FIRETV00000001")
