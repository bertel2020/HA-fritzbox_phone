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
from typing import Any

import aiohttp

from .cache import LookupCache

_LOGGER = logging.getLogger(__name__)

API_URL = "https://phoneblock.net/phoneblock/api/check"

_NUMBER_STRIP_RE = re.compile(r"[^\d+]")


def normalize_e164(number: str | None, country_prefix: str) -> str | None:
    """Best-effort normalization of a national/local number to E.164 form.

    PhoneBlock's own reference client (phoneblock_mobile) normalizes to
    international format before hashing, so a differently-formatted local
    number would hash to something PhoneBlock never sees as blocked even if
    the number itself is known to them. The coordinator already hands in
    canonical numbers (see phone_numbers.py); this only catches the leftovers.
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
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # noqa: S324 - API protocol


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
    """Thin async client for PhoneBlock's /api/check."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        country_prefix: str,
        spam_threshold: int,
        timeout: float = 8,
        cache: LookupCache[PhoneBlockInfo] | None = None,
    ) -> None:
        self._session = session
        self._auth = aiohttp.BasicAuth(username, password)
        self._country_prefix = country_prefix
        self._spam_threshold = spam_threshold
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._cache: LookupCache[PhoneBlockInfo] = cache or LookupCache()

    async def check(self, number: str | None) -> PhoneBlockInfo | None:
        """Look up a number's spam rating. Returns None on any failure."""
        e164 = normalize_e164(number, self._country_prefix)
        if not e164:
            return None

        hit, cached = self._cache.get(e164)
        if hit:
            return cached

        try:
            info = await self._check_uncached(e164)
        except Exception as err:  # noqa: BLE001 - this is a best-effort side
            # enrichment; any failure here (network, PhoneBlock outage, an
            # unexpected response shape) must never break call-list/coordinator
            # updates, so we deliberately swallow everything and just skip
            # enrichment for this number.
            _LOGGER.debug("PhoneBlock-Abfrage fehlgeschlagen: %s", err)
            self._cache.set(e164, None, failed=True)
            return None
        self._cache.set(e164, info)
        return info

    async def _check_uncached(self, e164: str) -> PhoneBlockInfo:
        params: dict[str, Any] = {"sha1": _sha1(e164), "format": "json"}
        # Range-based detection: also send hashes of the number with the
        # last 1/2 digits stripped, so freshly-rotated spam number pools
        # can be caught even before the exact number is individually
        # reported (same technique PhoneBlock's own mobile client uses).
        if len(e164) > 2:
            params["prefix10"] = _sha1(e164[:-1])
            params["prefix100"] = _sha1(e164[:-2])

        async with self._session.get(
            API_URL, params=params, auth=self._auth, timeout=self._timeout
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)

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
