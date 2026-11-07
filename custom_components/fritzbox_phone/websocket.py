"""Websocket commands: a stable, documented read API for panels.

The dashboard card reads entity attributes; a panel (for instance the
"Box > Telefon" page of the fritzbox_network integration) uses these
commands instead, so that it does not depend on entity ids or attribute
names. All commands are for administrators only. They answer with the
real names and numbers; `privacy_mode` is passed along for the panel to
follow, exactly like the card does with the attribute of the same name.

Errors: `not_found` for an unknown or not loaded entry (or an unknown
phonebook), `unauthorized` for a non-admin user, `box_request_failed`
when the FRITZ!Box did not answer. Names and numbers never go to the log.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from fritzconnection.core.exceptions import FritzConnectionException
import requests
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .api import UNSUPPORTED_ERRORS
from .const import (
    CONF_CALL_HISTORY_DAYS,
    CONF_CALL_LIST_DAYS,
    CONF_CALL_LIST_MAX,
    CONF_PRIVACY_MODE,
    DEFAULT_CALL_HISTORY_DAYS,
    DEFAULT_CALL_LIST_DAYS,
    DEFAULT_CALL_LIST_MAX,
    DEFAULT_PRIVACY_MODE,
    DOMAIN,
)
from .coordinator import FritzBoxPhoneCoordinator
from .history import SOURCE_HISTORY, SOURCE_LIST, compute_stats, sort_newest_first
from .payloads import (
    call_record,
    contact_to_dict,
    counterpart_number,
    message_id,
    message_to_dict,
)

_LOGGER = logging.getLogger(__name__)

ERR_BOX_REQUEST_FAILED = "box_request_failed"
STATS_DAYS = (7, 30, 90, 365, 0)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the commands (once for the domain)."""
    for command in (
        ws_entries,
        ws_phonebooks,
        ws_contacts,
        ws_calls,
        ws_tams,
        ws_blocklist,
        ws_stats,
    ):
        websocket_api.async_register_command(hass, command)


def _options(entry: ConfigEntry) -> dict[str, Any]:
    options = entry.options
    return {
        "call_list_days": options.get(CONF_CALL_LIST_DAYS, DEFAULT_CALL_LIST_DAYS),
        "call_list_max": options.get(CONF_CALL_LIST_MAX, DEFAULT_CALL_LIST_MAX),
        "privacy_mode": bool(options.get(CONF_PRIVACY_MODE, DEFAULT_PRIVACY_MODE)),
        "history_days": int(options.get(CONF_CALL_HISTORY_DAYS, DEFAULT_CALL_HISTORY_DAYS)),
    }


