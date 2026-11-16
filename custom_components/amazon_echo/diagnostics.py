"""Diagnostics support."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import AmazonEchoConfigEntry
from .const import CONF_CREDENTIALS, CONF_HOSTS, DOMAIN

TO_REDACT = {
    CONF_CREDENTIALS,
    CONF_HOSTS,
    "access_token",
    "account_id",
    "address",
    "appliance_id",
    "cluster_members",
    "cookies",
    "customer_id",
    "customer_name",
    "device_id",
    "device_serial",
    "email",
    "endpoint_id",
    "entity_id",
    "geolocation",
    "host",
    "id",
    "mac",
    "parent_clusters",
    "person",
    "raw",
    "refresh_token",
    "response",
    "serial",
    "spotify_user",
    "unique_id",
    "utterance",
    "wifi",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AmazonEchoConfigEntry
) -> dict[str, Any]:
    """Return the entry and the last snapshot, redacted.

    The snapshot is keyed by serial number, so every device gets an alias
    (``device_0``...) before the values are redacted by key; smart-home
    endpoints become ``endpoint_0``...
    """
    coordinator = entry.runtime_data
    data = asdict(coordinator.data)
    alias = {serial: f"device_{i}" for i, serial in enumerate(data["devices"])}
    alias |= {key: f"endpoint_{i}" for i, key in enumerate(data["smart_home"])}
    for device in data["devices"].values():
        device["capabilities"] = sorted(device["capabilities"])  # JSON has no set
    for endpoint in data["smart_home"].values():
        endpoint["operations"] = sorted(endpoint["operations"])

    def by_alias(values: dict[str, Any]) -> dict[str, Any]:
        return {alias.get(serial, "unknown"): v for serial, v in values.items()}

    # Dicts that are one record, not a table keyed by serial number.
    records = ("lists", "music_providers", "guard", "last_called")
    snapshot = {
        key: by_alias(value)
        if isinstance(value, dict) and key not in records
        else value
        for key, value in data.items()
    }
    snapshot["lists"] = [
        {"kind": lst["kind"], "items": len(items)}
        for lst, items in data["lists"].values()
    ]
    snapshot["routines"] = len(data["routines"])
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT | {"title"}),
        "push_connected": coordinator.push_connected,
        "data": async_redact_data(snapshot, TO_REDACT),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: AmazonEchoConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return what the snapshot holds about one device, redacted."""
    data = asdict(entry.runtime_data.data)
    key = next((i[1] for i in device.identifiers if i[0] == DOMAIN), None)
    for record in (data["devices"].get(key), data["smart_home"].get(key)):
        for field in ("capabilities", "operations"):
            if record and field in record:
                record[field] = sorted(record[field])  # JSON has no set
    tables = {
        name: table[key]
        for name, table in data.items()
        if isinstance(table, dict) and name != "lists" and key in table
    }
    return async_redact_data(tables, TO_REDACT)
