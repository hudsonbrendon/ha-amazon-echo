"""Config, discovery, reauth, reconfigure and options flows."""

from __future__ import annotations

from ipaddress import ip_address
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from amazon_echo import (
    Account,
    AmazonEchoAuthenticationError,
    AmazonEchoConnectionError,
    AmazonEchoError,
    LocalInfo,
)
from homeassistant import config_entries
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.amazon_echo.config_flow import _language, _read_cookies
from custom_components.amazon_echo.const import (
    CONF_CREDENTIALS,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_PUSH,
    CONF_ENTRY,
    CONF_HOSTS,
    CONF_PUBLIC_URL,
    CONF_SCAN_INTERVAL,
    CONF_SMART_HOME,
    DOMAIN,
)

from .conftest import (
    AUTHORIZE_URL,
    CUSTOMER_ID,
    ECHO_HOST,
    ECHO_MAC,
    REDIRECT_URL,
    TITLE,
    FakePush,
    setup_integration,
)

COOKIES = [{"name": "session-id", "value": "fake-cookie", "domain": ".amazon.com"}]
READ_COOKIES = "custom_components.amazon_echo.config_flow._read_cookies"


def _alexa_media(
    hass: HomeAssistant, email: str = "user@example.com"
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain="alexa_media",
        title=email,
        data={
            "email": email,
            "url": "amazon.com",
            "oauth": {
                "refresh_token": "fake-refresh-token",
                "access_token": "fake-access-token",
                "mac_dms": {},
            },
        },
    )
    entry.add_to_hass(hass)
    return entry


def _zeroconf(
    type_: str = "_spotify-connect._tcp.local.", host: str = ECHO_HOST, **props: str
) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="fake-echo.local.",
        name=f"Fake Instance.{type_}",
        port=4070,
        properties=props,
        type=type_,
    )


