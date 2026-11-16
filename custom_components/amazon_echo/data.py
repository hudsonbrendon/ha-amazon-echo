"""Snapshot of an Amazon account held by the coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.helpers.device_registry import format_mac

from amazon_echo import (
    BluetoothDevice,
    Device,
    EchoList,
    ListItem,
    LocalInfo,
    MediaState,
    Notification,
    Routine,
)


@dataclass(kw_only=True)
class AmazonEchoData:
    """Everything known about the account; dicts are keyed by device serial."""

    devices: dict[str, Device] = field(default_factory=dict)

    # Fast tier (poll + push).
    dnd: dict[str, bool] = field(default_factory=dict)
    volumes: dict[str, tuple[int, bool]] = field(default_factory=dict)
    bluetooth: dict[str, list[BluetoothDevice]] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    endpoints: dict[str, dict[str, Any]] = field(default_factory=dict)
    media: dict[str, MediaState] = field(default_factory=dict)

    # Slow tier, account wide.
    alarm_volumes: dict[str, int] = field(default_factory=dict)
    wake_words: dict[str, str] = field(default_factory=dict)
    ascending_alarms: dict[str, bool] = field(default_factory=dict)
    whisper_mode: bool | None = None
    adaptive_volume: bool | None = None
    routines: list[Routine] = field(default_factory=list)
    music_providers: dict[str, str] = field(default_factory=dict)
    lists: dict[str, tuple[EchoList, list[ListItem]]] = field(default_factory=dict)

    # Slow tier, per device: serial -> {fetcher or setting key: value}.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Local network (independent of the cloud).
    hosts: dict[str, str] = field(default_factory=dict)
    local: dict[str, LocalInfo] = field(default_factory=dict)
    reachable: dict[str, bool] = field(default_factory=dict)

    def setting(self, device: Device, key: str) -> Any:
        """Return a slow-tier value of a device (None when it has none)."""
        return self.settings.get(device.serial, {}).get(key)

    def endpoint(self, device: Device, key: str) -> Any:
        """Return an endpoint state value of a device."""
        return self.endpoints.get(device.serial, {}).get(key)

    def mac(self, device: Device) -> str | None:
        """Return the formatted MAC address of a device when any source has it."""
        mac = (
            device.mac
            or (self.setting(device, "wifi") or (None, None))[1]
            or self.endpoint(device, "mac")
        )
        return format_mac(mac) if mac else None
