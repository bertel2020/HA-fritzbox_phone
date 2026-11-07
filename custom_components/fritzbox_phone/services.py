"""Services of the FRITZ!Box phone integration."""
from __future__ import annotations

import re
from typing import Any

from fritzconnection.core.exceptions import FritzConnectionException
import requests
import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er, service

from .const import (
    ATTR_CONTACT_ID,
    ATTR_FILENAME,
    ATTR_MEDIA_PLAYER,
    ATTR_MESSAGE_KEY,
    ATTR_MESSAGE_INDEX,
    ATTR_NAME,
    ATTR_NUMBER,
    ATTR_NUMBER_TYPE,
    ATTR_PHONEBOOK_ID,
    ATTR_READ,
    DOMAIN,
    EVENT_NUMBER_BLOCKED,
    EVENT_NUMBER_UNBLOCKED,
    NUMBER_TYPES,
    SERVICE_ADD_CONTACT,
    SERVICE_ADD_NUMBER,
    SERVICE_BLOCK_NUMBER,
    SERVICE_DELETE_MESSAGE,
    SERVICE_DIAL,
    SERVICE_DOWNLOAD_MESSAGE,
    SERVICE_HANGUP,
    SERVICE_LOOKUP_NUMBER,
    SERVICE_MARK_MESSAGE_READ,
    SERVICE_PLAY_MESSAGE,
    SERVICE_UNBLOCK_NUMBER,
)
from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry

# Digits plus what a dial string may contain (+, *, #, separators). Nothing
# else goes to the box.
_DIAL_NUMBER = re.compile(r"^[0-9+*#()\-/ ]{1,32}$")

# The service target: devices, entities or areas (floors and labels are not
# resolved - nothing here is bound to them).
_DEVICE_FIELD = {
    vol.Optional(key): vol.All(cv.ensure_list, [cv.string])
    for key in (ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_AREA_ID)
}


def _number(value: Any) -> str:
    value = cv.string(value).strip()
    if not _DIAL_NUMBER.match(value):
        raise vol.Invalid("not a phone number")
    return value


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[FritzBoxPhoneCoordinator]:
    """The boxes a device-targeted service call is meant for."""
    entries: list[FritzBoxPhoneConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if any(call.data.get(key) for key in (ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_AREA_ID)):
        registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        wanted: set[str] = set()
        for device_id in call.data.get(ATTR_DEVICE_ID, []):
            if (device := registry.async_get(device_id)) is None:
                raise ServiceValidationError(f"Unbekanntes Gerät: {device_id}")
            wanted |= device.config_entries
        for entity_id in call.data.get(ATTR_ENTITY_ID, []):
            if (entity := entity_registry.async_get(entity_id)) is None or not entity.config_entry_id:
                raise ServiceValidationError(f"Unbekannte Entität: {entity_id}")
            wanted.add(entity.config_entry_id)
        for area_id in call.data.get(ATTR_AREA_ID, []):
            for device in dr.async_entries_for_area(registry, area_id):
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
                vol.Optional(ATTR_MESSAGE_KEY): cv.string,
                vol.Optional(ATTR_READ, default=True): bool,
            },
            "async_mark_message_read",
        ),
        (
            SERVICE_DELETE_MESSAGE,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Optional(ATTR_MESSAGE_KEY): cv.string,
            },
            "async_delete_message",
        ),
        (
            SERVICE_DOWNLOAD_MESSAGE,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Optional(ATTR_MESSAGE_KEY): cv.string,
                vol.Required(ATTR_FILENAME): str,
            },
            "async_download_message",
        ),
        (
            SERVICE_PLAY_MESSAGE,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Optional(ATTR_MESSAGE_KEY): cv.string,
                vol.Required(ATTR_MEDIA_PLAYER): cv.entity_id,
            },
            "async_play_message",
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

    def _announce(
        call: ServiceCall, coordinator: FritzBoxPhoneCoordinator, event: str, **data: Any
    ) -> None:
        # The logbook shows who blocked or released which number.
        hass.bus.async_fire(
            event,
            {
                "config_entry_id": coordinator.entry.entry_id,
                "host": coordinator.entry.data[CONF_HOST],
                **data,
            },
            context=call.context,
        )

    async def block_number(call: ServiceCall) -> None:
        number = call.data[ATTR_NUMBER]
        for coordinator in _coordinators(hass, call):
            added = await _async_run(
                hass, coordinator, coordinator.client.block_number, number, call.data.get(ATTR_NAME)
            )
            _announce(call, coordinator, EVENT_NUMBER_BLOCKED, number=number, already_blocked=not added)

    async def unblock_number(call: ServiceCall) -> None:
        number = call.data[ATTR_NUMBER]
        for coordinator in _coordinators(hass, call):
            removed = await _async_run(hass, coordinator, coordinator.client.unblock_number, number)
            if not removed:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="number_not_blocked",
                    translation_placeholders={"number": number},
                )
            _announce(call, coordinator, EVENT_NUMBER_UNBLOCKED, number=number)

    async def add_contact(call: ServiceCall) -> None:
        number, name = call.data[ATTR_NUMBER], call.data[ATTR_NAME]
        for coordinator in _coordinators(hass, call):
            if (known := coordinator.resolve_contact(number)[0]) is not None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="contact_exists",
                    translation_placeholders={"number": number, "name": known},
                )
            await _async_run(
                hass,
                coordinator,
                coordinator.client.add_contact,
                number,
                name,
                call.data[ATTR_PHONEBOOK_ID],
            )
            coordinator.invalidate_phonebooks()
            await coordinator.async_request_refresh()

    async def add_number_to_contact(call: ServiceCall) -> None:
        number = call.data[ATTR_NUMBER]
        contact_id = call.data[ATTR_CONTACT_ID]
        book_id = call.data[ATTR_PHONEBOOK_ID]
        for coordinator in _coordinators(hass, call):
            if (known := coordinator.resolve_contact(number)[0]) is not None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="contact_exists",
                    translation_placeholders={"number": number, "name": known},
                )
            books = coordinator.data.phonebooks if coordinator.data else []
            if not any(
                book.id == book_id and any(c.uniqueid == contact_id for c in book.contacts)
                for book in books
            ):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="contact_unknown",
                    translation_placeholders={"contact": contact_id},
                )
            await _async_run(
                hass,
                coordinator,
                coordinator.client.add_number_to_contact,
                contact_id,
                number,
                call.data[ATTR_NUMBER_TYPE],
                book_id,
            )
            coordinator.invalidate_phonebooks()
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_NUMBER,
        add_number_to_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_NUMBER): _number,
                vol.Required(ATTR_CONTACT_ID): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=32)),
                vol.Optional(ATTR_NUMBER_TYPE, default="home"): vol.In(NUMBER_TYPES),
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=999)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CONTACT,
        add_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_NUMBER): _number,
                vol.Required(ATTR_NAME): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=64)),
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=999)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BLOCK_NUMBER,
        block_number,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_NUMBER): _number,
                vol.Optional(ATTR_NAME): vol.All(cv.string, vol.Length(max=64)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNBLOCK_NUMBER,
        unblock_number,
        schema=vol.Schema({**_DEVICE_FIELD, vol.Required(ATTR_NUMBER): _number}),
    )
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
