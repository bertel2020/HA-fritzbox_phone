"""The opt-in call history and the statistics computed from it."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.fritzbox_phone.const import (
    CONF_CALL_HISTORY_DAYS,
    CONF_CALL_LIST_DAYS,
    DOMAIN,
)
from custom_components.fritzbox_phone.history import CallHistory, compute_stats, storage_key
from custom_components.fritzbox_phone.payloads import call_record, stable_call_id

from .common import FakeBox, build_client_class, get_coordinator, make_call, setup_integration

NOW = "2026-01-10T11:00:00+00:00"  # 12:00 in Berlin, a Saturday


@pytest.fixture(autouse=True)
async def berlin(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)


def _now() -> datetime:
    return dt_util.now()


# ----------------------------------------------------------------------
# Stable ids
# ----------------------------------------------------------------------


def test_stable_id_survives_polls_and_list_resets() -> None:
    call = make_call("17", date="09.01.26 20:00")
    # The same entry polled again, now final instead of active.
    assert stable_call_id(call) == stable_call_id(
        make_call("17", 1, date="09.01.26 20:00", duration="0:12")
    )
    # The box started numbering again after the list was cleared.
    assert stable_call_id(call) != stable_call_id(make_call("17", date="10.01.26 08:00"))
    # Without a box id the call itself is hashed.
    a = make_call("", date="09.01.26 20:00")
    assert stable_call_id(a) == stable_call_id(make_call("", date="09.01.26 20:00"))
    assert stable_call_id(a) != stable_call_id(
        make_call("", date="09.01.26 20:00", duration="0:02")
    )


# ----------------------------------------------------------------------
# The store
# ----------------------------------------------------------------------


async def test_merge_dedups_updates_and_prunes(hass: HomeAssistant) -> None:
    history = CallHistory(hass, "entry", days=30)
    await history.async_load()
    old = call_record(make_call("1", date="01.12.25 10:00"))  # 40 days ago
    recent = call_record(make_call("2", date="09.01.26 10:00"))
    undated = call_record(make_call("3", date=None))

    history.async_merge([old, recent, undated])
    assert [r["box_id"] for r in history.records()] == ["2"]

    history.async_merge([recent])
    assert len(history) == 1

    rated = recent | {"is_spam": True}
    history.async_merge([rated])
    assert history.records()[0]["is_spam"] is True

    # Time passes: the call leaves the window.
    history.async_merge([], now=_now() + timedelta(days=31))
    assert len(history) == 0


async def test_load_prunes_to_a_shorter_window(hass: HomeAssistant, hass_storage) -> None:
    hass_storage[storage_key("entry")] = {
        "version": 1,
        "minor_version": 1,
        "key": storage_key("entry"),
        "data": {
            "calls": [
                call_record(make_call("1", date="20.12.25 10:00")),
                call_record(make_call("2", date="08.01.26 10:00")),
                {"no": "id"},
            ]
        },
    }
    history = CallHistory(hass, "entry", days=7)
    await history.async_load()
    assert [r["box_id"] for r in history.records()] == ["2"]


async def test_history_collects_calls_that_left_the_list(
    hass: HomeAssistant, hass_ws_client, hass_storage
) -> None:
    box = FakeBox(
        calls=[make_call("1", date="02.01.26 10:00"), make_call("2", date="09.01.26 10:00")]
    )
    entry = await setup_integration(hass, box, {CONF_CALL_HISTORY_DAYS: 90, CONF_CALL_LIST_DAYS: 7})
    coordinator = get_coordinator(hass, entry)
    assert len(coordinator.history) == 2

    # The box drops the older call; the history keeps it.
    box.calls = [make_call("2", date="09.01.26 10:00"), make_call("3", date="10.01.26 08:00")]
    await coordinator.async_refresh()
    assert len(coordinator.history) == 3

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/calls", "entry_id": entry.entry_id, "days": 30}
    )
    result = (await client.receive_json())["result"]
    assert result["window"]["source"] == "history"
    assert [(c["box_id"], c["in_list"]) for c in result["calls"]] == [
        ("3", True),
        ("2", True),
        ("1", False),
    ]
    assert result["window"]["oldest"] == "2026-01-02T10:00:00+01:00"

    # Within the list window the live list answers.
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/calls", "entry_id": entry.entry_id, "days": 7}
    )
    result = (await client.receive_json())["result"]
    assert result["window"]["source"] == "list"
    assert result["total"] == 2

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/stats", "entry_id": entry.entry_id, "days": 0}
    )
    result = (await client.receive_json())["result"]
    assert (result["window"]["source"], result["window"]["count"]) == ("history", 3)

    await client.send_json_auto_id({"type": f"{DOMAIN}/entries"})
    assert (await client.receive_json())["result"]["entries"][0]["history_days"] == 90

    # Written on unload, deleted with the entry.
    await hass.config_entries.async_unload(entry.entry_id)
    stored = hass_storage[storage_key(entry.entry_id)]["data"]["calls"]
    assert sorted(record["box_id"] for record in stored) == ["1", "2", "3"]
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert storage_key(entry.entry_id) not in hass_storage


async def test_history_off_deletes_the_file(hass: HomeAssistant, hass_storage) -> None:
    box = FakeBox(calls=[make_call("1", date="09.01.26 10:00")])
    entry = await setup_integration(hass, box, {CONF_CALL_HISTORY_DAYS: 30})
    await hass.config_entries.async_unload(entry.entry_id)
    assert storage_key(entry.entry_id) in hass_storage

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CALL_HISTORY_DAYS: 0}
    )
    with patch("custom_components.fritzbox_phone.FritzBoxPhoneClient", build_client_class(box)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert get_coordinator(hass, entry).history is None
    assert storage_key(entry.entry_id) not in hass_storage


async def test_no_history_by_default(hass: HomeAssistant, hass_storage) -> None:
    entry = await setup_integration(hass, FakeBox(calls=[make_call("1", date="09.01.26 10:00")]))
    assert get_coordinator(hass, entry).history is None
    await hass.config_entries.async_unload(entry.entry_id)
    assert storage_key(entry.entry_id) not in hass_storage


# ----------------------------------------------------------------------
# Statistics on a fixed sample
# ----------------------------------------------------------------------


def _sample() -> list[dict]:
    calls = [
        # This week (04.01.-10.01.2026)
        make_call(
            "1", 1, caller_number="030111", date="10.01.26 09:15", duration="0:05", name="Anna"
        ),
        make_call("2", 1, caller_number="030111", date="09.01.26 09:30", duration="1:02"),
        make_call("3", 2, caller_number="030222", date="09.01.26 20:00", duration="0:00"),
        make_call(
            "4",
            3,
            caller_number="0302222",
            called_number="030333",
            date="08.01.26 18:45",
            duration="0:10",
        ),
        make_call(
            "5", 1, caller_number="030999", date="05.01.26 11:00", duration="0:03", is_spam=True
        ),
        make_call(
            "6",
            1,
            caller_number="030222",
            date="04.01.26 08:00",
            duration="0:01",
            is_tam=True,
            port="40",
        ),
        # The week before (28.12.2025-03.01.2026)
        make_call("7", 1, caller_number="030111", date="02.01.26 10:00", duration="0:03"),
        make_call("8", 2, caller_number="030444", date="28.12.25 10:00", duration="0:00"),
        # Unreadable date
        make_call("9", 1, date="gestern"),
    ]
    records = [call_record(call) for call in calls]
    for record in records:
        record["vip"] = record["caller_number"] == "030111"
    return records


def test_stats_week() -> None:
    stats = compute_stats(_sample(), 7, _now(), "list")
    assert stats["window"] == {
        "days": 7,
        "from": "2026-01-04",
        "to": "2026-01-10",
        "oldest": "2025-12-28T10:00:00+01:00",
        "newest": "2026-01-10T09:15:00+01:00",
        "count": 6,
        "undated": 1,
        "source": "list",
    }
    assert stats["totals"] == {
        "calls": 6,
        "incoming": 2,
        "outgoing": 1,
        "missed": 2,  # the missed call and the one the answering machine took
        "spam": 1,
        "connected": 4,
        "talk_minutes": 80,  # 5 + 62 + 10 + 3
        "avg_talk_minutes": 20.0,
        "missed_rate": 0.4,  # 2 of 5 inbound
    }
    assert [day["date"] for day in stats["per_day"]] == [
        f"2026-01-{day:02d}" for day in range(4, 11)
    ]
    friday = stats["per_day"][5]
    assert friday == {
        "date": "2026-01-09",
        "incoming": 1,
        "outgoing": 0,
        "missed": 1,
        "spam": 0,
        "talk_minutes": 62,
    }

    heat = stats["heat"]
    assert len(heat) == 7 and all(len(row) == 24 for row in heat)
    assert sum(map(sum, heat)) == 6
    assert heat[5][9] == 1  # Saturday 09:15
    assert heat[4][9] == 1 and heat[4][20] == 1  # Friday
    assert heat[3][18] == 1  # Thursday
    assert heat[0][11] == 1  # Monday
    assert heat[6][8] == 1  # Sunday

    assert stats["compare"] == {"kind": "full", "days": 7, "cover_days": 7}
    previous = stats["previous"]
    assert (previous["calls"], previous["incoming"], previous["missed"]) == (2, 1, 1)
    assert previous["talk_minutes"] == 3

    assert stats["top_callers"] == [
        {
            "number": "030111",
            "name": "Anna",
            "vip": True,
            "count": 2,
            "talk_minutes": 67,
            "spam": False,
        },
        {
            "number": "030222",
            "name": None,
            "vip": False,
            "count": 2,
            "talk_minutes": 0,
            "spam": False,
        },
        {
            "number": "030999",
            "name": None,
            "vip": False,
            "count": 1,
            "talk_minutes": 3,
            "spam": True,
        },
    ]
    assert stats["top_called"] == [
        {
            "number": "030333",
            "name": None,
            "vip": False,
            "count": 1,
            "talk_minutes": 10,
            "spam": False,
        }
    ]
    assert stats["per_line"] == [
        {"own_number": "0301111", "count": 5},
        {"own_number": "0302222", "count": 1},
    ]


def test_stats_all_and_uncovered_previous_period() -> None:
    stats = compute_stats(_sample(), 0, _now(), "history")
    assert stats["window"]["from"] == "2025-12-28"
    assert stats["window"]["count"] == 8
    assert len(stats["per_day"]) == 14
    assert stats["previous"] is None
    assert stats["compare"]["kind"] == "none"

    # 30 days reach back to 12.12.; nothing is held before 28.12.
    stats = compute_stats(_sample(), 30, _now(), "list")
    assert stats["previous"] is None
    assert stats["compare"] == {"kind": "none", "days": 30, "cover_days": 0}
    assert len(stats["per_day"]) == 30


def test_stats_partial_previous_period() -> None:
    # Held from 28.12.: the 4 days before the window (03.01.-06.01.) are covered.
    stats = compute_stats(_sample(), 4, _now(), "list")
    assert stats["compare"] == {"kind": "full", "days": 4, "cover_days": 4}
    # Held only from 04.01.: 3 of those 4 days are covered - enough to compare.
    records = [r for r in _sample() if r["box_id"] not in ("7", "8")]
    stats = compute_stats(records, 4, _now(), "list")
    assert stats["compare"] == {"kind": "partial", "days": 4, "cover_days": 3}
    assert stats["previous"]["calls"] == 2  # 04.01. and 05.01.
    # Held from 04.01. but asked for 7 days: nothing before 04.01.
    assert compute_stats(records, 7, _now(), "list")["previous"] is None


def test_stats_without_calls() -> None:
    stats = compute_stats([], 7, _now(), "list")
    assert stats["totals"]["calls"] == 0
    assert stats["totals"]["missed_rate"] == 0
    assert stats["window"]["oldest"] is None
    assert stats["previous"] is None
    assert stats["top_callers"] == []
