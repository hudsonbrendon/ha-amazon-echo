"""Config flow for the Amazon Echo integration."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from amazon_echo import (
    Account,
    AmazonEchoAuthenticationError,
    AmazonEchoClient,
    AmazonEchoConnectionError,
    AmazonEchoError,
    AuthorizeRequest,
    Credentials,
    build_authorize_url,
    probe_local,
    register_device,
)

from .const import (
    ALEXA_MEDIA_DOMAIN,
    CONF_CREDENTIALS,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_PUSH,
    CONF_ENTRY,
    CONF_HOSTS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

AUTHORIZATION_CODE = "openid.oa2.authorization_code"
BROWSER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=10,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Optional(CONF_ENABLE_PUSH, default=True): BooleanSelector(),
        vol.Optional(CONF_ENABLE_LOCAL, default=True): BooleanSelector(),
    }
)


def _language(hass: HomeAssistant) -> str:
    """Locale for the Amazon sign-in page (``pt-BR``, ``en-US``...)."""
    language = hass.config.language
    if "-" in language:
        return language
    return "en-US" if language == "en" else f"{language}-{hass.config.country or 'US'}"


def _read_cookies(path: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = json.loads(Path(path).read_text())["cookies"]
    return cookies


class AmazonEchoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in (import or browser), discovery, reauth and reconfigure."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._authorize: AuthorizeRequest | None = None
        self._name: str | None = None

    # ------------------------------------------------------------------ #
    # Sign-in methods
    # ------------------------------------------------------------------ #
    async def _async_choose_method(self, step_id: str) -> ConfigFlowResult:
        """Offer the import only when Alexa Media Player is set up."""
        if self.hass.config_entries.async_entries(ALEXA_MEDIA_DOMAIN):
            return self.async_show_menu(
                step_id=step_id, menu_options=["import_alexa_media", "browser"]
            )
        return await self.async_step_browser()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick how to sign in."""
        return await self._async_choose_method("user")

    async def async_step_import_alexa_media(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reuse the session of an Alexa Media Player entry: nothing to type."""
        sources = self.hass.config_entries.async_entries(ALEXA_MEDIA_DOMAIN)
        if not sources:
            return self.async_abort(reason="import_failed")
        if len(sources) > 1 and user_input is None:
            return self.async_show_form(
                step_id="import_alexa_media",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_ENTRY): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    SelectOptionDict(value=e.entry_id, label=e.title)
                                    for e in sources
                                ]
                            )
                        )
                    }
                ),
            )
        source = next(
            (e for e in sources if e.entry_id == (user_input or {}).get(CONF_ENTRY)),
            sources[0],
        )
        path = self.hass.config.path(
            ".storage", f"{ALEXA_MEDIA_DOMAIN}.{source.data.get('email')}.cookies"
        )
        try:
            cookies = await self.hass.async_add_executor_job(_read_cookies, path)
            credentials = Credentials.from_alexa_media(dict(source.data), cookies)
        except (OSError, ValueError, KeyError, TypeError, AmazonEchoError) as err:
            LOGGER.warning("Could not import the Alexa Media Player session: %s", err)
            return self.async_abort(reason="import_failed")
        error, account = await self._async_validate(credentials)
        if account is None:
            return self.async_abort(reason=error or "unknown")
        return await self._async_finish(credentials, account)

    async def async_step_browser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in to Amazon in the user's browser and paste the final address."""
        if self._authorize is None:
            self._authorize = build_authorize_url(language=_language(self.hass))
        errors: dict[str, str] = {}
        if user_input is not None:
            url: str = user_input[CONF_URL].strip()
            error, account, credentials = None, None, None
            if AUTHORIZATION_CODE not in url:
                error = "invalid_url"
            else:
                try:
                    credentials = await register_device(
                        self._authorize,
                        url,
                        session=async_get_clientsession(self.hass),
                    )
                except AmazonEchoAuthenticationError:
                    error = "invalid_auth"
                except AmazonEchoConnectionError:
                    error = "cannot_connect"
                except AmazonEchoError:
                    LOGGER.exception("Unexpected error registering with Amazon")
                    error = "unknown"
                else:
                    error, account = await self._async_validate(credentials)
            if credentials is not None and account is not None:
                return await self._async_finish(credentials, account)
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="browser",
            data_schema=BROWSER_SCHEMA,
            description_placeholders={"url": self._authorize.url},
            errors=errors,
        )

    async def _async_validate(
        self, credentials: Credentials
    ) -> tuple[str | None, Account | None]:
        """Check the session against the cloud; return (error, account)."""
        client = AmazonEchoClient(
            credentials, session=async_get_clientsession(self.hass)
        )
        try:
            return None, await client.get_account()
        except AmazonEchoAuthenticationError:
            return "invalid_auth", None
        except AmazonEchoConnectionError:
            return "cannot_connect", None
        except AmazonEchoError:
            LOGGER.exception("Unexpected error validating the Amazon session")
            return "unknown", None

    async def _async_finish(
        self, credentials: Credentials, account: Account
    ) -> ConfigFlowResult:
        """Create the entry, or update the one being reauthed/reconfigured."""
        await self.async_set_unique_id(account.customer_id, raise_on_progress=False)
        stored = {CONF_CREDENTIALS: credentials.to_dict()}
        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            entry = (
                self._get_reauth_entry()
                if self.source == SOURCE_REAUTH
                else self._get_reconfigure_entry()
            )
            return self.async_update_reload_and_abort(entry, data_updates=stored)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=account.name or account.email or "Amazon Echo",
            data={**stored, CONF_HOSTS: {}},
        )

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """An Echo (Spotify Connect) or a Fire TV (WhisperPlay) was announced."""
        host = discovery_info.host
        if discovery_info.type.startswith("_spotify-connect."):
            info = await probe_local(host, session=async_get_clientsession(self.hass))
            if info is None or (info.brand or "").casefold() != "amazon":
                return self.async_abort(reason="not_amazon_device")
            name = info.name
        else:
            name = discovery_info.properties.get("n")
        name = name or discovery_info.name.split(".")[0]
        if entries := self._async_current_entries(include_ignore=True):
            for entry in entries:
                if entry.state is ConfigEntryState.LOADED:
                    entry.runtime_data.async_add_discovered(name, host)
            return self.async_abort(reason="already_configured")
        # One discovery card for the whole account, however many Echos announce.
        await self.async_set_unique_id(DOMAIN)
        self._name = name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_discovery_confirm()

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """A registered device got an address: store it for the LAN probe."""
        mac = dr.format_mac(discovery_info.macaddress)
        registry = dr.async_get(self.hass)
        for entry in self._async_current_entries(include_ignore=False):
            hosts: dict[str, str] = entry.data.get(CONF_HOSTS, {})
            if hosts.get(mac) != discovery_info.ip and (
                registry.async_get_device_by_connection(
                    (dr.CONNECTION_NETWORK_MAC, mac), entry.entry_id
                )
            ):
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_HOSTS: {**hosts, mac: discovery_info.ip}},
                )
        return self.async_abort(reason="already_configured")

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered device, then sign in."""
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._name or "Amazon Echo"},
        )

    # ------------------------------------------------------------------ #
    # Reauth / reconfigure / options
    # ------------------------------------------------------------------ #
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Amazon rejected the stored session."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick how to sign in again."""
        return await self._async_choose_method("reauth_confirm")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the stored session (same account)."""
        return await self._async_choose_method("reconfigure")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AmazonEchoOptionsFlow:
        """Return the options flow."""
        return AmazonEchoOptionsFlow()


class AmazonEchoOptionsFlow(OptionsFlowWithReload):
    """Polling interval, push channel and LAN probing."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show/save the options."""
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
