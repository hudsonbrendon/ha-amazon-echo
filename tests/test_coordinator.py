"""Coordinator tiers: fast poll, slow settings, push events and LAN probing."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from amazon_echo import (
    AmazonEchoAuthenticationError,
    AmazonEchoConnectionError,
    AmazonEchoError,
    AmazonEchoResponseError,
    BluetoothDevice,
    ListItem,
    MediaState,
    VoiceRecord,
)
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.amazon_echo.const import (
    CONF_CREDENTIALS,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_PUSH,
    CONF_HOSTS,
    DOMAIN,
    SLOW_INTERVAL,
)

from .conftest import (
    ECHO,
    ECHO_HOST,
    ECHO_MAC,
    FIRE_TV,
    GROUP,
    SHOW,
    FakePush,
    build_devices,
    setup_integration,
)


async def _settle(hass: HomeAssistant) -> None:
    """Let the (zero-delay) push debounce timer fire, then drain the tasks."""
    await asyncio.sleep(0.01)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_first_refresh_runs_every_tier(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert set(data.devices) == {ECHO, SHOW, FIRE_TV, "BUDS0000000001", GROUP}
    assert data.dnd[SHOW] is True and data.volumes[ECHO] == (40, False)
    assert data.media[ECHO].title == "Fake Song"
    # Media is only read for online audio devices and groups.
    assert FIRE_TV not in data.media and GROUP in data.media
    assert data.settings[ECHO]["equalizer"] == {"bass": 1, "mid": 0, "treble": -2}
    assert data.settings[SHOW]["timeZone"] == "America/Sao_Paulo"
    assert data.alarm_volumes[ECHO] == 60 and data.whisper_mode is False
    assert [r.name for r in data.routines] == ["Good night", "Disabled one"]
    assert [item.name for item in data.lists["list-shop"][1]] == ["Milk", "Bread"]
    assert data.hosts == {ECHO: ECHO_HOST} and data.reachable == {ECHO: True}
    assert data.local[ECHO].spotify_user == "fake-spotify-user"
    # Groups have no per-device settings.
    assert GROUP not in data.settings


async def test_slow_tier_tolerates_failures_and_remembers_unsupported(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """One broken endpoint never fails the update; unsupported keys are not retried."""
    mock_client.get_alarm_sounds.side_effect = AmazonEchoResponseError(500, "boom")
    mock_client.get_whisper_mode.side_effect = AmazonEchoConnectionError("flaky")
    await setup_integration(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert "alarm_sounds" not in data.settings[ECHO] and data.whisper_mode is None
    assert hass.states.get("select.kitchen_echo_alarm_sound") is None
    assert hass.states.get("switch.test_account_whisper_mode") is None
    assert hass.states.get("number.kitchen_echo_bass").state == "1"

    # The Fire TV answered "not supported" to everything, the Echo to the
    # Show-only setting keys: none of that is asked again.
    for mock in (mock_client.get_setting, mock_client.get_equalizer):
        mock.reset_mock()
    mock_client.get_alarm_sounds.side_effect = None
    mock_client.get_alarm_sounds.return_value = {"sound-1": "Simple"}
    mock_client.get_whisper_mode.side_effect = None
    freezer.tick(SLOW_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert {c.args[0].serial for c in mock_client.get_setting.await_args_list} == {SHOW}
    assert {c.args[0].serial for c in mock_client.get_equalizer.await_args_list} == {
        ECHO
    }
    # What failed before is back, and its entities show up without a reload.
    assert hass.states.get("select.kitchen_echo_alarm_sound").state == "Simple"
    assert hass.states.get("switch.test_account_whisper_mode").state == STATE_OFF


async def test_cloud_down_local_up(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Cloud entities go unavailable, LAN entities keep working and updating."""
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    local_reachable = "binary_sensor.kitchen_echo_reachable_on_the_local_network"
    assert hass.states.get(local_reachable).state == STATE_ON

    mock_client.get_devices.side_effect = AmazonEchoConnectionError("cloud down")
    await coordinator.async_refresh()
    await _settle(hass)
    assert not coordinator.last_update_success
    for cloud in (
        "switch.kitchen_echo_do_not_disturb",
        "media_player.kitchen_echo",
        "binary_sensor.kitchen_echo_online",
        "switch.test_account_adaptive_volume",
    ):
        assert hass.states.get(cloud).state == STATE_UNAVAILABLE
    assert hass.states.get(local_reachable).state == STATE_ON
    assert hass.states.get("sensor.kitchen_echo_ip_address").state == ECHO_HOST
    assert (
        hass.states.get("sensor.kitchen_echo_spotify_user").state == "fake-spotify-user"
    )

    # The LAN poll keeps running without the cloud.
    mock_local["probe_local"].return_value = None
    mock_local["is_reachable"].return_value = False
    await coordinator.async_poll_local()
    assert hass.states.get(local_reachable).state == STATE_OFF
    # Port 55442 answering is enough when the Spotify endpoint does not.
    mock_local["is_reachable"].return_value = True
    await coordinator.async_poll_local()
    assert hass.states.get(local_reachable).state == STATE_ON
    mock_local["probe_local"].side_effect = OSError("network unreachable")
    await coordinator.async_poll_local()
    assert hass.states.get(local_reachable).state == STATE_OFF
    # The slow tier is not attempted while the cloud is down.
    mock_client.get_routines.reset_mock()
    await coordinator._async_poll_slow()
    mock_client.get_routines.assert_not_awaited()

    mock_client.get_devices.side_effect = lambda: build_devices()
    await coordinator.async_refresh()
    await _settle(hass)
    assert hass.states.get("switch.kitchen_echo_do_not_disturb").state == STATE_OFF


