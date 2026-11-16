"""Amazon Echo integration: Alexa cloud, HTTP/2 push and LAN discovery."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from amazon_echo import AmazonEchoClient, Credentials

from .const import CONF_CREDENTIALS, DOMAIN, PLATFORMS
from .coordinator import AmazonEchoCoordinator
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type AmazonEchoConfigEntry = ConfigEntry[AmazonEchoCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration-level actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AmazonEchoConfigEntry) -> bool:
    """Set up an Amazon account from a config entry."""

    @callback
    def save_credentials(credentials: Credentials) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_CREDENTIALS: credentials.to_dict()}
        )

    client = AmazonEchoClient(
        Credentials.from_dict(entry.data[CONF_CREDENTIALS]),
        session=async_get_clientsession(hass),
        on_credentials_update=save_credentials,
    )
    coordinator = AmazonEchoCoordinator(hass, entry, client)

    async def close() -> None:
        await coordinator.async_stop()
        await client.close()

    entry.async_on_unload(close)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AmazonEchoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AmazonEchoConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device only when the account no longer has it."""
    current = {(DOMAIN, serial) for serial in entry.runtime_data.data.devices}
    current.add((DOMAIN, entry.unique_id or entry.entry_id))
    return not device_entry.identifiers & current
