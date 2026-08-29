"""Client for PhoneBlock's privacy-preserving spam-check API.

PhoneBlock (https://phoneblock.net) is a free, open-source (GPL-3.0),
community-maintained spam-caller database built specifically for FRITZ!Box
use cases. Its `GET /api/check` endpoint only ever receives a SHA-1 hash of
the phone number - never the number itself - and is documented (in the
project's own source) as "deciding whether a number is in the database
without revealing the calling number to the service".

Endpoint, auth scheme and response schema were verified directly against
the project's public source (github.com/haumacher/phoneblock):
- de.haumacher.phoneblock.app.api.SpamCheckServlet (PATH = "/api/check",
  HTTP Basic Auth against a PhoneBlock account)
- de.haumacher.phoneblock.app.api.model.api.proto (PhoneInfo message)
- phoneblock_mobile's CallChecker.java (reference client: number
  normalization to E.164 before hashing, optional prefix10/prefix100
  hashes for range-based spam detection)

A free PhoneBlock account (https://phoneblock.net) is required - the API
authenticates every request to prevent abuse.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import re
import time
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

API_URL = "https://phoneblock.net/phoneblock/api/check"
DEFAULT_CACHE_TTL = 6 * 3600  # seconds; spam ratings don't change minute to minute

_NUMBER_STRIP_RE = re.compile(r"[^\d+]")


def normalize_e164(number: str | None, country_prefix: str) -> str | None:
    """Best-effort normalization of a national/local number to E.164 form.

    PhoneBlock's own reference client (phoneblock_mobile) normalizes to
    international format before hashing, so a differently-formatted local
    number would hash to something PhoneBlock never sees as blocked even if
    the number itself is known to them.
    """
    digits = _NUMBER_STRIP_RE.sub("", number or "")
    if not digits:
        return None
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("+"):
        return digits
    if digits.startswith("0"):
        return country_prefix + digits[1:]
    return digits


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


@dataclass
class PhoneBlockInfo:
    rating: str | None
    votes: int
    votes_wildcard: int
    black_listed: bool
    white_listed: bool
    label: str | None
    location: str | None
    spam_confidence: int
    is_spam: bool


class PhoneBlockClient:
    """Thin client for PhoneBlock's /api/check. Blocking, use from an executor."""

    def __init__(
        self,
        username: str,
        password: str,
        country_prefix: str,
        spam_threshold: int,
        timeout: float = 8,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._auth = (username, password)
        self._country_prefix = country_prefix
        self._spam_threshold = spam_threshold
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._session = requests.Session()
        self._cache: dict[str, tuple[float, PhoneBlockInfo | None]] = {}

    def check(self, number: str | None) -> PhoneBlockInfo | None:
        """Look up a number's spam rating. Returns None on any failure."""
        e164 = normalize_e164(number, self._country_prefix)
        if not e164:
            return None

        cached = self._cache.get(e164)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        info = self._check_uncached(e164)
        self._cache[e164] = (now, info)
        return info

    def _check_uncached(self, e164: str) -> PhoneBlockInfo | None:
        params: dict[str, Any] = {"sha1": _sha1(e164), "format": "json"}
        # Range-based detection: also send hashes of the number with the
        # last 1/2 digits stripped, so freshly-rotated spam number pools
        # can be caught even before the exact number is individually
        # reported (same technique PhoneBlock's own mobile client uses).
        if len(e164) > 2:
            params["prefix10"] = _sha1(e164[:-1])
            params["prefix100"] = _sha1(e164[:-2])

        try:
            response = self._session.get(
                API_URL, params=params, auth=self._auth, timeout=self._timeout
            )
            response.raise_for_status()
            data = response.json()
        except Exception as err:  # noqa: BLE001 - this is a best-effort side
            # enrichment; any failure here (network, PhoneBlock outage, an
            # unexpected response shape) must never break call-list/coordinator
            # updates, so we deliberately swallow everything and just skip
            # enrichment for this number.
            _LOGGER.debug("PhoneBlock-Abfrage fehlgeschlagen: %s", err)
            return None

        confidence = int(data.get("spamConfidence") or 0)
        black_listed = bool(data.get("blackListed"))
        return PhoneBlockInfo(
            rating=data.get("rating"),
            votes=int(data.get("votes") or 0),
            votes_wildcard=int(data.get("votesWildcard") or 0),
            black_listed=black_listed,
            white_listed=bool(data.get("whiteListed")),
            label=data.get("label") or None,
            location=data.get("location") or None,
            spam_confidence=confidence,
            is_spam=black_listed or confidence >= self._spam_threshold,
        )
