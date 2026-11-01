"""The German texts the logbook shows for the integration's events."""
from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event
import pytest

from custom_components.fritzbox_phone import logbook
from custom_components.fritzbox_phone.const import DOMAIN


def _message(describe, **data) -> str:
    return describe(Event("x", data))[LOGBOOK_ENTRY_MESSAGE]


def test_all_events_are_registered() -> None:
    registered: list[str] = []
    logbook.async_describe_events(None, lambda domain, event, func: registered.append(event))
    assert len(registered) == 6
    assert all(event.startswith(DOMAIN) for event in registered)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"name": "Max", "number": "030"}, "Max (030)"),
        ({"reverse_name": "Shop"}, "Shop"),
        ({}, "Unbekannt"),
        ({"number": "030", "area_name": "Berlin"}, "030 (Berlin)"),
        ({"number": "030"}, "030"),
    ],
)
def test_party(data, expected) -> None:
    assert logbook._party(data) == expected


def test_spam_suffix() -> None:
    assert logbook._spam_suffix({}) == ""
    assert logbook._spam_suffix({"is_spam": True}) == " - als Spam eingestuft"
    assert "Vertrauen 90 %" in logbook._spam_suffix({"is_spam": True, "spam_confidence": 90})


def test_time_of() -> None:
    assert logbook._time_of("07.09.26 16:10") == "16:10"
    assert logbook._time_of("kaputt") == "kaputt"
    assert logbook._time_of(None) is None


def test_join() -> None:
    assert logbook._join(["a"]) == "a"
    assert logbook._join(["a", "b"]) == "a und b"
    assert logbook._join(["a", "b", "c"]) == "a, b und c"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"call_state": "ringing", "number": "030", "is_spam": True}, "Eingehender Anruf von 030 - als Spam"),
        ({"call_state": "ringing", "number": "030", "enriched": True}, "Anrufer näher bestimmt: 030"),
        ({"call_state": "dialing", "number": "030", "device": "Tel"}, "Ausgehender Anruf an 030 über Tel"),
        ({"call_state": "dialing", "number": "030"}, "Ausgehender Anruf an 030"),
        (
            {"call_state": "talking", "number": "030", "ring_duration_formatted": "0:05"},
            "Gespräch mit 030 angenommen (nach 0:05 Klingeln)",
        ),
        ({"call_state": "idle", "number": "030", "answered": True, "duration_formatted": "1:00"}, "Gespräch mit 030 beendet nach 1:00"),
        ({"call_state": "idle", "number": "030", "answered": True}, "Gespräch mit 030 beendet"),
        ({"call_state": "idle", "number": "030", "direction": "outgoing"}, "Anruf an 030 ohne Verbindung beendet"),
        ({"call_state": "idle", "number": "030"}, "Anruf von 030 nicht angenommen"),
    ],
)
def test_call_monitor_texts(data, expected) -> None:
    assert _message(logbook._describe_call, **data).startswith(expected)
    assert logbook._describe_call(Event("x", data))[LOGBOOK_ENTRY_NAME] == logbook.NAME_CALL_MONITOR


def test_call_list_entries() -> None:
    entry = {"type": "missed", "name": "Max", "number": "030", "is_answering_machine": True}
    assert _message(logbook._describe_call_list_changed, added=[entry], added_count=1) == (
        "Neuer Eintrag: Verpasster Anruf von Max (030), auf den Anrufbeantworter"
    )
    fax = {"type": "incoming", "number": "1", "is_fax": True}
    assert "(Fax)" in _message(logbook._describe_call_list_changed, added=[fax], added_count=1)
    many = _message(
        logbook._describe_call_list_changed,
        added=[{"type": "outgoing", "number": "1"}, {"number": "2"}],
        added_count=4,
        removed=1,
    )
    assert many.startswith("4 neue Einträge: Ausgehender Anruf an 1, Anruf von 2 und 2 weitere Einträge")
    assert "1 Eintrag nicht mehr in der Anrufliste" in many
    assert "2 Einträge nicht mehr" in _message(logbook._describe_call_list_changed, removed=2)
    assert _message(logbook._describe_call_list_changed) == "Anrufliste aktualisiert"


def test_missed_calls() -> None:
    one = {"name": "Max", "number": "030", "date": "07.09.26 16:10", "is_spam": True}
    text = _message(logbook._describe_missed_call, added=[one], added_count=1)
    assert text.startswith("Verpasster Anruf von Max (030) um 16:10 - als Spam")
    text = _message(
        logbook._describe_missed_call, added=[{"number": "1"}], added_count=2, removed=1
    )
    assert text == "2 verpasste Anrufe: 1 und 1 weiterer Anruf; 1 verpasster Anruf nicht mehr in der Anrufliste"
    assert _message(logbook._describe_missed_call, removed=3) == "3 verpasste Anrufe nicht mehr in der Anrufliste"
    assert _message(logbook._describe_missed_call) == "Verpasste Anrufe aktualisiert"


def test_answering_machine_messages() -> None:
    event = Event("x", {"added": [{"number": "030", "duration": "0:20"}], "added_count": 1, "tam_name": "AB"})
    result = logbook._describe_tam_message(event)
    assert result[LOGBOOK_ENTRY_NAME] == "AB"
    assert result[LOGBOOK_ENTRY_MESSAGE] == "Neue Nachricht von 030, Dauer 0:20"
    text = _message(
        logbook._describe_tam_message,
        added=[{"number": "1"}],
        added_count=3,
        removed=1,
        tam_index=2,
    )
    assert text == "3 neue Nachrichten: 1 und 2 weitere Nachrichten; 1 Nachricht nicht mehr neu (als gelesen markiert oder gelöscht)"
    event = Event("x", {"tam_index": 2})
    assert logbook._describe_tam_message(event)[LOGBOOK_ENTRY_NAME] == "Anrufbeantworter 2"
    assert "2 Nachrichten nicht mehr neu" in _message(logbook._describe_tam_message, removed=2)


def test_blocking() -> None:
    assert _message(logbook._describe_number_blocked, number="030") == "Rufnummer 030 gesperrt"
    assert "stand bereits" in _message(logbook._describe_number_blocked, number="030", already_blocked=True)
    assert _message(logbook._describe_number_unblocked, number="030") == "Sperre für Rufnummer 030 aufgehoben"
