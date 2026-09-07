"""Logbook descriptions for the FRITZ!Box phone integration.

Home Assistant fills the "Was ist passiert" field of an activity by
resolving the Context of a state change: it looks for a logbook entry
sharing that context and shows its message. Without one, the frontend
falls back to "Für diese Aktivität wurde kein Grund festgehalten".

The entities therefore fire an event before every notable state change
and adopt its Context (see sensor.py / coordinator.py); this platform
turns those events back into German plain text.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    CALLMONITOR_STATE_DIALING,
    CALLMONITOR_STATE_RINGING,
    CALLMONITOR_STATE_TALKING,
    DOMAIN,
    EVENT_CALL,
    EVENT_CALL_LIST_CHANGED,
    EVENT_MISSED_CALL,
    EVENT_TAM_MESSAGE,
)

NAME_CALL_MONITOR = "Anrufmonitor"
NAME_CALL_LIST = "Anrufliste"
NAME_MISSED_CALLS = "Verpasste Anrufe"
NAME_TAM = "Anrufbeantworter"

# CallEntry.type_name (see CALL_TYPE_NAMES) in German, for call list entries.
CALL_TYPE_LABELS = {
    "incoming": "Eingehender Anruf von",
    "missed": "Verpasster Anruf von",
    "outgoing": "Ausgehender Anruf an",
    "active_incoming": "Laufender eingehender Anruf von",
    "rejected_incoming": "Abgewiesener Anruf von",
    "active_outgoing": "Laufender ausgehender Anruf an",
}

_DATE_FORMAT_IN = "%d.%m.%y %H:%M"


def _party(data: dict[str, Any]) -> str:
    """The other end of a call: name plus number where both are known.

    Falls back to the number alone (with its offline-geocoded area name,
    if any) and finally to "Unbekannt" for suppressed numbers.
    """
    name = data.get("name") or data.get("reverse_name")
    number = data.get("number")
    if name and number:
        return f"{name} ({number})"
    if name:
        return name
    if not number:
        return "Unbekannt"
    if area := data.get("area_name"):
        return f"{number} ({area})"
    return number


def _spam_suffix(data: dict[str, Any]) -> str:
    """Spam verdict as a trailing clause - usually the whole point of the
    logbook entry for an unknown caller."""
    if not data.get("is_spam"):
        return ""
    if (confidence := data.get("spam_confidence")) is not None:
        return f" - als Spam eingestuft (Vertrauen {confidence} %)"
    return " - als Spam eingestuft"


def _time_of(raw: str | None) -> str | None:
    """"16:10" out of the box's "07.09.26 16:10" call list timestamp."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _DATE_FORMAT_IN).strftime("%H:%M")
    except ValueError:
        return raw


def _describe_call_entry(entry: dict[str, Any]) -> str:
    """One call list entry, e.g. "Verpasster Anruf von Max (+49...)"."""
    label = CALL_TYPE_LABELS.get(entry.get("type"), "Anruf von")
    text = f"{label} {_party(entry)}"
    if entry.get("is_answering_machine"):
        text += ", auf den Anrufbeantworter"
    elif entry.get("is_fax"):
        text += " (Fax)"
    return text + _spam_suffix(entry)


