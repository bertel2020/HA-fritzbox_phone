"""The shapes in which calls, messages and contacts leave the integration.

Shared by the entity attributes (sensor.py), the call history store
(history.py) and the websocket commands (websocket.py), so that the
dashboard card and the panel see the same fields.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any

from homeassistant.util import dt as dt_util

from .api import CallEntry, PhonebookContact, TamMessage
from .views import recording_path

AVM_DATE_FORMAT = "%d.%m.%y %H:%M"
OUTGOING_TYPES = frozenset({"outgoing", "active_outgoing"})


def parse_avm_date(text: str | None) -> datetime | None:
    """A date as the box prints it ("07.09.26 16:10"), in Home Assistant's time zone."""
    try:
        naive = datetime.strptime((text or "").strip(), AVM_DATE_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=dt_util.get_default_time_zone())


def _short_hash(basis: str) -> str:
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def stable_call_id(call: CallEntry) -> str:
    """An id that stays the same for a call across polls, restarts and list resets.

    The box numbers its call list entries (``Id``), and that number belongs
    to the same call while the call stays in the list - also while an
    ``active_*`` entry turns into its final one. Together with the start
    time it stays unique after the list was cleared and the numbering began
    again. Entries without a box id fall back to what describes the call.
    """
    if call.id:
        return _short_hash(f"id|{call.id}|{call.date or ''}")
    return _short_hash(
        "|".join(
            (
                "call",
                call.date or "",
                call.caller_number or call.caller or "",
                call.called_number or call.called or "",
                call.duration or "",
                str(call.type),
            )
        )
    )


def message_id(tam_index: int, message_key: str) -> str:
    """A stable id for an answering machine message (the box renumbers them)."""
    return _short_hash(f"msg|{tam_index}|{message_key}")


def call_to_dict(call: CallEntry) -> dict[str, Any]:
    """A call as the call list sensors show it in their attributes."""
    return {
        "id": call.id,
        "type": call.type_name,
        "name": call.name,
        "caller": call.caller,
        "caller_number": call.caller_number,
        "called": call.called,
        "called_number": call.called_number,
        "device": call.device,
        "port": call.port,
        "date": call.date,
        "duration": call.duration,
        "is_fax": call.is_fax,
        "is_answering_machine": call.is_tam,
        # The recording itself is delivered by views.py; the box's session
        # id (part of the raw URL) must not end up in the state machine.
        "has_recording": call.recording_url is not None,
        "tam_index": call.tam_index,
        "tam_message_index": call.tam_message_index,
        "area_name": call.area_name,
        "is_spam": call.is_spam,
        "spam_confidence": call.spam_confidence,
        "spam_rating": call.spam_rating,
        "spam_location": call.spam_location,
        "reverse_name": call.reverse_name,
        "reverse_category": call.reverse_category,
    }


def call_record(call: CallEntry) -> dict[str, Any]:
    """A call as the websocket API and the history store keep it.

    ``id`` is the stable id (see stable_call_id); the box's own entry number
    moves to ``box_id``. ``datetime`` is the start time in ISO 8601 with the
    offset of Home Assistant's time zone, None if the box gave no readable
    date.
    """
    started = parse_avm_date(call.date)
    return call_to_dict(call) | {
        "id": stable_call_id(call),
        "box_id": call.id or None,
        "datetime": started.isoformat() if started else None,
    }


def counterpart_number(record: dict[str, Any]) -> str | None:
    """The other side of a call, direction-aware."""
    if record.get("type") in OUTGOING_TYPES:
        return record.get("called_number") or record.get("called")
    return record.get("caller_number") or record.get("caller")


def own_number(record: dict[str, Any]) -> str | None:
    """The box's own number a call used, direction-aware."""
    if record.get("type") in OUTGOING_TYPES:
        return record.get("caller_number") or record.get("caller")
    return record.get("called_number") or record.get("called")


def message_to_dict(entry_id: str, tam_index: int, message: TamMessage, key: str) -> dict[str, Any]:
    """An answering machine message as the answering machine sensor lists it."""
    return {
        "index": message.index,
        "name": message.name,
        "number": message.number,
        "called": message.called,
        "date": message.date,
        "key": key,
        "duration": message.duration,
        "new": message.new,
        "in_phonebook": message.inbook,
        "has_recording": message.download_url is not None,
        "recording_path": (
            recording_path(entry_id, tam_index, message.index, key)
            if message.download_url
            else None
        ),
        "area_name": message.area_name,
        "is_spam": message.is_spam,
        "spam_confidence": message.spam_confidence,
        "spam_rating": message.spam_rating,
        "spam_location": message.spam_location,
        "reverse_name": message.reverse_name,
        "reverse_category": message.reverse_category,
    }


def contact_to_dict(contact: PhonebookContact) -> dict[str, Any]:
    """A phonebook contact as the phonebook sensor lists it."""
    return {
        "name": contact.name,
        "vip": contact.vip,
        "uniqueid": contact.uniqueid,
        "has_image": contact.image_url is not None,
        "numbers": [{"number": number.number, "type": number.type} for number in contact.numbers],
    }
