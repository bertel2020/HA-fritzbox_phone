"""Config flow for the FRITZ!Box phone integration."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
    FritzSecurityError,
)
import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
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

_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="fritz.box"): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
        vol.Optional(CONF_USE_TLS, default=False): bool,
        vol.Optional(CONF_PORT): int,
    }
)


async def _validate_input(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, Any]:
    """Try to connect and authenticate against the FRITZ!Box. Blocking calls
    are run in an executor. Raises on failure."""
    client = FritzBoxPhoneClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        use_tls=data.get(CONF_USE_TLS, False),
    )
    await hass.async_add_executor_job(client.connect)
    return {"title": f"FRITZ!Box ({data[CONF_HOST]})", "serial": client.serial_number}


async def _try_validate(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """_validate_input, with the failure mapped to a form error key."""
    try:
        return await _validate_input(hass, data), None
    except (FritzAuthorizationError, FritzSecurityError):
        return None, "invalid_auth"
    except (FritzConnectionException, requests.RequestException, OSError):
        return None, "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unerwarteter Fehler beim Verbindungstest")
        return None, "unknown"


class FritzBoxPhoneConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FRITZ!Box phone."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await _try_validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                unique_id = info["serial"] or user_input[CONF_HOST]
                await self.async_set_unique_id(str(unique_id))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials after the box rejected the stored ones."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            info, error = await _try_validate(self.hass, data)
            if error:
                errors["base"] = error
            elif entry.unique_id and info["serial"] and info["serial"] != entry.unique_id:
                return self.async_abort(reason="wrong_device")
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
                }
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host, port, TLS or credentials of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            if not user_input.get(CONF_PORT):
                data.pop(CONF_PORT, None)
            info, error = await _try_validate(self.hass, data)
            if error:
                errors["base"] = error
            elif entry.unique_id and info["serial"] and info["serial"] != entry.unique_id:
                return self.async_abort(reason="wrong_device")
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        suggested = user_input or dict(entry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, suggested),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FritzBoxPhoneOptionsFlow()


class FritzBoxPhoneOptionsFlow(config_entries.OptionsFlow):
    """Options for polling interval, call list scope and PhoneBlock spam-check."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            # The stored PhoneBlock password is never sent back to the
            # browser (so the field is empty on every visit); leaving it
            # empty therefore means "keep the current one".
            user_input = dict(user_input)
            if not user_input.get(CONF_PHONEBLOCK_PASSWORD):
                user_input[CONF_PHONEBLOCK_PASSWORD] = options.get(CONF_PHONEBLOCK_PASSWORD, "")
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
                vol.Optional(CONF_PHONEBLOCK_PASSWORD): _PASSWORD_SELECTOR,
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
