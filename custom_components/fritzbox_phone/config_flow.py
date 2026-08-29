"""Config flow for the FRITZ!Box phone integration."""
from __future__ import annotations

import logging
from typing import Any

from fritzconnection.core.exceptions import FritzAuthorizationError, FritzConnectionException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import FritzBoxPhoneClient
from .const import (
    CONF_CALL_LIST_DAYS,
    CONF_CALL_LIST_MAX,
    CONF_CALLMONITOR_PORT,
    CONF_ENABLE_CALLMONITOR,
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_THRESHOLD,
    CONF_PHONEBLOCK_USERNAME,
    CONF_PREFIXES,
    CONF_REVERSE_LOOKUP_ENABLED,
    CONF_SCAN_INTERVAL,
    CONF_USE_TLS,
    DEFAULT_CALL_LIST_DAYS,
    DEFAULT_CALL_LIST_MAX,
    DEFAULT_CALLMONITOR_PORT,
    DEFAULT_ENABLE_CALLMONITOR,
    DEFAULT_PHONEBLOCK_ENABLED,
    DEFAULT_PHONEBLOCK_THRESHOLD,
    DEFAULT_REVERSE_LOOKUP_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="fritz.box"): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_USE_TLS, default=False): bool,
        vol.Optional(CONF_PORT): int,
    }
)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Try to connect and authenticate against the FRITZ!Box. Blocking calls
    are run in an executor. Raises on failure."""
    client = FritzBoxPhoneClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        use_tls=data.get(CONF_USE_TLS, False),
    )

    def _connect_and_check() -> str | None:
        client.connect()
        return client.serial_number

    serial = await hass.async_add_executor_job(_connect_and_check)
    return {"title": f"FRITZ!Box ({data[CONF_HOST]})", "serial": serial}


class FritzBoxPhoneConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FRITZ!Box phone."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate_input(self.hass, user_input)
            except FritzAuthorizationError:
                errors["base"] = "invalid_auth"
            except (FritzConnectionException, OSError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unerwarteter Fehler beim Verbindungstest")
                errors["base"] = "unknown"
            else:
                unique_id = info["serial"] or user_input[CONF_HOST]
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FritzBoxPhoneOptionsFlow()


class FritzBoxPhoneOptionsFlow(config_entries.OptionsFlow):
    """Options for polling interval, call list scope and PhoneBlock spam-check."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            if user_input.get(CONF_PHONEBLOCK_ENABLED) and not (
                user_input.get(CONF_PHONEBLOCK_USERNAME)
                and user_input.get(CONF_PHONEBLOCK_PASSWORD)
            ):
                errors["base"] = "phoneblock_credentials_required"
            else:
                return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=30)),
                vol.Optional(
                    CONF_CALL_LIST_DAYS,
                    default=options.get(CONF_CALL_LIST_DAYS, DEFAULT_CALL_LIST_DAYS),
                ): vol.All(int, vol.Range(min=0, max=999)),
                vol.Optional(
                    CONF_CALL_LIST_MAX,
                    default=options.get(CONF_CALL_LIST_MAX, DEFAULT_CALL_LIST_MAX),
                ): vol.All(int, vol.Range(min=0, max=999)),
                vol.Optional(
                    CONF_ENABLE_CALLMONITOR,
                    default=options.get(CONF_ENABLE_CALLMONITOR, DEFAULT_ENABLE_CALLMONITOR),
                ): bool,
                vol.Optional(
                    CONF_CALLMONITOR_PORT,
                    default=options.get(CONF_CALLMONITOR_PORT, DEFAULT_CALLMONITOR_PORT),
                ): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_PREFIXES,
                    default=options.get(CONF_PREFIXES, ""),
                ): str,
                vol.Optional(
                    CONF_PHONEBLOCK_ENABLED,
                    default=options.get(CONF_PHONEBLOCK_ENABLED, DEFAULT_PHONEBLOCK_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_PHONEBLOCK_USERNAME,
                    default=options.get(CONF_PHONEBLOCK_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_PHONEBLOCK_PASSWORD,
                    default=options.get(CONF_PHONEBLOCK_PASSWORD, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_PHONEBLOCK_THRESHOLD,
                    default=options.get(CONF_PHONEBLOCK_THRESHOLD, DEFAULT_PHONEBLOCK_THRESHOLD),
                ): vol.All(int, vol.Range(min=1, max=100)),
                vol.Optional(
                    CONF_REVERSE_LOOKUP_ENABLED,
                    default=options.get(
                        CONF_REVERSE_LOOKUP_ENABLED, DEFAULT_REVERSE_LOOKUP_ENABLED
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