async def test_empty_device_list_does_not_wipe_the_registry(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """A glitch answer with no devices must not delete every device and entity."""
    await setup_integration(hass, mock_config_entry)
    mock_client.get_devices.side_effect = lambda: []
    await mock_config_entry.runtime_data.async_refresh()
    await _settle(hass)
    assert hass.states.get("media_player.kitchen_echo").state == STATE_UNAVAILABLE
    mock_client.get_devices.side_effect = lambda: build_devices()
    await mock_config_entry.runtime_data.async_refresh()
    await _settle(hass)
    assert hass.states.get("media_player.kitchen_echo").state == "playing"


async def test_auth_error_while_polling_starts_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_client.get_dnd.side_effect = AmazonEchoAuthenticationError("expired")
    await mock_config_entry.runtime_data.async_refresh()
    await _settle(hass)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_fast_tier_keeps_last_value_on_partial_failure(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    mock_client.get_volumes.side_effect = AmazonEchoError("graphql hiccup")
    mock_client.get_dnd.return_value = {ECHO: True, SHOW: True}
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.volumes[ECHO] == (40, False)
    assert hass.states.get("switch.kitchen_echo_do_not_disturb").state == STATE_ON


async def test_media_polled_only_for_playing_devices_with_push(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    mock_push.on_state(True)
    mock_client.get_media.reset_mock()
    await coordinator.async_refresh()
    assert [c.args[0].serial for c in mock_client.get_media.await_args_list] == [ECHO]

    # Push down: poll faster and read every player again.
    mock_push.on_state(False)
    await _settle(hass)
    assert coordinator.update_interval == timedelta(seconds=60)
    mock_client.get_media.reset_mock()
    await coordinator.async_refresh()
    assert len(mock_client.get_media.await_args_list) == 4

    mock_client.get_devices.reset_mock()
    mock_push.on_state(True)
    await _settle(hass)
    assert coordinator.update_interval == timedelta(seconds=300)
    mock_client.get_devices.assert_awaited()  # resync after the reconnect


async def test_push_events_update_the_snapshot(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    mock_client.get_devices.reset_mock()

    mock_push.emit("PUSH_VOLUME_CHANGE", ECHO, volumeSetting=65, isMuted=False)
    assert (
        hass.states.get("media_player.kitchen_echo").attributes["volume_level"] == 0.65
    )

    mock_push.emit("PUSH_DND_STATE_CHANGE", ECHO, enabled=True)
    assert hass.states.get("switch.kitchen_echo_do_not_disturb").state == STATE_ON

    mock_push.emit(
        "PUSH_DOPPLER_CONNECTION_CHANGE", ECHO, dopplerConnectionState="OFFLINE"
    )
    assert hass.states.get("binary_sensor.kitchen_echo_online").state == STATE_OFF
    assert hass.states.get("media_player.kitchen_echo").state == "off"
    mock_push.emit(
        "PUSH_DOPPLER_CONNECTION_CHANGE", ECHO, dopplerConnectionState="ONLINE"
    )

    mock_push.emit("PUSH_EQUALIZER_STATE_CHANGE", ECHO, bass=3, midrange=2, treble=1)
    assert hass.states.get("number.kitchen_echo_midrange").state == "2"

    # Player state applies at once, the metadata is re-read (device + its group).
    mock_client.get_media.reset_mock()
    mock_client.get_media.side_effect = None
    mock_client.get_media.return_value = MediaState(state="paused", title="Other")
    mock_push.emit("PUSH_AUDIO_PLAYER_STATE", ECHO, audioPlayerState="INTERRUPTED")
    assert hass.states.get("media_player.kitchen_echo").state == "paused"
    await _settle(hass)
    assert {c.args[0].serial for c in mock_client.get_media.await_args_list} == {
        ECHO,
        GROUP,
    }
    assert hass.states.get("media_player.kitchen_echo").attributes["media_title"] == (
        "Other"
    )

    mock_client.get_notifications.return_value = []
    mock_push.emit("PUSH_NOTIFICATION_CHANGE", ECHO, eventType="UPDATE")
    mock_push.emit("PUSH_NOTIFICATION_CHANGE", ECHO, eventType="UPDATE")
    mock_client.get_notifications.reset_mock()
    await _settle(hass)
    mock_client.get_notifications.assert_awaited_once()  # debounced
    assert hass.states.get("sensor.kitchen_echo_next_alarm").state == "unknown"

    mock_client.get_bluetooth.return_value = {
        ECHO: [BluetoothDevice(address="11:22:33:44:55:66", name="Soundbar")]
    }
    mock_push.emit("PUSH_BLUETOOTH_STATE_CHANGE", ECHO)
    await _settle(hass)
    assert hass.states.get("sensor.kitchen_echo_bluetooth_device").state == "unknown"

    mock_client.get_list_items.side_effect = None
    mock_client.get_list_items.return_value = [ListItem(id="item-9", name="Eggs")]
    mock_push.emit("PUSH_LIST_ITEM_CHANGE")
    await _settle(hass)
    assert hass.states.get("todo.test_account_shopping_list").state == "1"

    # Unknown or state-less commands are only logged.
    mock_push.emit("PUSH_SOMETHING_NEW", ECHO, anything=1)
    mock_push.emit("PUSH_MICROPHONE_STATE", ECHO)
    mock_push.emit("PUSH_VOLUME_CHANGE", "UNKNOWNSERIAL", volumeSetting=1)
    await _settle(hass)
    assert data.volumes[ECHO] == (65, False)
    # None of this needed a full poll.
    mock_client.get_devices.assert_not_awaited()


async def test_voice_event_from_push(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    entity_id = "event.kitchen_echo_voice_command"
    assert hass.states.get(entity_id).state == "unknown"
    now = dt_util.utcnow()
    mock_client.get_voice_history.return_value = [
        VoiceRecord(
            id="rec-new",
            timestamp=now + timedelta(seconds=5),
            device_serial=ECHO,
            utterance="what time is it",
            response="It is noon",
            intent="WhatTimeIntent",
            person="Tester",
        ),
        VoiceRecord(
            id="rec-old", timestamp=now - timedelta(days=1), device_serial=ECHO
        ),
    ]
    mock_push.emit("PUSH_ACTIVITY", ECHO)
    await _settle(hass)
    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "voice_command"
    assert state.attributes["utterance"] == "what time is it"
    assert state.attributes["response"] == "It is noon"
    assert state.attributes["intent"] == "WhatTimeIntent"
    assert state.attributes["person"] == "Tester"
    # Other devices did not fire, and the same record does not fire twice.
    assert hass.states.get("event.office_show_voice_command").state == "unknown"
    fired_at = state.state
    mock_push.emit("PUSH_EQUALIZER_STATE_CHANGE", ECHO, bass=0, midrange=0, treble=0)
    await _settle(hass)
    assert hass.states.get(entity_id).state == fired_at

    mock_client.get_voice_history.side_effect = AmazonEchoError("history down")
    mock_push.emit("PUSH_ACTIVITY", ECHO)
    await _settle(hass)
    assert hass.states.get(entity_id).state == fired_at


async def test_push_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    mock_client.get_notifications.side_effect = AmazonEchoAuthenticationError("no")
    mock_push.emit("PUSH_NOTIFICATION_CHANGE", ECHO)
    await _settle(hass)
    assert len(hass.config_entries.flow.async_progress()) == 1


async def test_push_start_failure_falls_back_to_polling(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_push.start.side_effect = AmazonEchoConnectionError("no http2")
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    assert coordinator.push_connected is False
    assert coordinator.update_interval == timedelta(seconds=60)


async def test_push_and_local_can_be_disabled(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data=mock_config_entry.data,
        options={CONF_ENABLE_PUSH: False, CONF_ENABLE_LOCAL: False},
    )
    await setup_integration(hass, mock_config_entry)
    mock_push.start.assert_not_awaited()
    mock_local["probe_local"].assert_not_awaited()
    assert hass.states.get("sensor.kitchen_echo_ip_address") is None
    coordinator = mock_config_entry.runtime_data
    coordinator.async_add_discovered("Office Show", "192.0.2.11")
    await _settle(hass)
    assert coordinator.data.hosts == {}
    assert mock_config_entry.data[CONF_HOSTS] == {ECHO_MAC: ECHO_HOST}


async def test_media_failure_and_slow_tier_auth_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    # A player that cannot be read keeps its last state.
    mock_client.get_media.side_effect = AmazonEchoError("player gone")
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert hass.states.get("media_player.kitchen_echo").state == "playing"

    mock_client.get_routines.side_effect = AmazonEchoAuthenticationError("expired")
    await coordinator._async_poll_slow()
    await _settle(hass)
    assert len(hass.config_entries.flow.async_progress()) == 1


async def test_no_push_on_a_session_shared_with_alexa_media(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """One push stream per registration: on a shared session, poll and say so."""
    imported = {**mock_config_entry.data[CONF_CREDENTIALS], "source": "alexa_media"}
    mock_config_entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data={**mock_config_entry.data, CONF_CREDENTIALS: imported},
    )
    alexa_media = MockConfigEntry(domain="alexa_media")
    alexa_media.add_to_hass(hass)
    issues = ir.async_get(hass)
    issue_id = f"shared_session_{mock_config_entry.entry_id}"
    push_sensor = "binary_sensor.test_account_real_time_updates"

    await setup_integration(hass, mock_config_entry)
    mock_push.start.assert_not_awaited()
    coordinator = mock_config_entry.runtime_data
    assert coordinator.push_connected is False
    assert coordinator.update_interval == timedelta(seconds=60)
    assert hass.states.get(push_sensor).state == STATE_OFF
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and not issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "shared_session"

    # A disabled Alexa Media Player no longer competes for the stream: the
    # imported session gets push and the repair goes away.
    await hass.config_entries.async_set_disabled_by(
        alexa_media.entry_id, ConfigEntryDisabler.USER
    )
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await _settle(hass)
    mock_push.start.assert_awaited_once()
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    mock_push.on_state(True)
    assert hass.states.get(push_sensor).state == STATE_ON

    # The sensor reports the stream, also while the cloud is unreachable.
    mock_client.get_devices.side_effect = AmazonEchoConnectionError("cloud down")
    mock_push.on_state(False)
    await _settle(hass)
    assert hass.states.get(push_sensor).state == STATE_OFF


async def test_own_session_gets_push_next_to_alexa_media(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """A browser sign-in has its own registration, so nothing is shared."""
    MockConfigEntry(domain="alexa_media").add_to_hass(hass)
    await setup_integration(hass, mock_config_entry)
    mock_push.start.assert_awaited_once()
    assert not ir.async_get(hass).issues


async def test_lan_browser_maps_hosts(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_browser: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A Spotify Connect announcement seen by our own browser yields the host."""
    from unittest.mock import patch

    from zeroconf import ServiceStateChange

    await setup_integration(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data
    coordinator._discovered.clear()
    handler = mock_browser.call_args.kwargs["handlers"][0]
    with patch(
        "custom_components.amazon_echo.coordinator.AsyncServiceInfo"
    ) as service_info:
        service_info.return_value.async_request = AsyncMock(return_value=True)
        service_info.return_value.parsed_addresses.return_value = ["192.0.2.55"]
        handler(None, "_spotify-connect._tcp.local.", "x", ServiceStateChange.Added)
        await _settle(hass)
    assert coordinator._discovered == {"kitchen echo": "192.0.2.55"}

    # a removal is ignored
    handler(None, "_spotify-connect._tcp.local.", "x", ServiceStateChange.Removed)
    await _settle(hass)
    assert coordinator._discovered == {"kitchen echo": "192.0.2.55"}
