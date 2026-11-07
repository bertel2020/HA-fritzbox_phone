"""Diagnostics for the FRITZ!Box phone integration.

Deliberately free of anything personal: counts and flags instead of call
lists, phonebooks and message texts, and no credentials, host names or
phone numbers.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_PHONEBLOCK_PASSWORD, CONF_PHONEBLOCK_USERNAME
from .health import describe_error
from .runtime import FritzBoxPhoneConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    monitor = entry.runtime_data.call_monitor
    data = coordinator.data

    return {
        "entry": {
            "title": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "box": {
            "model": coordinator.client.model_name,
            "software_version": coordinator.client.software_version,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_error": (
                describe_error(coordinator.last_exception)
                if coordinator.last_exception is not None
                else None
            ),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
            "phonebooks": [
                {"id": phonebook.id, "contacts": len(phonebook.contacts)}
                for phonebook in data.phonebooks
            ],
            "calls": {
                "total": len(data.calls),
                "by_type": _count(call.type_name for call in data.calls),
                "spam": sum(1 for call in data.calls if call.is_spam),
                "linked_to_message": sum(
                    1 for call in data.calls if call.tam_message_index is not None
                ),
            },
            # Only how many calls the opt-in history holds, never the calls.
            "call_history": (
                None
                if coordinator.history is None
                else {"days": coordinator.history.days, "calls": len(coordinator.history)}
            ),
            "answering_machines": [
                {
                    "index": tam.index,
                    "enabled": tam.enabled,
                    "running": tam.running,
                    "messages": len(tam.messages),
                    "new_messages": sum(1 for message in tam.messages if message.new),
                }
                for tam in data.tams
            ],
            "lookups": {
                "phoneblock_enabled": coordinator.phoneblock is not None,
                "reverse_lookup_enabled": coordinator.tellows is not None,
                "phoneblock": (
                    coordinator.phoneblock.health.as_dict() if coordinator.phoneblock else None
                ),
                "reverse_lookup": (
                    coordinator.tellows.health.as_dict() if coordinator.tellows else None
                ),
            },
        },
        "call_monitor": (
            None
            if monitor is None
            else {
                "connected": monitor.connected,
                "state": monitor.state,
                "connection_failures": monitor.failures,
            }
        ),
    }


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
