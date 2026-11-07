"""Opt-in call history and the call statistics.

The FRITZ!Box keeps only a limited call list (and this integration asks for
a window of it, see the options). With the option `call_history_days` set,
every refreshed call list is merged into a store in Home Assistant's
`.storage` folder, one file per config entry, deduplicated by the stable
call id (payloads.stable_call_id) and pruned to that many days. The store
is only read by the websocket commands `calls` and `stats`. With the option
at 0 (the default) nothing is written, and an existing file is deleted.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .payloads import OUTGOING_TYPES, counterpart_number, own_number

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Merges happen on every poll; the file is written at most this often.
SAVE_DELAY = 30  # seconds

SOURCE_LIST = "list"
SOURCE_HISTORY = "history"

TOP_LIMIT = 5


def storage_key(entry_id: str) -> str:
    return f"{DOMAIN}.call_history.{entry_id}"


def _started(record: dict[str, Any]) -> datetime | None:
    value = record.get("datetime")
    return dt_util.parse_datetime(value) if value else None


class CallHistory:
    """Calls of one config entry, kept for `days` days on disk."""

    def __init__(self, hass: HomeAssistant, entry_id: str, days: int) -> None:
        self.hass = hass
        self.days = days
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry_id), private=True
        )
        self._calls: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        calls = data.get("calls") if isinstance(data, dict) else None
        self._calls = {
            record["id"]: record
            for record in calls or []
            if isinstance(record, dict) and record.get("id")
        }
        if self._prune(dt_util.now()):
            self._schedule_save()

    @staticmethod
    async def async_delete(hass: HomeAssistant, entry_id: str) -> None:
        """Remove the file of an entry (option switched off, entry removed)."""
        await Store(hass, STORAGE_VERSION, storage_key(entry_id), private=True).async_remove()

    async def async_save(self) -> None:
        """Write now (on unload) instead of waiting for the delayed save."""
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"calls": list(self._calls.values())}

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _prune(self, now: datetime) -> int:
        """Drop calls older than the window (and any without a date)."""
        cutoff = now - timedelta(days=self.days)
        stale = [
            call_id
            for call_id, record in self._calls.items()
            if (started := _started(record)) is None or started < cutoff
        ]
        for call_id in stale:
            del self._calls[call_id]
        return len(stale)

    @callback
    def async_merge(self, records: Iterable[dict[str, Any]], now: datetime | None = None) -> None:
        """Add (or update) the calls of a fresh call list and prune the rest.

        A call that is in the list again replaces what was stored for it, so
        late enrichment (spam rating, reverse lookup) and an `active_*`
        entry that became final are kept in their latest form.
        """
        now = now or dt_util.now()
        changed = False
        for record in records:
            if not record.get("id") or record.get("datetime") is None:
                continue
            if self._calls.get(record["id"]) != record:
                self._calls[record["id"]] = dict(record)
                changed = True
        if self._prune(now):
            changed = True
        if changed:
            self._schedule_save()

    def records(self) -> list[dict[str, Any]]:
        """All stored calls, newest first."""
        return sort_newest_first(self._calls.values())

    def __len__(self) -> int:
        return len(self._calls)


def sort_newest_first(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first; calls without a readable date go to the end."""
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for record in records:
        if (started := _started(record)) is None:
            undated.append(record)
        else:
            dated.append((started, record))
    dated.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in dated] + undated


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------


