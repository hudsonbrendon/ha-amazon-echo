"""Fixtures: a fully mocked library fed with invented devices (no real data)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from amazon_echo import (
    Account,
    AmazonEchoNotSupportedError,
    AuthorizeRequest,
    AuxPort,
    BluetoothDevice,
    Credentials,
    Device,
    EchoList,
    ListItem,
    LocalInfo,
    MediaState,
    Notification,
    PushEvent,
    Routine,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo.const import (
    CONF_CREDENTIALS,
    CONF_HOSTS,
    DOMAIN,
)

CUSTOMER_ID = "A1CUSTOMER000"
TITLE = "Test Account"
ENTRY_ID = "01J0AMAZONECHOENTRY0000001"
ECHO = "ECHO0000000001"
SHOW = "SHOW0000000001"
FIRE_TV = "FIRETV00000001"
BUDS = "BUDS0000000001"
GROUP = "GROUP000000001"
APP = "APP00000000001"
ECHO_MAC = "aa:bb:cc:00:00:01"
ECHO_HOST = "192.0.2.10"
AUTHORIZE_URL = "https://www.amazon.com/ap/signin?fake=1"
REDIRECT_URL = (
    "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=FAKECODE"
)

AUDIO = {
    "AUDIO_PLAYER",
    "VOLUME_SETTING",
    "MICROPHONE",
    "TIMERS_AND_ALARMS",
    "REMINDERS",
    "ALEXA_DEVICE_REBOOT",
}
SHOW_SETTINGS: dict[str, Any] = {
    "adaptiveListening": "DISABLED",
    "alexaCaptions": "ENABLED",
    "alexaGestures": True,
    "alexaSpeakingRate": 1.0,
    "deviceNightMode": {
        "nightModeEnablement": "ENABLED",
        "nightModeType": "AUTOMATIC",
    },
    "smartMotion": "OFF",
    "tapGestures": {"enablement": "DISABLED", "gestureActionsMap": []},
    "timeFormat": "24_HOURS",
    "timeZone": "America/Sao_Paulo",
    "visualGesture": "DISABLED",
    "wakeWordSensitivity": 0,
}


def credentials() -> Credentials:
    return Credentials(
        domain="amazon.com",
        refresh_token="fake-refresh-token",
        cookies={"session-id": "fake-cookie"},
        customer_id=CUSTOMER_ID,
        email="user@example.com",
    )


def build_devices() -> list[Device]:
    return [
        Device(
            serial=ECHO,
            device_type="TYPEECHO",
            name="Kitchen Echo",
            family="ECHO",
            model="Echo Dot",
            software_version="1.2.3",
            account_id="ACCOUNTECHO",
            online=True,
            capabilities=frozenset(AUDIO),
            parent_clusters=(GROUP,),
            mac=ECHO_MAC,
            endpoint_id="endpoint-echo",
        ),
        Device(
            serial=SHOW,
            device_type="TYPESHOW",
            name="Office Show",
            family="KNIGHT",
            model="Echo Show 5",
            software_version="4.5.6",
            account_id="ACCOUNTSHOW",
            online=True,
            capabilities=frozenset(AUDIO),
            parent_clusters=(GROUP,),
            endpoint_id="endpoint-show",
        ),
        Device(
            serial=FIRE_TV,
            device_type="TYPEFIRETV",
            name="Living Room TV",
            family="FIRE_TV",
            model="Fire TV Stick",
            online=False,
            capabilities=frozenset({"VOLUME_SETTING", "MICROPHONE"}),
            endpoint_id="endpoint-firetv",
        ),
        Device(
            serial=BUDS,
            device_type="TYPEBUDS",
            name="Test Buds",
            family="VOX_ACCESSORY",
            online=True,
            capabilities=frozenset({"AUDIO_PLAYER", "VOLUME_SETTING"}),
            battery_level=80,
            charging=False,
        ),
        Device(
            serial=GROUP,
            device_type="TYPEGROUP",
            name="Everywhere",
            family="WHA",
            online=True,
            capabilities=frozenset({"AUDIO_PLAYER", "VOLUME_SETTING"}),
            cluster_members=(ECHO, SHOW),
        ),
        Device(
            serial=APP,
            device_type="TYPEAPP",
            name="Alexa App",
            family="VOX",
            online=True,
        ),
    ]


def build_notifications() -> list[Notification]:
    now = dt_util.utcnow()
    return [
        Notification(
            id="alarm-late",
            kind="alarm",
            status="ON",
            device_serial=ECHO,
            device_type="TYPEECHO",
            label="Late",
            when=now + timedelta(hours=8),
        ),
        Notification(
            id="alarm-soon",
            kind="alarm",
            status="ON",
            device_serial=ECHO,
            device_type="TYPEECHO",
            label="Soon",
            when=now + timedelta(hours=1),
        ),
        Notification(
            id="alarm-off",
            kind="alarm",
            status="OFF",
            device_serial=ECHO,
            device_type="TYPEECHO",
            when=now + timedelta(minutes=5),
        ),
        Notification(
            id="timer-1",
            kind="timer",
            status="ON",
            device_serial=ECHO,
            device_type="TYPEECHO",
            label="Pasta",
            when=now + timedelta(minutes=10),
            remaining=timedelta(minutes=10),
        ),
    ]


class FakePush:
    """Stands in for PushClient and lets tests emit events."""

    def __init__(self) -> None:
        self.on_event: Any = None
        self.on_state: Any = None
        self.start = AsyncMock()
        self.stop = AsyncMock()

    def __call__(self, client: Any, on_event: Any, *, on_state: Any = None) -> FakePush:
        self.on_event, self.on_state = on_event, on_state
        return self

    def emit(self, command: str, serial: str | None = None, **payload: Any) -> None:
        self.on_event(PushEvent(command=command, device_serial=serial, payload=payload))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in every test."""


