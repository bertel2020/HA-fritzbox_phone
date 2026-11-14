"""Small bounded cache for online lookup results."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any
import time

DEFAULT_TTL = 6 * 3600  # seconds; ratings don't change minute to minute
# A failed lookup (timeout, outage) is remembered only briefly so a short
# hiccup at the provider does not switch the feature off for hours, yet a
# dead provider is not hammered on every poll either.
DEFAULT_FAILURE_TTL = 300
DEFAULT_MAX_ENTRIES = 1000


class LookupCache[T]:
    """TTL cache with a size limit (least recently used goes first)."""

    def __init__(
        self,
        ttl: float = DEFAULT_TTL,
        failure_ttl: float = DEFAULT_FAILURE_TTL,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = ttl
        self._failure_ttl = failure_ttl
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, T | None, bool]] = OrderedDict()
        # Called after a real result was stored (not after a failure), so
        # an owner can save the cache.
        self.on_change: Callable[[], None] | None = None

    def get(self, key: str) -> tuple[bool, T | None]:
        """(hit, value). A hit may carry a None value (a remembered failure)."""
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        expires, value, _failed = entry
        if time.monotonic() >= expires:
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def set(self, key: str, value: T | None, *, failed: bool = False) -> None:
        ttl = self._failure_ttl if failed else self._ttl
        self._entries[key] = (time.monotonic() + ttl, value, failed)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        if not failed and self.on_change is not None:
            self.on_change()

    def dump(self, encode: Callable[[T], Any]) -> list[list[Any]]:
        """The results worth keeping across a restart: [key, expiry, value].

        The expiry is a wall-clock time (the monotonic clock restarts with
        the process). Remembered failures are left out.
        """
        offset = time.time() - time.monotonic()
        return [
            [key, expires + offset, None if value is None else encode(value)]
            for key, (expires, value, failed) in self._entries.items()
            if not failed and expires + offset > time.time()
        ]

    def load(self, rows: Any, decode: Callable[[Any], T]) -> None:
        """Take back what dump() wrote. Rows that are unusable are skipped."""
        offset = time.monotonic() - time.time()
        now = time.time()
        for row in rows if isinstance(rows, list) else []:
            try:
                key, expires_at, raw = row
                if not isinstance(key, str) or expires_at <= now:
                    continue
                value = None if raw is None else decode(raw)
            except (TypeError, ValueError, KeyError):
                continue
            self._entries[key] = (expires_at + offset, value, False)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