def call_minutes(record: dict[str, Any]) -> int:
    """The call list's duration is "h:mm" (minutes, rounded up by the box), not m:ss."""
    hours, _, minutes = str(record.get("duration") or "").partition(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return 0


def category(record: dict[str, Any]) -> str:
    """One series per call: spam first, missed includes the answering machine."""
    if record.get("is_spam"):
        return "spam"
    if record.get("type") in OUTGOING_TYPES:
        return "outgoing"
    if record.get("type") in ("missed", "rejected_incoming") or record.get("is_answering_machine"):
        return "missed"
    return "incoming"


def connected(record: dict[str, Any]) -> bool:
    """A call that was talked on: incoming or outgoing and not the answering machine."""
    return record.get("type") in ("incoming", "outgoing") and not record.get("is_answering_machine")


def _digits(number: str | None) -> str:
    text = str(number or "")
    plus = "+" if text.strip().startswith("+") else ""
    return plus + "".join(ch for ch in text if ch.isdigit())


def totals(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"incoming": 0, "outgoing": 0, "missed": 0, "spam": 0}
    for record in records:
        counts[category(record)] += 1
    talked = [record for record in records if connected(record)]
    talk = sum(call_minutes(record) for record in talked)
    inbound = [record for record in records if record.get("type") not in OUTGOING_TYPES]
    return {
        "calls": len(records),
        **counts,
        "connected": len(talked),
        "talk_minutes": talk,
        "avg_talk_minutes": round(talk / len(talked), 1) if talked else 0,
        "missed_rate": round(counts["missed"] / len(inbound), 3) if inbound else 0,
    }


def _top(records: list[dict[str, Any]], outgoing: bool) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        if (record.get("type") in OUTGOING_TYPES) is not outgoing:
            continue
        number = counterpart_number(record)
        if not (key := _digits(number)):
            continue
        entry = grouped.setdefault(
            key,
            {
                "number": number,
                "name": None,
                "vip": False,
                "count": 0,
                "talk_minutes": 0,
                "spam": False,
            },
        )
        entry["count"] += 1
        if connected(record):
            entry["talk_minutes"] += call_minutes(record)
        entry["name"] = entry["name"] or record.get("name") or None
        entry["vip"] = entry["vip"] or bool(record.get("vip"))
        entry["spam"] = entry["spam"] or bool(record.get("is_spam"))
    ranked = sorted(
        grouped.items(), key=lambda item: (-item[1]["count"], -item[1]["talk_minutes"], item[0])
    )
    return [entry for _, entry in ranked[:TOP_LIMIT]]


def _per_line(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        if not (number := own_number(record)):
            continue
        entry = grouped.setdefault(_digits(number) or number, {"own_number": number, "count": 0})
        entry["count"] += 1
    return sorted(grouped.values(), key=lambda entry: (-entry["count"], entry["own_number"]))


def compute_stats(
    records: list[dict[str, Any]], days: int, now: datetime, source: str
) -> dict[str, Any]:
    """Everything the statistics view shows, for the last `days` days (0 = all held).

    Days are calendar days in Home Assistant's time zone, today included.
    `previous` covers the same number of days right before; it is given
    when the held calls reach back at least half of that period
    (`compare.cover_days` says how far), otherwise it is None.
    """
    dated = [(started, record) for record in records if (started := _started(record)) is not None]
    today = dt_util.as_local(now).date()
    oldest = min((started for started, _ in dated), default=None)
    newest = max((started for started, _ in dated), default=None)
    oldest_day = dt_util.as_local(oldest).date() if oldest else None

    if days > 0:
        first_day = today - timedelta(days=days - 1)
    else:
        first_day = oldest_day or today
    length = (today - first_day).days + 1

    def local_day(started: datetime) -> date:
        return dt_util.as_local(started).date()

    inside = [
        (started, record) for started, record in dated if first_day <= local_day(started) <= today
    ]
    in_window = [record for _, record in inside]

    per_day: dict[date, dict[str, Any]] = {}
    for offset in range(length):
        day = first_day + timedelta(days=offset)
        per_day[day] = {
            "date": day.isoformat(),
            "incoming": 0,
            "outgoing": 0,
            "missed": 0,
            "spam": 0,
            "talk_minutes": 0,
        }
    heat = [[0] * 24 for _ in range(7)]
    for started, record in inside:
        local = dt_util.as_local(started)
        bucket = per_day[local.date()]
        bucket[category(record)] += 1
        if connected(record):
            bucket["talk_minutes"] += call_minutes(record)
        heat[local.weekday()][local.hour] += 1

    previous = None
    compare: dict[str, Any] = {"kind": "none", "days": days, "cover_days": 0}
    if days > 0 and oldest_day is not None:
        previous_first = first_day - timedelta(days=days)
        cover = min(days, max(0, (first_day - oldest_day).days))
        if cover >= days / 2 and cover > 0:
            previous = totals(
                [
                    record
                    for started, record in dated
                    if previous_first <= local_day(started) < first_day
                ]
            )
            compare = {
                "kind": "full" if cover == days else "partial",
                "days": days,
                "cover_days": cover,
            }
        else:
            compare["cover_days"] = cover

    return {
        "window": {
            "days": days,
            "from": first_day.isoformat(),
            "to": today.isoformat(),
            "oldest": oldest.isoformat() if oldest else None,
            "newest": newest.isoformat() if newest else None,
            "count": len(in_window),
            "undated": len(records) - len(dated),
            "source": source,
        },
        "per_day": list(per_day.values()),
        "heat": heat,
        "totals": totals(in_window),
        "previous": previous,
        "compare": compare,
        "top_callers": _top(in_window, outgoing=False),
        "top_called": _top(in_window, outgoing=True),
        "per_line": _per_line(in_window),
    }
