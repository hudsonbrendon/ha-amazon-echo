"""Setup, unload, auth failure, devices."""

from __future__ import annotations

from unittest.mock import MagicMock

from amazon_echo import (
    AmazonEchoAuthenticationError,
    AmazonEchoConnectionError,
    Credentials,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo import async_remove_config_entry_device
from custom_components.amazon_echo.const import CONF_CREDENTIALS, CONF_HOSTS, DOMAIN

from .conftest import (
    APP,
    CUSTOMER_ID,
    ECHO,
    ECHO_HOST,
    ECHO_MAC,
    ENTRY_ID,
    FIRE_TV,
    GROUP,
    FakePush,
    build_devices,
    setup_integration,
)


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_push.start.assert_awaited_once()

    registry = dr.async_get(hass)
    echo = registry.async_get_device_by_identifier((DOMAIN, ECHO), ENTRY_ID)
    assert echo is not None
    assert echo.manufacturer == "Amazon" and echo.model == "Echo Dot"
    assert echo.sw_version == "1.2.3" and echo.serial_number == ECHO
    assert (dr.CONNECTION_NETWORK_MAC, ECHO_MAC) in echo.connections
    assert echo.via_device_id is None
    account = registry.async_get_device_by_identifier((DOMAIN, CUSTOMER_ID), ENTRY_ID)
    assert account is not None and account.entry_type is dr.DeviceEntryType.SERVICE
    assert (
        registry.async_get_device_by_identifier((DOMAIN, GROUP), ENTRY_ID) is not None
    )
    # Alexa app registrations never become devices.
    assert registry.async_get_device_by_identifier((DOMAIN, APP), ENTRY_ID) is None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    mock_push.stop.assert_awaited_once()
    mock_client.close.assert_awaited_once()


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.get_devices.side_effect = AmazonEchoAuthenticationError("expired")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_setup_cloud_down_retries(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.get_devices.side_effect = AmazonEchoConnectionError("down")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_credentials_update_is_persisted(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    updated = Credentials.from_dict(mock_config_entry.data[CONF_CREDENTIALS])
    updated.access_token = "new-fake-token"
    mock_client.on_credentials_update(updated)
    stored = mock_config_entry.data
    assert stored[CONF_CREDENTIALS]["access_token"] == "new-fake-token"
    assert stored[CONF_HOSTS] == {ECHO_MAC: ECHO_HOST}


async def test_stale_device_removed_and_removal_guard(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    registry = dr.async_get(hass)
    fire_tv = registry.async_get_device_by_identifier((DOMAIN, FIRE_TV), ENTRY_ID)
    assert fire_tv is not None
    # A device the account still has cannot be removed by hand.
    assert not await async_remove_config_entry_device(hass, mock_config_entry, fire_tv)

    mock_client.get_devices.side_effect = lambda: [
        d for d in build_devices() if d.serial != FIRE_TV
    ]
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_device_by_identifier((DOMAIN, FIRE_TV), ENTRY_ID) is None
    assert await async_remove_config_entry_device(hass, mock_config_entry, fire_tv)