def _join(parts: list[str]) -> str:
    """Human list: "A", "A und B", "A, B und C"."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " und " + parts[-1]


def _listing(
    added: list[dict[str, Any]],
    count: int,
    render: Callable[[dict[str, Any]], str],
    more: tuple[str, str],
) -> str:
    """List the entries the event carries, naming the rest by number -
    the coordinator caps how many travel inside one event. `more` holds
    the singular/plural wording for that remainder."""
    parts = [render(entry) for entry in added]
    if (rest := count - len(parts)) > 0:
        parts.append(more[0] if rest == 1 else more[1].format(rest))
    return _join(parts)


@callback
def _describe_call(event: Event) -> dict[str, str]:
    """A live CallMonitor state change (ringing/dialing/talking/idle)."""
    data = event.data
    state = data.get("call_state")
    party = _party(data)
    spam = _spam_suffix(data)

    if state == CALLMONITOR_STATE_RINGING:
        message = f"Eingehender Anruf von {party}{spam}"
    elif state == CALLMONITOR_STATE_DIALING:
        message = f"Ausgehender Anruf an {party}"
        if device := data.get("device"):
            message += f" über {device}"
    elif state == CALLMONITOR_STATE_TALKING:
        message = f"Gespräch mit {party} angenommen"
        if ringing := data.get("ring_duration_formatted"):
            message += f" (nach {ringing} Klingeln)"
        message += spam
    elif data.get("answered"):
        message = f"Gespräch mit {party} beendet"
        if duration := data.get("duration_formatted"):
            message += f" nach {duration}"
    elif data.get("direction") == "outgoing":
        message = f"Anruf an {party} ohne Verbindung beendet"
    else:
        message = f"Anruf von {party} nicht angenommen{spam}"

    return {LOGBOOK_ENTRY_NAME: NAME_CALL_MONITOR, LOGBOOK_ENTRY_MESSAGE: message}


@callback
def _describe_call_list_changed(event: Event) -> dict[str, str]:
    """Entries appearing in or dropping out of the polled call list."""
    added: list[dict[str, Any]] = event.data.get("added", [])
    count: int = event.data.get("added_count", len(added))
    removed: int = event.data.get("removed", 0)
    messages: list[str] = []

    if count == 1 and added:
        messages.append(f"Neuer Eintrag: {_describe_call_entry(added[0])}")
    elif count:
        listed = _listing(
            added, count, _describe_call_entry, ("1 weiterer Eintrag", "{} weitere Einträge")
        )
        messages.append(f"{count} neue Einträge: {listed}")
    if removed:
        noun = "Eintrag" if removed == 1 else "Einträge"
        messages.append(
            f"{removed} {noun} nicht mehr in der Anrufliste (außerhalb des "
            "Zeitfensters oder auf der FRITZ!Box gelöscht)"
        )

    return {
        LOGBOOK_ENTRY_NAME: NAME_CALL_LIST,
        LOGBOOK_ENTRY_MESSAGE: "; ".join(messages) or "Anrufliste aktualisiert",
    }


@callback
def _describe_missed_call(event: Event) -> dict[str, str]:
    """Missed calls appearing in or dropping out of the call list."""
    added: list[dict[str, Any]] = event.data.get("added", [])
    count: int = event.data.get("added_count", len(added))
    removed: int = event.data.get("removed", 0)
    messages: list[str] = []

    if count == 1 and added:
        entry = added[0]
        text = f"Verpasster Anruf von {_party(entry)}"
        if time := _time_of(entry.get("date")):
            text += f" um {time}"
        messages.append(text + _spam_suffix(entry))
    elif count:
        listed = _listing(
            added,
            count,
            lambda entry: _party(entry) + _spam_suffix(entry),
            ("1 weiterer Anruf", "{} weitere Anrufe"),
        )
        messages.append(f"{count} verpasste Anrufe: {listed}")
    if removed == 1:
        messages.append("1 verpasster Anruf nicht mehr in der Anrufliste")
    elif removed:
        messages.append(f"{removed} verpasste Anrufe nicht mehr in der Anrufliste")

    return {
        LOGBOOK_ENTRY_NAME: NAME_MISSED_CALLS,
        LOGBOOK_ENTRY_MESSAGE: "; ".join(messages) or "Verpasste Anrufe aktualisiert",
    }


@callback
def _describe_tam_message(event: Event) -> dict[str, str]:
    """New (or no longer new) answering machine recordings."""
    data = event.data
    added: list[dict[str, Any]] = data.get("added", [])
    count: int = data.get("added_count", len(added))
    removed: int = data.get("removed", 0)
    tam_name = data.get("tam_name") or f"{NAME_TAM} {data.get('tam_index')}"
    messages: list[str] = []

    if count == 1 and added:
        entry = added[0]
        text = f"Neue Nachricht von {_party(entry)}"
        if duration := entry.get("duration"):
            text += f", Dauer {duration}"
        messages.append(text + _spam_suffix(entry))
    elif count:
        listed = _listing(
            added,
            count,
            lambda entry: _party(entry) + _spam_suffix(entry),
            ("1 weitere Nachricht", "{} weitere Nachrichten"),
        )
        messages.append(f"{count} neue Nachrichten: {listed}")
    if removed:
        noun = "Nachricht" if removed == 1 else "Nachrichten"
        messages.append(
            f"{removed} {noun} nicht mehr neu (als gelesen markiert oder gelöscht)"
        )

    return {
        LOGBOOK_ENTRY_NAME: tam_name,
        LOGBOOK_ENTRY_MESSAGE: "; ".join(messages) or "Anrufbeantworter aktualisiert",
    }


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Register the integration's events with the logbook."""
    async_describe_event(DOMAIN, EVENT_CALL, _describe_call)
    async_describe_event(DOMAIN, EVENT_CALL_LIST_CHANGED, _describe_call_list_changed)
    async_describe_event(DOMAIN, EVENT_MISSED_CALL, _describe_missed_call)
    async_describe_event(DOMAIN, EVENT_TAM_MESSAGE, _describe_tam_message)
