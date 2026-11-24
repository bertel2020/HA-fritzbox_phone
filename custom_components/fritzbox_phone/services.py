"""Services of the FRITZ!Box phone integration."""
from __future__ import annotations

import logging
import re
from typing import Any

from fritzconnection.core.exceptions import FritzConnectionException
import requests
import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import CONF_HOST
from homeassistant.core import HassJob, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.event import async_call_later

from .api import internal_number_for, redact
from .const import (
    ATTR_CONTACT_ID,
    ATTR_EMAILS,
    ATTR_MEDIA_PLAYER,
    ATTR_MESSAGE_KEY,
    ATTR_MESSAGE_INDEX,
    ATTR_NAME,
    ATTR_MAX_RING_SECONDS,
    ATTR_MINUTES,
    ATTR_NUMBER,
    ATTR_PHONE,
    ATTR_TARGET_PHONE,
    ATTR_NUMBER_TYPE,
    ATTR_NUMBERS,
    ATTR_PHONEBOOK_ID,
    ATTR_READ,
    ATTR_VIP,
    DOMAIN,
    EVENT_NUMBER_BLOCKED,
    EVENT_NUMBER_UNBLOCKED,
    NUMBER_TYPES,
    SERVICE_ADD_CONTACT,
    SERVICE_ADD_NUMBER,
    SERVICE_BLOCK_NUMBER,
    SERVICE_DELETE_CONTACT,
    SERVICE_DELETE_MESSAGE,
    SERVICE_CALL_PHONE,
    SERVICE_DIAL,
    SERVICE_HANGUP,
    SERVICE_LOOKUP_NUMBER,
    SERVICE_PROBE_PHONES,
    SERVICE_MARK_MESSAGE_READ,
    SERVICE_PLAY_MESSAGE,
    SERVICE_TURN_ON_FOR,
    SERVICE_UNBLOCK_NUMBER,
    SERVICE_UPDATE_CONTACT,
)
from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry

_LOGGER = logging.getLogger(__name__)

# Digits plus what a dial string may contain (+, *, #, separators). Nothing
# else goes to the box.
_DIAL_NUMBER = re.compile(r"^[0-9+*#()\-/ ]{1,32}$")

# The service target as the target picker offers it: devices, entities,
# areas, floors and labels.
_DEVICE_FIELD = cv.TARGET_SERVICE_FIELDS


def _number(value: Any) -> str:
    value = cv.string(value).strip()
    if not _DIAL_NUMBER.match(value):
        raise vol.Invalid("not a phone number")
    return value


def _contact_number(value: Any) -> tuple[str, str]:
    """One number of a contact: {number, type} -> (number, type)."""
    if not isinstance(value, dict):
        raise vol.Invalid("expected number and type")
    kind = value.get("type", "home")
    # the box has more types than the ones offered (intern, fax_home, ...): a stored one stays
    if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,16}", kind):
        raise vol.Invalid("unknown number type")
    return _number(value.get("number")), kind


_NUMBERS = vol.All(cv.ensure_list, [_contact_number], vol.Length(max=10))
_EMAILS = vol.All(
    cv.ensure_list, [vol.All(cv.string, vol.Strip, vol.Length(min=3, max=128))], vol.Length(max=10)
)
_CONTACT_NAME = vol.All(cv.string, vol.Strip, vol.Length(min=1, max=64))
_CONTACT_ID = vol.All(cv.string, vol.Strip, vol.Length(min=1, max=32))
_BOOK_ID = vol.All(vol.Coerce(int), vol.Range(min=0, max=999))


