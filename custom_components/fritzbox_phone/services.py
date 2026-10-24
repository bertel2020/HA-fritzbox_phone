"""Services of the FRITZ!Box phone integration."""
from __future__ import annotations

import re
from typing import Any

from fritzconnection.core.exceptions import FritzConnectionException
import requests
import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, service

from .const import (
    ATTR_FILENAME,
    ATTR_MESSAGE_INDEX,
    ATTR_NUMBER,
    ATTR_READ,
    DOMAIN,
    SERVICE_DELETE_MESSAGE,
    SERVICE_DIAL,
    SERVICE_DOWNLOAD_MESSAGE,
    SERVICE_HANGUP,
    SERVICE_LOOKUP_NUMBER,
    SERVICE_MARK_MESSAGE_READ,
)
from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry

# Digits plus what a dial string may contain (+, *, #, separators). Nothing
# else goes to the box.
_DIAL_NUMBER = re.compile(r"^[0-9+*#()\-/ ]{1,32}$")

_DEVICE_FIELD = {vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}


def _number(value: Any) -> str:
    value = cv.string(value).strip()
    if not _DIAL_NUMBER.match(value):
        raise vol.Invalid("not a phone number")
    return value


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[FritzBoxPhoneCoordinator]:
    """The boxes a device-targeted service call is meant for."""
    entries: list[FritzBoxPhoneConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if device_ids := call.data.get(ATTR_DEVICE_ID):
        registry = dr.async_get(hass)
        wanted: set[str] = set()
        for device_id in device_ids:
            if (device := registry.async_get(device_id)) is None:
                raise ServiceValidationError(f"Unbekanntes Gerät: {device_id}")
            wanted |= device.config_entries
        entries = [entry for entry in entries if entry.entry_id in wanted]
    elif len(entries) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="device_required"
        )
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_box")
    return [entry.runtime_data.coordinator for entry in entries]


async def _async_run(hass: HomeAssistant, coordinator: FritzBoxPhoneCoordinator, func, *args):
    try:
        return await hass.async_add_executor_job(func, *args)
    except (FritzConnectionException, requests.RequestException, OSError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="box_request_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services (once, not per config entry)."""

    for name, schema, func in (
        (
            SERVICE_MARK_MESSAGE_READ,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Optional(ATTR_READ, default=True): bool,
            },
            "async_mark_message_read",
        ),
        (
            SERVICE_DELETE_MESSAGE,
            {vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int)},
            "async_delete_message",
        ),
        (
            SERVICE_DOWNLOAD_MESSAGE,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Required(ATTR_FILENAME): str,
            },
            "async_download_message",
        ),
    ):
        service.async_register_platform_entity_service(
            hass, DOMAIN, name, entity_domain=SENSOR_DOMAIN, schema=schema, func=func
        )

    async def dial(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await _async_run(hass, coordinator, coordinator.client.dial, call.data[ATTR_NUMBER])

    async def hangup(call: ServiceCall) -> None:
        for coordinator in _coordinators(hass, call):
            await _async_run(hass, coordinator, coordinator.client.hangup)

    async def lookup_number(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinators(hass, call)[0]
        return await coordinator.async_lookup_number(call.data[ATTR_NUMBER])

    hass.services.async_register(
        DOMAIN,
        SERVICE_DIAL,
        dial,
        schema=vol.Schema({**_DEVICE_FIELD, vol.Required(ATTR_NUMBER): _number}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_HANGUP, hangup, schema=vol.Schema({**_DEVICE_FIELD})
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOOKUP_NUMBER,
        lookup_number,
        schema=vol.Schema({**_DEVICE_FIELD, vol.Required(ATTR_NUMBER): _number}),
        supports_response=SupportsResponse.ONLY,
    )
