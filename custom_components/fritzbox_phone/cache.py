"""Small bounded cache for online lookup results."""
from __future__ import annotations

from collections import OrderedDict
import time
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_TTL = 6 * 3600  # seconds; ratings don't change minute to minute
# A failed lookup (timeout, outage) is remembered only briefly so a short
# hiccup at the provider does not switch the feature off for hours, yet a
# dead provider is not hammered on every poll either.
DEFAULT_FAILURE_TTL = 300
DEFAULT_MAX_ENTRIES = 1000


class LookupCache(Generic[T]):
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
        self._entries: OrderedDict[str, tuple[float, T | None]] = OrderedDict()

    def get(self, key: str) -> tuple[bool, T | None]:
        """(hit, value). A hit may carry a None value (a remembered failure)."""
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        expires, value = entry
        if time.monotonic() >= expires:
            del self._entries[key]
            return False, None
        self._entries.move_to_end(key)
        return True, value

    def set(self, key: str, value: T | None, *, failed: bool = False) -> None:
        ttl = self._failure_ttl if failed else self._ttl
        self._entries[key] = (time.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)
