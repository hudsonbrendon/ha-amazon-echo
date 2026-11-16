"""Diagnostics support."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AmazonEchoConfigEntry
from .const import CONF_CREDENTIALS, CONF_HOSTS

TO_REDACT = {
    CONF_CREDENTIALS,
    CONF_HOSTS,
    "access_token",
    "account_id",
    "address",
    "cluster_members",
    "cookies",
    "customer_id",
    "customer_name",
    "device_id",
    "device_serial",
    "email",
    "endpoint_id",
    "geolocation",
    "host",
    "id",
    "mac",
    "parent_clusters",
    "raw",
    "refresh_token",
    "serial",
    "spotify_user",
    "unique_id",
    "wifi",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AmazonEchoConfigEntry
) -> dict[str, Any]:
    """Return the entry and the last snapshot, redacted.

    The snapshot is keyed by serial number, so every device gets an alias
    (``device_0``...) before the values are redacted by key.
    """
    coordinator = entry.runtime_data
    data = asdict(coordinator.data)
    alias = {serial: f"device_{i}" for i, serial in enumerate(data["devices"])}
    for device in data["devices"].values():
        device["capabilities"] = sorted(device["capabilities"])  # JSON has no set

    def by_alias(values: dict[str, Any]) -> dict[str, Any]:
        return {alias.get(serial, "unknown"): v for serial, v in values.items()}

    snapshot = {
        key: by_alias(value)
        if isinstance(value, dict) and key not in ("lists", "music_providers")
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