async def test_browser_flow(
    hass: HomeAssistant, mock_client: MagicMock, mock_register: AsyncMock
) -> None:
    """Without Alexa Media Player the browser sign-in is the only method."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "browser"
    assert result["description_placeholders"] == {"url": AUTHORIZE_URL}
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: "https://www.amazon.com/somewhere-else"}
    )
    assert result["errors"] == {"base": "invalid_url"}
    mock_register.assert_not_awaited()

    for error, expected in (
        (AmazonEchoAuthenticationError("refused"), "invalid_auth"),
        (AmazonEchoConnectionError("offline"), "cannot_connect"),
        (AmazonEchoError("weird"), "unknown"),
    ):
        mock_register.side_effect = error
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_URL: REDIRECT_URL}
        )
        assert result["errors"] == {"base": expected}

    mock_register.side_effect = None
    for error, expected in (
        (AmazonEchoAuthenticationError("refused"), "invalid_auth"),
        (AmazonEchoConnectionError("offline"), "cannot_connect"),
        (AmazonEchoError("weird"), "unknown"),
    ):
        mock_client.get_account.side_effect = error
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_URL: REDIRECT_URL}
        )
        assert result["errors"] == {"base": expected}

    mock_client.get_account.side_effect = None
    with patch("custom_components.amazon_echo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_URL: f"  {REDIRECT_URL} "}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["result"].unique_id == CUSTOMER_ID
    assert result["data"][CONF_HOSTS] == {}
    stored = result["data"][CONF_CREDENTIALS]
    assert stored["refresh_token"] == "fake-refresh-token"
    assert "password" not in json.dumps(result["data"])
    assert mock_register.await_args.args[1] == REDIRECT_URL


async def test_import_alexa_media(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """With an Alexa Media Player entry the user picks the import: zero typing."""
    _alexa_media(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["import_alexa_media", "browser"]

    with (
        patch(READ_COOKIES, return_value=COOKIES) as read,
        patch("custom_components.amazon_echo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_alexa_media"}
        )
        await hass.async_block_till_done()
    assert read.call_args.args[0].endswith(
        ".storage/alexa_media.user@example.com.cookies"
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == CUSTOMER_ID
    stored = result["data"][CONF_CREDENTIALS]
    assert stored["refresh_token"] == "fake-refresh-token"
    assert stored["source"] == "alexa_media"


async def test_import_picks_one_of_many(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    _alexa_media(hass, "first@example.com")
    second = _alexa_media(hass, "second@example.com")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_alexa_media"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "import_alexa_media"
    with (
        patch(READ_COOKIES, return_value=COOKIES) as read,
        patch("custom_components.amazon_echo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENTRY: second.entry_id}
        )
        await hass.async_block_till_done()
    assert "second@example.com" in read.call_args.args[0]
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("cookies", "account_error", "reason"),
    [
        (OSError("no file"), None, "import_failed"),
        (COOKIES, AmazonEchoAuthenticationError("expired"), "invalid_auth"),
        (COOKIES, AmazonEchoConnectionError("offline"), "cannot_connect"),
    ],
)
async def test_import_failures(
    hass: HomeAssistant,
    mock_client: MagicMock,
    cookies: object,
    account_error: Exception | None,
    reason: str,
) -> None:
    _alexa_media(hass)
    mock_client.get_account.side_effect = account_error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(READ_COOKIES, side_effect=[cookies]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_alexa_media"}
        )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == reason


def test_read_cookies(tmp_path: Path) -> None:
    path = tmp_path / "alexa_media.user@example.com.cookies"
    path.write_text(json.dumps({"cookies": COOKIES}))
    assert _read_cookies(str(path)) == COOKIES
    with pytest.raises(OSError):
        _read_cookies(str(tmp_path / "missing"))


async def test_language(hass: HomeAssistant) -> None:
    hass.config.language, hass.config.country = "pt-BR", "BR"
    assert _language(hass) == "pt-BR"
    hass.config.language = "en"
    assert _language(hass) == "en-US"
    hass.config.language = "pt"
    assert _language(hass) == "pt-BR"


async def test_same_account_twice_aborts(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_register: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: REDIRECT_URL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_register: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "browser"

    # Signing in with another Amazon account is refused.
    mock_client.get_account.return_value = Account(customer_id="A2OTHER", name="X")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: REDIRECT_URL}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"

    mock_client.get_account.return_value = Account(customer_id=CUSTOMER_ID, name="X")
    mock_register.return_value.refresh_token = "renewed-fake-token"
    result = await mock_config_entry.start_reauth_flow(hass)
    with patch("custom_components.amazon_echo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: REDIRECT_URL}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    data = mock_config_entry.data
    assert data[CONF_CREDENTIALS]["refresh_token"] == "renewed-fake-token"
    assert data[CONF_HOSTS] == {ECHO_MAC: ECHO_HOST}  # kept


async def test_reauth_offers_the_import(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    _alexa_media(hass)
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(READ_COOKIES, return_value=COOKIES),
        patch("custom_components.amazon_echo.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "import_alexa_media"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_CREDENTIALS]["source"] == "alexa_media"


async def test_reconfigure(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_register: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "browser"
    with patch("custom_components.amazon_echo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: REDIRECT_URL}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_zeroconf_new_account(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_register: AsyncMock,
    mock_local: dict[str, AsyncMock],
) -> None:
    """A discovered Echo offers the setup once, then goes through the user flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {"name": "Kitchen Echo"}
    mock_local["probe_local"].assert_awaited_once()
    assert mock_local["probe_local"].await_args.args == (ECHO_HOST,)

    # A second Echo announcing itself does not open a second card.
    second = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf(host="192.0.2.11"),
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "browser"
    with patch("custom_components.amazon_echo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: REDIRECT_URL}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == CUSTOMER_ID


@pytest.mark.parametrize(
    "info", [None, LocalInfo(host=ECHO_HOST, name="Some Speaker", brand="Other")]
)
async def test_zeroconf_not_amazon(
    hass: HomeAssistant, mock_local: dict[str, AsyncMock], info: LocalInfo | None
) -> None:
    mock_local["probe_local"].return_value = info
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_amazon_device"


async def test_zeroconf_fire_tv(
    hass: HomeAssistant, mock_local: dict[str, AsyncMock]
) -> None:
    """WhisperPlay is Amazon by definition: no probe, name from the TXT record."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf("_amzn-wplay._tcp.local.", n="Living Room TV"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"name": "Living Room TV"}
    mock_local["probe_local"].assert_not_awaited()


async def test_zeroconf_hands_host_to_existing_entry(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.office_show_ip_address") is None
    mock_local["probe_local"].return_value = LocalInfo(
        host="192.0.2.11", name="Office Show", brand="Amazon"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf(host="192.0.2.11"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done(wait_background_tasks=True)
    # The Show had no known host; the discovery gave it one (matched by name),
    # and since its MAC is known the host is now stored for the next restart.
    assert hass.states.get("sensor.office_show_ip_address").state == "192.0.2.11"
    assert mock_config_entry.data[CONF_HOSTS]["aa:bb:cc:00:00:02"] == "192.0.2.11"


async def test_dhcp_updates_the_stored_host(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    for mac, ip in (("aabbcc000001", "192.0.2.99"), ("ffffffffffff", "192.0.2.50")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(ip=ip, hostname="fake", macaddress=mac),
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
    hosts = mock_config_entry.data[CONF_HOSTS]
    assert hosts[ECHO_MAC] == "192.0.2.99"
    assert "ff:ff:ff:ff:ff:ff" not in hosts  # not one of our devices


async def test_options_flow(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 120, CONF_ENABLE_PUSH: False, CONF_ENABLE_LOCAL: False},
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_SCAN_INTERVAL: 120,
        CONF_ENABLE_PUSH: False,
        CONF_ENABLE_LOCAL: False,
        CONF_SMART_HOME: False,  # opt-in: nothing is imported unless asked for
    }
    # Reloaded with the new options: no push, no LAN probing, 120 s polling.
    coordinator = mock_config_entry.runtime_data
    assert coordinator.update_interval.total_seconds() == 120
    assert mock_push.start.await_count == 1  # only the first load started it


async def test_options_flow_public_url(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_push: FakePush,
    mock_local: dict[str, AsyncMock],
    mock_config_entry: MockConfigEntry,
) -> None:
    """Alexa only fetches audio over HTTPS, so nothing else is accepted."""
    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 300, CONF_PUBLIC_URL: "http://ha.example.com"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PUBLIC_URL: "not_https"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 300, CONF_PUBLIC_URL: "https://ha.example.com"},
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_PUBLIC_URL] == "https://ha.example.com"
