"""Smart-home endpoints (opt-in), Amazon hardware without a microphone, Guard."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amazon_echo import AmazonEchoError, Device, Endpoint, Guard
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.json import ExtendedJSONEncoder
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo import async_remove_config_entry_device
from custom_components.amazon_echo.const import (
    CONF_CREDENTIALS,
    CONF_SMART_HOME,
    DOMAIN,
    PUSH_SMART_HOME,
)
from custom_components.amazon_echo.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import (
    CUSTOMER_ID,
    ECHO,
    ENTRY_ID,
    TITLE,
    FakePush,
    build_devices,
    credentials,
    setup_integration,
)

LAMP = "endpoint-lamp"
WHITE_LAMP = "endpoint-white-lamp"
PLUG = "endpoint-plug"
DOOR = "endpoint-door"
MOTION = "endpoint-motion"
LOCK = "endpoint-lock"
OLD_LOCK = "endpoint-old-lock"
SCENE = "endpoint-scene"
GLOW = "endpoint-glow"
MONITOR = "endpoint-monitor"
POWER = frozenset({"power.turnOn", "power.turnOff"})


def build_endpoints() -> list[Endpoint]:
    return [
        Endpoint(
            id=LAMP,
            name="Desk Lamp",
            category="LIGHT",
            manufacturer="Lamp Maker",
            model="LM-1",
            operations=POWER
            | {
                "brightness.setBrightness",
                "color.setColor",
                "colorTemperature.setColorTemperature",
            },
            state={
                "reachable": True,
                "power": False,
                "brightness": 40,
                "color": None,
                "color_temperature": 2700,
            },
        ),
        Endpoint(
            id=WHITE_LAMP,
            name="Hall Lamp",
            category="LIGHT",
            operations=POWER,
            state={"reachable": True, "power": True},
        ),
        Endpoint(
            id=PLUG,
            name="Coffee Plug",
            category="SMARTPLUG",
            manufacturer="Plug Maker",
            operations=POWER,
            state={"reachable": True, "power": True},
        ),
        Endpoint(
            id=DOOR,
            name="Front Door",
            category="CONTACT_SENSOR",
            state={"reachable": True, "contact": True, "battery": 71},
        ),
        Endpoint(
            id=MOTION,
            name="Hall Motion",
            category="MOTION_SENSOR",
            state={"reachable": True, "motion": False, "temperature": None},
        ),
        Endpoint(
            id=LOCK,
            name="Back Door",
            category="SMARTLOCK",
            operations=frozenset({"lock.lock", "lock.unlock"}),
            state={"reachable": True, "lock": "UNLOCKED", "battery": 90},
        ),
        Endpoint(
            id=OLD_LOCK,
            name="Garage",
            category="SMARTLOCK",
            operations=frozenset({"lock.lock"}),
            state={"reachable": False, "lock": "JAMMED"},
        ),
        # A scene has nothing to show: no entity, no device.
        Endpoint(id=SCENE, name="Good Night", category="ACTIVITY_TRIGGER"),
        Endpoint(
            id=GLOW,
            name="Kids Glow",
            category="LIGHT",
            manufacturer="Amazon",
            model="Echo Glow",
            serial="GLOW0000000001",
            device_type="A2OV3VSK41OD7X",
            operations=POWER
            | {"brightness.setBrightness", "color.setColor", "mode.setMode"},
            state={
                "reachable": True,
                "power": True,
                "brightness": 100,
                "color": {"hue": 240.0, "saturation": 1.0, "brightness": 1.0},
                "mode": "Rainbow.Mode",
                "mode_instance": "1",
                "mode_options": {"Rainbow": "Rainbow.Mode", "Campfire": "Fire.Mode"},
            },
        ),
        Endpoint(
            id=MONITOR,
            name="Air Monitor",
            category="AIR_QUALITY_MONITOR",
            manufacturer="Amazon",
            model="Air Quality Monitor",
            serial="AQM00000000001",
            device_type="AEZME1X38KDRA",
            operations=frozenset({"toggle.turnOn", "toggle.turnOff"}),
            state={
                "reachable": True,
                "temperature": 22.5,
                "humidity": 48.0,
                "voc": 2.0,
                "pm25": 7.0,
                "pm10": 9.0,
                "co": 0.0,
                "air_quality": 87.0,
                "aqm_led": True,
            },
        ),
    ]


@pytest.fixture
def smart_home_entry() -> MockConfigEntry:
    """The account with the smart-home option turned on."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id=CUSTOMER_ID,
        data={CONF_CREDENTIALS: credentials().to_dict()},
        options={CONF_SMART_HOME: True},
        entry_id=ENTRY_ID,
    )