async def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[FritzBoxPhoneCoordinator]:
    """The boxes a device-targeted service call is meant for."""
    entries: list[FritzBoxPhoneConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    targeted = any(
        call.data.get(key) not in (None, "none", [])
        for key in ("entity_id", "device_id", "area_id", "floor_id", "label_id")
    )
    if targeted:
        wanted = await service.async_extract_config_entry_ids(call)
        entries = [entry for entry in entries if entry.entry_id in wanted]
    elif len(entries) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_required",
            translation_placeholders={"boxes": ", ".join(entry.title for entry in entries)},
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
            translation_placeholders={"error": redact(err)},
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

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_TURN_ON_FOR,
        entity_domain=SWITCH_DOMAIN,
        schema={vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))},
        func="async_turn_on_for",
    )

    async def _start_call(
        coordinator: FritzBoxPhoneCoordinator,
        number: str,
        phone: str | None,
        seconds: int | None,
    ) -> None:
        if phone is not None and phone in coordinator.hidden_phones:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="hidden_phone",
                translation_placeholders={"phone": phone},
            )
        try:
            await _async_run(
                hass,
                coordinator,
                coordinator.client.dial,
                *((number, phone) if phone is not None else (number,)),
            )
        except ValueError as err:  # a phone the dial help does not know
            raise ServiceValidationError(str(err)) from err
        if seconds is not None:
            # Like fritz.dial: cancel the call setup if nobody picked up in time.
            async def _hangup(_now, coordinator=coordinator) -> None:
                try:
                    await _async_run(hass, coordinator, coordinator.client.hangup)
                except HomeAssistantError as err:
                    _LOGGER.warning("Hanging up after %s seconds failed: %s", seconds, err)

            async_call_later(hass, seconds, HassJob(_hangup, cancel_on_shutdown=True))

    async def dial(call: ServiceCall) -> None:
        for coordinator in await _coordinators(hass, call):
            await _start_call(
                coordinator,
                call.data[ATTR_NUMBER],
                call.data.get(ATTR_PHONE),
                call.data.get(ATTR_MAX_RING_SECONDS),
            )

    async def call_phone(call: ServiceCall) -> None:
        for coordinator in await _coordinators(hass, call):
            number = internal_number_for(coordinator.data.phones, call.data[ATTR_TARGET_PHONE])
            if number is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_target_phone",
                    translation_placeholders={"phone": call.data[ATTR_TARGET_PHONE]},
                )
            await _start_call(
                coordinator,
                number,
                call.data.get(ATTR_PHONE),
                call.data.get(ATTR_MAX_RING_SECONDS),
            )

    async def hangup(call: ServiceCall) -> None:
        for coordinator in await _coordinators(hass, call):
            await _async_run(hass, coordinator, coordinator.client.hangup)

    async def lookup_number(call: ServiceCall) -> dict[str, Any]:
        coordinator = (await _coordinators(hass, call))[0]
        return await coordinator.async_lookup_number(call.data[ATTR_NUMBER])

    async def probe_phones(call: ServiceCall) -> dict[str, Any]:
        coordinator = (await _coordinators(hass, call))[0]
        return await _async_run(hass, coordinator, coordinator.client.probe_phones)

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
        for coordinator in await _coordinators(hass, call):
            added = await _async_run(
                hass, coordinator, coordinator.client.block_number, number, call.data.get(ATTR_NAME)
            )
            _announce(call, coordinator, EVENT_NUMBER_BLOCKED, number=number, already_blocked=not added)
            coordinator.invalidate_blocked()
            await coordinator.async_request_refresh()

    async def unblock_number(call: ServiceCall) -> None:
        number = call.data[ATTR_NUMBER]
        for coordinator in await _coordinators(hass, call):
            removed = await _async_run(hass, coordinator, coordinator.client.unblock_number, number)
            if not removed:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="number_not_blocked",
                    translation_placeholders={"number": number},
                )
            _announce(call, coordinator, EVENT_NUMBER_UNBLOCKED, number=number)
            coordinator.invalidate_blocked()
            await coordinator.async_request_refresh()

    def _check_new_numbers(coordinator: FritzBoxPhoneCoordinator, numbers: list[str]) -> None:
        for number in numbers:
            if (known := coordinator.resolve_contact(number)[0]) is not None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="contact_exists",
                    translation_placeholders={"number": number, "name": known},
                )

    async def _contact_done(coordinator: FritzBoxPhoneCoordinator) -> None:
        coordinator.invalidate_phonebooks()
        await coordinator.async_request_refresh()

    async def add_contact(call: ServiceCall) -> None:
        numbers = list(call.data.get(ATTR_NUMBERS) or [])
        if (single := call.data.get(ATTR_NUMBER)) and not numbers:
            numbers = [(single, "home")]
        if not numbers:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="contact_no_number"
            )
        for coordinator in await _coordinators(hass, call):
            _check_new_numbers(coordinator, [number for number, _ in numbers])
            await _async_run(
                hass,
                coordinator,
                coordinator.client.add_contact,
                numbers[0][0],
                call.data[ATTR_NAME],
                call.data[ATTR_PHONEBOOK_ID],
                numbers,
                call.data[ATTR_EMAILS],
                call.data[ATTR_VIP],
            )
            await _contact_done(coordinator)

    async def add_number_to_contact(call: ServiceCall) -> None:
        number = call.data[ATTR_NUMBER]
        for coordinator in await _coordinators(hass, call):
            _check_new_numbers(coordinator, [number])
            # The box is asked for the entry itself, not for the polled copy: a contact made a
            # moment ago on the box's own pages is not in that copy yet.
            await _async_run(
                hass,
                coordinator,
                coordinator.client.add_number_to_contact,
                call.data[ATTR_CONTACT_ID],
                number,
                call.data[ATTR_NUMBER_TYPE],
                call.data[ATTR_PHONEBOOK_ID],
            )
            await _contact_done(coordinator)

    async def _require_admin(call: ServiceCall) -> None:
        """Changing or deleting a contact is for administrators; automations (no user) pass."""
        if call.context.user_id is None:
            return
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=call.context, permission="admin")

    async def update_contact(call: ServiceCall) -> None:
        await _require_admin(call)
        for coordinator in await _coordinators(hass, call):
            await _async_run(
                hass,
                coordinator,
                coordinator.client.update_contact,
                call.data[ATTR_CONTACT_ID],
                call.data[ATTR_NAME],
                call.data[ATTR_NUMBERS],
                call.data[ATTR_EMAILS],
                call.data[ATTR_VIP],
                call.data[ATTR_PHONEBOOK_ID],
            )
            await _contact_done(coordinator)

    async def delete_contact(call: ServiceCall) -> None:
        await _require_admin(call)
        for coordinator in await _coordinators(hass, call):
            await _async_run(
                hass,
                coordinator,
                coordinator.client.delete_contact,
                call.data[ATTR_CONTACT_ID],
                call.data[ATTR_PHONEBOOK_ID],
            )
            await _contact_done(coordinator)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CONTACT,
        add_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Optional(ATTR_NUMBER): _number,
                vol.Optional(ATTR_NUMBERS): _NUMBERS,
                vol.Required(ATTR_NAME): _CONTACT_NAME,
                vol.Optional(ATTR_EMAILS, default=list): _EMAILS,
                vol.Optional(ATTR_VIP, default=False): cv.boolean,
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): _BOOK_ID,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_NUMBER,
        add_number_to_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_NUMBER): _number,
                vol.Required(ATTR_CONTACT_ID): _CONTACT_ID,
                vol.Optional(ATTR_NUMBER_TYPE, default="home"): vol.In(NUMBER_TYPES),
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): _BOOK_ID,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_CONTACT,
        update_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_CONTACT_ID): _CONTACT_ID,
                vol.Required(ATTR_NAME): _CONTACT_NAME,
                vol.Required(ATTR_NUMBERS): vol.All(_NUMBERS, vol.Length(min=1)),
                vol.Optional(ATTR_EMAILS, default=list): _EMAILS,
                vol.Optional(ATTR_VIP, default=False): cv.boolean,
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): _BOOK_ID,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_CONTACT,
        delete_contact,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_CONTACT_ID): _CONTACT_ID,
                vol.Optional(ATTR_PHONEBOOK_ID, default=0): _BOOK_ID,
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
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_NUMBER): _number,
                vol.Optional(ATTR_PHONE): cv.string,
                vol.Optional(ATTR_MAX_RING_SECONDS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALL_PHONE,
        call_phone,
        schema=vol.Schema(
            {
                **_DEVICE_FIELD,
                vol.Required(ATTR_TARGET_PHONE): cv.string,
                vol.Optional(ATTR_PHONE): cv.string,
                vol.Optional(ATTR_MAX_RING_SECONDS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_HANGUP, hangup, schema=vol.Schema({**_DEVICE_FIELD})
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE_PHONES,
        probe_phones,
        schema=vol.Schema({**_DEVICE_FIELD}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOOKUP_NUMBER,
        lookup_number,
        schema=vol.Schema({**_DEVICE_FIELD, vol.Required(ATTR_NUMBER): _number}),
        supports_response=SupportsResponse.ONLY,
    )