def _coordinator(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> FritzBoxPhoneCoordinator | None:
    """The coordinator of a loaded entry, or None after sending `not_found`."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
        or entry.runtime_data.coordinator.data is None
    ):
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Entry not found or not loaded"
        )
        return None
    return entry.runtime_data.coordinator


def _with_vip(coordinator: FritzBoxPhoneCoordinator, record: dict[str, Any]) -> dict[str, Any]:
    number = counterpart_number(record)
    return record | {"vip": bool(number) and coordinator.resolve_contact(number)[1]}


def _call_records(
    coordinator: FritzBoxPhoneCoordinator, use_history: bool
) -> tuple[list[dict[str, Any]], str]:
    """The calls of the chosen source, newest first, with `vip` and `in_list`.

    History entries that have left the box's list keep their last known
    data; their recording is gone from the list, so `has_recording` is
    false for them.
    """
    live = [call_record(call) for call in coordinator.data.calls]
    if use_history and coordinator.history is not None:
        live_ids = {record["id"] for record in live}
        merged = {record["id"]: record for record in coordinator.history.records()}
        merged.update({record["id"]: record for record in live})
        records = [
            record
            if record["id"] in live_ids
            else record | {"has_recording": False, "tam_message_index": None}
            for record in merged.values()
        ]
        source = SOURCE_HISTORY
    else:
        live_ids = {record["id"] for record in live}
        records = live
        source = SOURCE_LIST
    return [
        _with_vip(coordinator, record) | {"in_list": record["id"] in live_ids}
        for record in sort_newest_first(records)
    ], source


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/entries"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_entries(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """All config entries of the integration, loaded or not."""
    version = str((await async_get_integration(hass, DOMAIN)).version or "")
    entries = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        loaded = entry.state is ConfigEntryState.LOADED
        serial = None
        if loaded:
            serial = entry.runtime_data.coordinator.client.serial_number
        if serial is None and entry.unique_id and entry.unique_id != entry.data.get(CONF_HOST):
            # Set from the serial number at setup (the host only as a fallback).
            serial = entry.unique_id
        entries.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "host": entry.data.get(CONF_HOST),
                "serial": serial,
                "loaded": loaded,
                **_options(entry),
                "version": version,
            }
        )
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/phonebooks", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_phonebooks(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The phonebooks of a box; `id` is what `add_contact` takes as `phonebook_id`."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    connection.send_result(
        msg["id"],
        {
            "phonebooks": [
                {"id": phonebook.id, "name": phonebook.name, "count": len(phonebook.contacts)}
                for phonebook in coordinator.data.phonebooks
            ],
            "privacy_mode": _options(coordinator.entry)["privacy_mode"],
        },
    )


def _matches(contact: dict[str, Any], query: str) -> bool:
    text = query.casefold()
    if text in contact["name"].casefold():
        return True
    digits = "".join(ch for ch in query if ch.isdigit())
    return bool(digits) and any(
        digits in "".join(ch for ch in number["number"] if ch.isdigit())
        for number in contact["numbers"]
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/contacts",
        vol.Required("entry_id"): str,
        vol.Required("phonebook_id"): vol.Coerce(int),
        vol.Optional("query"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_contacts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The contacts of one phonebook, optionally filtered by name or digits."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    phonebook = next(
        (pb for pb in coordinator.data.phonebooks if pb.id == msg["phonebook_id"]), None
    )
    if phonebook is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Phonebook not found")
        return
    contacts = [contact_to_dict(contact) for contact in phonebook.contacts]
    if query := (msg.get("query") or "").strip():
        contacts = [contact for contact in contacts if _matches(contact, query)]
    connection.send_result(
        msg["id"],
        {"contacts": contacts, "privacy_mode": _options(coordinator.entry)["privacy_mode"]},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/calls",
        vol.Required("entry_id"): str,
        vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3650)),
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100000)),
        vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)
@websocket_api.require_admin
@callback
def ws_calls(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Calls, newest first.

    `days` and `limit` default to the call list window of the options
    (0 = no limit). With the call history switched on, a request for all
    days (0) or for more days than the call list holds is answered from the
    history; otherwise from the live call list.
    """
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    options = _options(coordinator.entry)
    list_days = options["call_list_days"]
    days = msg.get("days")
    use_history = (
        days is not None
        and coordinator.history is not None
        and (days == 0 or (list_days != 0 and days > list_days))
    )
    if days is None:
        days = list_days
    limit = msg.get("limit", options["call_list_max"])
    records, source = _call_records(coordinator, use_history)
    held_oldest = next(
        (record["datetime"] for record in reversed(records) if record.get("datetime")), None
    )
    if days:
        cutoff = dt_util.now() - timedelta(days=days)
        records = [
            record
            for record in records
            if (started := record.get("datetime")) and dt_util.parse_datetime(started) >= cutoff
        ]
    total = len(records)
    offset = msg["offset"]
    page = records[offset : offset + limit] if limit else records[offset:]
    connection.send_result(
        msg["id"],
        {
            "calls": page,
            "window": {
                "days": days,
                "max": limit,
                "offset": offset,
                "oldest": held_oldest,
                "source": source,
            },
            "total": total,
            "privacy_mode": options["privacy_mode"],
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/tams", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_tams(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The answering machines with their messages (as the sensor lists them)."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    entry_id = coordinator.entry.entry_id
    tams = []
    for tam in coordinator.data.tams:
        messages = []
        for message in tam.messages:
            key = coordinator.message_key(message)
            messages.append(
                message_to_dict(entry_id, tam.index, message, key)
                | {"tam_index": tam.index, "id": message_id(tam.index, key)}
            )
        tams.append(
            {
                "index": tam.index,
                "name": tam.name,
                "enabled": tam.enabled,
                "running": tam.running,
                "capacity_minutes_remaining": tam.capacity_minutes,
                "new_count": sum(1 for message in tam.messages if message.new),
                "total": len(tam.messages),
                "messages": messages,
            }
        )
    connection.send_result(
        msg["id"], {"tams": tams, "privacy_mode": _options(coordinator.entry)["privacy_mode"]}
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/blocklist", vol.Required("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_blocklist(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """The numbers of the box's call barring list, read from the box on each call."""
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    try:
        blocked = await hass.async_add_executor_job(coordinator.client.get_blocked_numbers)
    except UNSUPPORTED_ERRORS as err:
        # A box (or a box user) without call barring.
        _LOGGER.debug("Rufsperre nicht lesbar: %s", type(err).__name__)
        connection.send_result(msg["id"], {"numbers": [], "entries": [], "supported": False})
        return
    except (FritzConnectionException, requests.RequestException, OSError) as err:
        connection.send_error(msg["id"], ERR_BOX_REQUEST_FAILED, type(err).__name__)
        return
    connection.send_result(
        msg["id"],
        {
            "numbers": [number.number for contact in blocked for number in contact.numbers],
            "entries": [
                {
                    "uniqueid": contact.uniqueid,
                    "name": contact.name,
                    "numbers": [number.number for number in contact.numbers],
                }
                for contact in blocked
            ],
            "supported": True,
            "privacy_mode": _options(coordinator.entry)["privacy_mode"],
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stats",
        vol.Required("entry_id"): str,
        vol.Optional("days", default=7): vol.All(vol.Coerce(int), vol.Range(min=0, max=3650)),
    }
)
@websocket_api.require_admin
@callback
def ws_stats(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Statistics over the last `days` calendar days (0 = everything held).

    Computed from the call history when it is switched on, else from the
    live call list.
    """
    if (coordinator := _coordinator(hass, connection, msg)) is None:
        return
    records, source = _call_records(coordinator, coordinator.history is not None)
    result = compute_stats(records, msg["days"], dt_util.now(), source)
    result["privacy_mode"] = _options(coordinator.entry)["privacy_mode"]
    connection.send_result(msg["id"], result)