@pytest.fixture(autouse=True)
def no_delays() -> Generator[None]:
    """Skip the settle delay after writes and the push debounce."""
    with (
        patch("custom_components.amazon_echo.coordinator.WRITE_SETTLE_SECONDS", 0),
        patch("custom_components.amazon_echo.coordinator.PUSH_DEBOUNCE_SECONDS", 0),
    ):
        yield


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch AmazonEchoClient in the integration and the config flow."""
    client = MagicMock()
    state: dict[str, Any] = {
        "get_account": Account(
            customer_id=CUSTOMER_ID, name=TITLE, email="user@example.com"
        ),
        "get_routines": [
            Routine(id="routine-1", name="Good night"),
            Routine(id="routine-2", name="Disabled one", enabled=False),
        ],
        "get_music_providers": {"SPOTIFY": "Spotify", "AMAZON_MUSIC": "Amazon Music"},
        "get_dnd": {ECHO: False, SHOW: True, FIRE_TV: False},
        "get_volumes": {ECHO: (40, False), SHOW: (20, False), GROUP: (30, False)},
        "get_bluetooth": {
            ECHO: [
                BluetoothDevice(address="11:22:33:44:55:66", name="Soundbar"),
                BluetoothDevice(
                    address="11:22:33:44:55:77", name="Phone", connected=True
                ),
            ]
        },
        "get_notifications": build_notifications(),
        "get_alarm_volumes": {ECHO: 60, SHOW: 50},
        "get_wake_words": {ECHO: "ALEXA", SHOW: "ECHO"},
        "get_ascending_alarms": {ECHO: True, SHOW: False},
        "get_endpoint_states": {
            ECHO: {"temperature": 24.5},
            FIRE_TV: {"remote_battery": 55, "ambient_mode": True},
        },
        "get_whisper_mode": False,
        "get_adaptive_volume": True,
        "get_lists": [
            EchoList(id="list-shop", name="Shopping", kind="shopping"),
            EchoList(id="list-todo", name="To-do", kind="todo"),
        ],
        "get_voice_history": [],
    }
    for name, value in state.items():
        setattr(client, name, AsyncMock(return_value=value))
    client.get_devices = AsyncMock(side_effect=lambda: build_devices())
    client.get_media = AsyncMock(
        side_effect=lambda device: (
            MediaState(
                state="playing",
                title="Fake Song",
                artist="Fake Artist",
                album="Fake Album",
                image_url="https://example.com/cover.jpg",
                duration=200.0,
                position=30.0,
                provider="Spotify",
                shuffle=False,
                repeat=True,
                can_next=True,
                can_previous=True,
                can_seek=True,
                volume=40,
            )
            if device.serial == ECHO
            else MediaState()
        )
    )
    client.get_list_items = AsyncMock(
        side_effect=lambda list_id: (
            [
                ListItem(id="item-1", name="Milk"),
                ListItem(id="item-2", name="Bread", completed=True),
            ]
            if list_id == "list-shop"
            else []
        )
    )

    # Per-device slow tier: the Echo and the Show answer, the rest do not.
    def per_device(values: dict[str, Any]) -> AsyncMock:
        def get(device: Device, *args: Any) -> Any:
            if device.serial not in values:
                raise AmazonEchoNotSupportedError("not supported")
            return values[device.serial]

        return AsyncMock(side_effect=get)

    client.get_wifi = per_device(
        {ECHO: ("FakeWiFi", ECHO_MAC), SHOW: ("FakeWiFi", "aa:bb:cc:00:00:02")}
    )
    client.get_equalizer = per_device({ECHO: {"bass": 1, "mid": 0, "treble": -2}})
    client.get_earcons = per_device({ECHO: {"wake_word": True, "end_of_speech": False}})
    client.get_aux = per_device(
        {ECHO: [AuxPort(id="aux0", direction="INPUT", plugged=True)], SHOW: []}
    )
    client.get_available_wake_words = per_device(
        {ECHO: ["ALEXA", "ECHO", "COMPUTER"], SHOW: ["ALEXA", "ECHO"]}
    )
    client.get_alarm_sounds = per_device(
        {ECHO: {"sound-1": "Simple", "sound-2": "Nimble"}}
    )
    client.get_default_alarm_sound = per_device({ECHO: "sound-1"})

    def get_setting(device: Device, key: str) -> Any:
        if device.serial != SHOW or key not in SHOW_SETTINGS:
            raise AmazonEchoNotSupportedError(key)
        return SHOW_SETTINGS[key]

    client.get_setting = AsyncMock(side_effect=get_setting)

    for name in (
        "close",
        "set_whisper_mode",
        "set_adaptive_volume",
        "set_dnd",
        "set_equalizer",
        "set_earcons",
        "set_setting",
        "set_alarm_volume",
        "set_wake_word",
        "set_ascending_alarm",
        "set_default_alarm_sound",
        "set_aux_direction",
        "bluetooth_connect",
        "bluetooth_disconnect",
        "reboot",
        "media_command",
        "set_volume",
        "stop",
        "speak",
        "announce",
        "text_command",
        "play_sound",
        "play_music",
        "launch_skill",
        "run_routine",
        "delete_notification",
        "add_list_item",
        "update_list_item",
        "delete_list_item",
        "call_feature",
    ):
        setattr(client, name, AsyncMock(return_value=None))
    created = build_notifications()[0]
    for name in ("create_alarm", "create_timer", "create_reminder"):
        setattr(client, name, AsyncMock(return_value=created))

    def factory(creds: Credentials, **kwargs: Any) -> MagicMock:
        client.credentials = creds
        client.on_credentials_update = kwargs.get("on_credentials_update")
        return client

    with (
        patch(
            "custom_components.amazon_echo.AmazonEchoClient", side_effect=factory
        ) as cls,
        patch("custom_components.amazon_echo.config_flow.AmazonEchoClient", new=cls),
    ):
        yield client


@pytest.fixture
def mock_push() -> Generator[FakePush]:
    """Patch PushClient with a fake that tests can drive."""
    push = FakePush()
    with patch("custom_components.amazon_echo.coordinator.PushClient", new=push):
        yield push


@pytest.fixture
def mock_local() -> Generator[dict[str, AsyncMock]]:
    """Patch the LAN probes (coordinator and config flow)."""
    info = LocalInfo(
        host=ECHO_HOST,
        name="Kitchen Echo",
        model="Echo_Dot",
        brand="Amazon",
        device_id="fake-device-id",
        spotify_user="fake-spotify-user",
    )
    probe = AsyncMock(return_value=info)
    reachable = AsyncMock(return_value=True)
    with (
        patch("custom_components.amazon_echo.coordinator.probe_local", new=probe),
        patch("custom_components.amazon_echo.coordinator.is_reachable", new=reachable),
        patch("custom_components.amazon_echo.config_flow.probe_local", new=probe),
    ):
        yield {"probe_local": probe, "is_reachable": reachable}


@pytest.fixture
def mock_register() -> Generator[AsyncMock]:
    """Patch the browser sign-in helpers of the config flow."""
    register = AsyncMock(return_value=credentials())
    with (
        patch(
            "custom_components.amazon_echo.config_flow.build_authorize_url",
            return_value=AuthorizeRequest(
                url=AUTHORIZE_URL, serial="FAKESERIAL", code_verifier="fake-verifier"
            ),
        ),
        patch(
            "custom_components.amazon_echo.config_flow.register_device", new=register
        ),
    ):
        yield register


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Config entry of the fake account; the Echo already has a known host."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id=CUSTOMER_ID,
        data={
            CONF_CREDENTIALS: credentials().to_dict(),
            CONF_HOSTS: {ECHO_MAC: ECHO_HOST},
        },
        options={},
        entry_id=ENTRY_ID,
    )


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and load it."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