@pytest.fixture
def endpoints(mock_client: MagicMock) -> list[Endpoint]:
    items = build_endpoints()
    mock_client.get_smart_home_endpoints.return_value = items
    return items


async def _call(
    hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any
) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def _feature_calls(mock_client: MagicMock) -> list[tuple[Any, ...]]:
    """(endpoint, feature, operation, instance, payload) of every feature call."""
    return [
        (*call.args, call.kwargs.get("instance"), call.kwargs.get("payload"))
        for call in mock_client.call_feature.await_args_list
    ]


def _entities_of(hass: HomeAssistant, endpoint_id: str) -> set[str]:
    registry = er.async_get(hass)
    return {
        f"{entry.domain}.{entry.unique_id.removeprefix(endpoint_id + '_')}"
        for entry in registry.entities.values()
        if entry.unique_id.startswith(endpoint_id + "_")
    }


# ---------------------------------------------------------------------- #
# Opt-in
# ---------------------------------------------------------------------- #
async def test_off_by_default_except_amazon_hardware(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    """Other brands' devices already live in HA: only Amazon's own are added."""
    await setup_integration(hass, mock_config_entry)
    data = mock_config_entry.runtime_data.data
    assert set(data.smart_home) == {GLOW, MONITOR}
    for endpoint_id in (LAMP, PLUG, DOOR, MOTION, LOCK, SCENE):
        assert not _entities_of(hass, endpoint_id)
    assert _entities_of(hass, GLOW) == {"light.light"}
    assert _entities_of(hass, MONITOR) == {
        "sensor.temperature",
        "sensor.humidity",
        "sensor.voc",
        "sensor.pm25",
        "sensor.pm10",
        "sensor.co",
        "sensor.air_quality",
        "switch.aqm_led",
    }
    assert hass.states.get("light.kids_glow").state == STATE_ON
    assert hass.states.get("sensor.air_monitor_pm2_5").state == "7.0"
    assert hass.states.get("sensor.air_monitor_air_quality_index").state == "87.0"


async def test_amazon_hardware_that_is_also_a_device_is_not_doubled(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    glow = next(e for e in endpoints if e.id == GLOW)
    mock_client.get_devices.side_effect = lambda: [
        *build_devices(),
        Device(serial=glow.serial, device_type="TYPEGLOW", name="Glow", family="ECHO"),
    ]
    await setup_integration(hass, mock_config_entry)
    assert set(mock_config_entry.runtime_data.data.smart_home) == {MONITOR}


async def test_entities_bridged_from_home_assistant_are_not_taken_back(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
) -> None:
    """A Matter hub publishing HA entities to Alexa must not create a loop."""
    mock_client.get_smart_home_endpoints.return_value = [
        Endpoint(
            id=f"endpoint-bridged-{maker}",
            name="Bridged Lamp",
            category="LIGHT",
            manufacturer=maker,
            operations=POWER,
            state={"power": True},
        )
        for maker in ("t0bst4r", "Riddix", "Matterbridge", "Home Assistant")
    ]
    await setup_integration(hass, smart_home_entry)
    assert smart_home_entry.runtime_data.data.smart_home == {}
    assert hass.states.get("light.bridged_lamp") is None

    # A Hue lamp is a real lamp, unless Home Assistant emulates a Hue bridge.
    hue = Endpoint(
        id="endpoint-hue",
        name="Hue Lamp",
        category="LIGHT",
        manufacturer="Royal Philips Electronics",
        operations=POWER,
        state={"power": True},
    )
    mock_client.get_smart_home_endpoints.return_value = [hue]
    coordinator = smart_home_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("light.hue_lamp").state == STATE_ON
    hass.config.components.add("emulated_hue")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data.smart_home == {}
    assert hass.states.get("light.hue_lamp") is None


async def test_every_endpoint_with_the_option_on(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    assert _entities_of(hass, LAMP) == {"light.light"}
    assert _entities_of(hass, WHITE_LAMP) == {"light.light"}
    assert _entities_of(hass, PLUG) == {"switch.power"}
    assert _entities_of(hass, DOOR) == {"binary_sensor.contact", "sensor.battery"}
    # the motion sensor has a thermometer Amazon cannot read: no entity for it
    assert _entities_of(hass, MOTION) == {"binary_sensor.motion"}
    assert _entities_of(hass, LOCK) == {"lock.lock", "sensor.battery"}
    assert not _entities_of(hass, SCENE)

    # One Home Assistant device per endpoint, hanging off the account device.
    registry = dr.async_get(hass)
    account = registry.async_get_device_by_identifier((DOMAIN, CUSTOMER_ID), ENTRY_ID)
    lamp = registry.async_get_device_by_identifier((DOMAIN, LAMP), ENTRY_ID)
    assert lamp is not None and account is not None
    assert (lamp.name, lamp.manufacturer, lamp.model) == (
        "Desk Lamp",
        "Lamp Maker",
        "LM-1",
    )
    assert lamp.via_device_id == account.id
    door = registry.async_get_device_by_identifier((DOMAIN, DOOR), ENTRY_ID)
    assert door.model == "Contact sensor"  # no model: the category stands in
    assert registry.async_get_device_by_identifier((DOMAIN, SCENE), ENTRY_ID) is None

    assert hass.states.get("switch.coffee_plug").state == STATE_ON
    assert hass.states.get("binary_sensor.front_door_contact").state == STATE_ON
    assert hass.states.get("sensor.front_door_battery").state == "71"
    assert hass.states.get("binary_sensor.hall_motion_motion").state == STATE_OFF
    # Amazon cannot reach the garage lock.
    assert hass.states.get("lock.garage").state == STATE_UNAVAILABLE


# ---------------------------------------------------------------------- #
# Lights
# ---------------------------------------------------------------------- #
async def test_light(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    state = hass.states.get("light.desk_lamp")
    assert state.state == STATE_OFF
    assert set(state.attributes["supported_color_modes"]) == {"hs", "color_temp"}
    assert (state.attributes["min_color_temp_kelvin"], 6500) == (
        2200,
        state.attributes["max_color_temp_kelvin"],
    )

    await _call(hass, "light", "turn_on", "light.desk_lamp", brightness=128)
    assert _feature_calls(mock_client) == [
        (LAMP, "power", "turnOn", None, None),
        (LAMP, "brightness", "setBrightness", None, {"brightness": 50}),
    ]
    state = hass.states.get("light.desk_lamp")
    assert state.state == STATE_ON
    assert state.attributes["brightness"] == 128
    # white: the lamp reports a colour temperature and no colour
    assert state.attributes["color_mode"] == "color_temp"
    assert state.attributes["color_temp_kelvin"] == 2700

    mock_client.call_feature.reset_mock()
    await _call(hass, "light", "turn_on", "light.desk_lamp", hs_color=(120, 50))
    assert _feature_calls(mock_client) == [
        (
            LAMP,
            "color",
            "setColor",
            None,
            {"color": {"hue": 120.0, "saturation": 0.5, "brightness": 1.0}},
        )
    ]
    state = hass.states.get("light.desk_lamp")
    assert state.attributes["color_mode"] == "hs"
    assert state.attributes["hs_color"] == (120.0, 50.0)

    mock_client.call_feature.reset_mock()
    await _call(hass, "light", "turn_on", "light.desk_lamp", color_temp_kelvin=4000)
    assert _feature_calls(mock_client) == [
        (
            LAMP,
            "colorTemperature",
            "setColorTemperature",
            None,
            {"colorTemperatureInKelvin": 4000},
        )
    ]
    state = hass.states.get("light.desk_lamp")
    assert state.attributes["color_mode"] == "color_temp"
    assert state.attributes["color_temp_kelvin"] == 4000

    mock_client.call_feature.reset_mock()
    await _call(hass, "light", "turn_off", "light.desk_lamp")
    assert _feature_calls(mock_client) == [(LAMP, "power", "turnOff", None, None)]
    assert hass.states.get("light.desk_lamp").state == STATE_OFF

    # A lamp that only switches.
    plain = hass.states.get("light.hall_lamp")
    assert plain.attributes["supported_color_modes"] == ["onoff"]
    assert plain.attributes["color_mode"] == "onoff"


async def test_echo_glow_effects(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, mock_config_entry)
    state = hass.states.get("light.kids_glow")
    assert state.attributes["supported_color_modes"] == ["hs"]
    assert state.attributes["hs_color"] == (240.0, 100.0)
    assert state.attributes["effect_list"] == ["Rainbow", "Campfire"]
    assert state.attributes["effect"] == "Rainbow"

    await _call(hass, "light", "turn_on", "light.kids_glow", effect="Campfire")
    # already on: only the light show is changed
    assert _feature_calls(mock_client) == [
        (GLOW, "mode", "setMode", "1", {"mode": "Fire.Mode"})
    ]
    assert hass.states.get("light.kids_glow").attributes["effect"] == "Campfire"


async def test_dimmable_only_lamp(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
) -> None:
    """Something that is not called a light but dims is still a light."""
    mock_client.get_smart_home_endpoints.return_value = [
        Endpoint(
            id="endpoint-dimmer",
            name="Dimmer",
            category="OTHER",
            operations=POWER | {"brightness.setBrightness"},
            state={"power": None, "brightness": None},
        )
    ]
    await setup_integration(hass, smart_home_entry)
    assert _entities_of(hass, "endpoint-dimmer") == {"light.light"}
    state = hass.states.get("light.dimmer")
    assert state.state == "unknown"  # Amazon could not read it
    assert state.attributes["supported_color_modes"] == ["brightness"]


# ---------------------------------------------------------------------- #
# Switches, locks
# ---------------------------------------------------------------------- #
async def test_switches(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    await _call(hass, "switch", "turn_off", "switch.coffee_plug")
    assert hass.states.get("switch.coffee_plug").state == STATE_OFF
    await _call(hass, "switch", "turn_on", "switch.coffee_plug")
    assert hass.states.get("switch.coffee_plug").state == STATE_ON
    # The LED of the Air Quality Monitor is a toggle with a fixed instance.
    await _call(hass, "switch", "turn_off", "switch.air_monitor_indicator_light")
    assert _feature_calls(mock_client) == [
        (PLUG, "power", "turnOff", None, None),
        (PLUG, "power", "turnOn", None, None),
        (MONITOR, "toggle", "turnOff", "11", None),
    ]
    assert hass.states.get("switch.air_monitor_indicator_light").state == STATE_OFF

    # A refused command changes nothing.
    mock_client.call_feature.side_effect = AmazonEchoError("ENDPOINT_UNREACHABLE")
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_off", "switch.coffee_plug")
    assert hass.states.get("switch.coffee_plug").state == STATE_ON


async def test_lock(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    next(e for e in endpoints if e.id == OLD_LOCK).state["reachable"] = True
    await setup_integration(hass, smart_home_entry)
    assert hass.states.get("lock.back_door").state == "unlocked"
    assert hass.states.get("lock.garage").state == "jammed"

    await _call(hass, "lock", "lock", "lock.back_door")
    assert hass.states.get("lock.back_door").state == "locked"
    await _call(hass, "lock", "unlock", "lock.back_door")
    assert hass.states.get("lock.back_door").state == "unlocked"
    assert _feature_calls(mock_client) == [
        (LOCK, "lock", "lock", None, None),
        (LOCK, "lock", "unlock", None, None),
    ]
    # Amazon offers no unlock for this one.
    with pytest.raises(HomeAssistantError, match="unlock"):
        await _call(hass, "lock", "unlock", "lock.garage")


# ---------------------------------------------------------------------- #
# Updates: re-read after a command, push, removal
# ---------------------------------------------------------------------- #
async def test_commands_are_optimistic_until_the_next_poll(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    mock_client.get_smart_home_endpoints.reset_mock()
    # Amazon disagrees with the optimistic state: its answer wins.
    answer = build_endpoints()
    next(e for e in answer if e.id == PLUG).state["power"] = True
    mock_client.get_smart_home_endpoints.return_value = answer
    await _call(hass, "switch", "turn_off", "switch.coffee_plug")
    assert hass.states.get("switch.coffee_plug").state == STATE_OFF
    await asyncio.sleep(0.01)
    await hass.async_block_till_done(wait_background_tasks=True)
    # no request of its own: the endpoint list is large
    mock_client.get_smart_home_endpoints.assert_not_awaited()
    await smart_home_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.coffee_plug").state == STATE_ON


async def test_smart_home_push(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    """State changes arrive by push and are applied without a request."""
    await setup_integration(hass, smart_home_entry)
    mock_client.get_smart_home_endpoints.reset_mock()
    mock_client.get_endpoint_states.reset_mock()

    mock_client.parse_endpoint_update.return_value = (MOTION, {"motion": True})
    mock_push.emit(PUSH_SMART_HOME, entity={"id": MOTION}, data={"features": []})
    assert hass.states.get("binary_sensor.hall_motion_motion").state == STATE_ON
    payload = mock_client.parse_endpoint_update.call_args.args[0]
    assert payload["entity"] == {"id": MOTION}

    # The same event for the endpoint of an Echo updates the Echo's sensors.
    mock_client.parse_endpoint_update.return_value = (
        "endpoint-echo",
        {"temperature": 30.5},
    )
    mock_push.emit(PUSH_SMART_HOME, entity={"id": "endpoint-echo"})
    assert hass.states.get("sensor.kitchen_echo_temperature").state == "30.5"

    # Unknown endpoints and other payloads are ignored.
    mock_client.parse_endpoint_update.return_value = ("nobody", {"power": True})
    mock_push.emit(PUSH_SMART_HOME)
    mock_client.parse_endpoint_update.return_value = None
    mock_push.emit(PUSH_SMART_HOME)
    await hass.async_block_till_done(wait_background_tasks=True)
    mock_client.get_smart_home_endpoints.assert_not_awaited()
    mock_client.get_endpoint_states.assert_not_awaited()


async def test_endpoints_come_and_go(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    registry = dr.async_get(hass)
    coordinator = smart_home_entry.runtime_data
    plug = registry.async_get_device_by_identifier((DOMAIN, PLUG), ENTRY_ID)
    assert plug is not None
    # A device the account still has cannot be removed by hand.
    assert not await async_remove_config_entry_device(hass, smart_home_entry, plug)

    # A failed read says nothing about which endpoints exist: nothing is removed.
    coordinator._smart_home_fetched = False
    mock_client.get_smart_home_endpoints.side_effect = AmazonEchoError("graphql down")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_device_by_identifier((DOMAIN, PLUG), ENTRY_ID)
    assert hass.states.get("switch.coffee_plug").state == STATE_ON

    # The plug is unlinked from Alexa, a new one appears.
    mock_client.get_smart_home_endpoints.side_effect = None
    mock_client.get_smart_home_endpoints.return_value = [
        *(e for e in build_endpoints() if e.id != PLUG),
        Endpoint(
            id="endpoint-new",
            name="New Plug",
            category="SWITCH",
            operations=POWER,
            state={"power": False},
        ),
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_device_by_identifier((DOMAIN, PLUG), ENTRY_ID) is None
    assert hass.states.get("switch.coffee_plug") is None
    assert hass.states.get("switch.new_plug").state == STATE_OFF
    assert await async_remove_config_entry_device(hass, smart_home_entry, plug)


async def test_turning_the_option_off_removes_the_devices(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    assert hass.states.get("switch.coffee_plug") is not None
    hass.config_entries.async_update_entry(smart_home_entry, options={})
    await hass.config_entries.async_reload(smart_home_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    registry = dr.async_get(hass)
    assert registry.async_get_device_by_identifier((DOMAIN, PLUG), ENTRY_ID) is None
    assert hass.states.get("switch.coffee_plug") is None
    # Amazon's own hardware stays.
    assert hass.states.get("light.kids_glow") is not None


async def test_actions_on_a_smart_home_device(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    await setup_integration(hass, smart_home_entry)
    plug = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, PLUG), ENTRY_ID)
    # The escape hatch takes the endpoint of the picked smart-home device.
    await hass.services.async_call(
        DOMAIN,
        "call_feature",
        {"device_id": plug.id, "feature": "power", "operation": "turnOff"},
        blocking=True,
    )
    assert _feature_calls(mock_client) == [(PLUG, "power", "turnOff", None, None)]
    # A plug cannot speak.
    with pytest.raises(ServiceValidationError, match="needs a device"):
        await hass.services.async_call(
            DOMAIN,
            "send_text_command",
            {"device_id": plug.id, "text": "hello"},
            blocking=True,
        )


async def test_diagnostics_with_endpoints_and_guard(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    smart_home_entry: MockConfigEntry,
    endpoints: list[Endpoint],
) -> None:
    mock_client.get_guard.return_value = Guard(
        entity_id="guard-entity", appliance_id="AAA_Guard_secret", state="ARMED_STAY"
    )
    await setup_integration(hass, smart_home_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, smart_home_entry)
    dump = json.dumps(diagnostics, cls=ExtendedJSONEncoder)
    for secret in (LAMP, PLUG, GLOW, "GLOW0000000001", "guard-entity", "AAA_Guard"):
        assert secret not in dump, secret
    data = diagnostics["data"]
    lamp = data["smart_home"]["endpoint_0"]
    assert (lamp["name"], lamp["category"]) == ("Desk Lamp", "LIGHT")
    assert lamp["state"]["color_temperature"] == 2700
    assert "power.turnOn" in lamp["operations"]
    assert data["guard"]["state"] == "ARMED_STAY"


# ---------------------------------------------------------------------- #
# Alexa Guard
# ---------------------------------------------------------------------- #
async def test_guard_panel(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    guard = Guard(entity_id="guard-entity", appliance_id="AAA_Guard_1")
    guard.state = "ARMED_STAY"
    mock_client.get_guard.return_value = guard
    # one Echo of the account has Guard
    mock_client.get_devices.side_effect = lambda: [
        Device(
            serial=d.serial,
            device_type=d.device_type,
            name=d.name,
            family=d.family,
            online=d.online,
            capabilities=d.capabilities | {"GUARD_EARCON"}
            if d.serial == ECHO
            else d.capabilities,
            cluster_members=d.cluster_members,
            parent_clusters=d.parent_clusters,
        )
        for d in build_devices()
    ]
    await setup_integration(hass, mock_config_entry)
    entity_id = "alarm_control_panel.test_account_alexa_guard"
    state = hass.states.get(entity_id)
    assert state.state == "disarmed"
    assert state.attributes["code_arm_required"] is False

    def arm(panel: Guard, armed: bool, device: Device | None) -> None:
        panel.state = "ARMED_AWAY" if armed else "ARMED_STAY"

    mock_client.set_guard.side_effect = arm
    await _call(hass, "alarm_control_panel", "alarm_arm_away", entity_id)
    panel, armed, device = mock_client.set_guard.await_args.args
    assert (panel, armed, device.serial) == (guard, True, ECHO)
    assert hass.states.get(entity_id).state == "armed_away"

    await _call(hass, "alarm_control_panel", "alarm_disarm", entity_id)
    assert mock_client.set_guard.await_args.args[1] is False
    assert hass.states.get(entity_id).state == "disarmed"

    # The state could not be read, then the account lost Guard.
    guard.state = None
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unknown"
    mock_client.get_guard.return_value = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_guard_without_an_echo_at_hand(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """No Echo with Guard online: the library falls back to the state API."""
    mock_client.get_guard.return_value = Guard(
        entity_id="guard-entity", appliance_id="AAA_Guard_1", state="ARMED_AWAY"
    )
    await setup_integration(hass, mock_config_entry)
    entity_id = "alarm_control_panel.test_account_alexa_guard"
    assert hass.states.get(entity_id).state == "armed_away"
    await _call(hass, "alarm_control_panel", "alarm_disarm", entity_id)
    assert mock_client.set_guard.await_args.args[2] is None
