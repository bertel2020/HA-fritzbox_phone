"""Client for Tellows' public reverse-lookup / spam-score API.

Tellows (https://www.tellows.de) is a community caller-ID/spam-rating
database. Its `GET /basic/num/{nummer}?xml=1` endpoint is a public,
unauthenticated API - no account or API key required - and is the same
data source AVM itself licenses for FRITZ!OS's built-in caller
identification in some markets. Verified directly by querying the live
endpoint: it returns full XML (score, location, and, when known,
`numberDetails` with a real name for the number) with no credentials.

Unlike PhoneBlock's `/api/check` (a SHA-1 hash only), this endpoint
receives the RAW phone number - that's Tellows' whole purpose (a public
caller-ID/reverse-lookup lookup), but it means this feature has a
different, higher privacy cost and is opt-in and off by default,
independent of the PhoneBlock spam-check toggle.

Two other providers the user considered, dastelefonbuch.de and
dasoertliche.de/11880.com, were deliberately NOT implemented:
- dastelefonbuch.de's robots.txt explicitly disallows known bots/scrapers
  (ClaudeBot, GPTBot, Scrapy, ...), so this integration doesn't crawl it.
- dasoertliche.de and 11880.com have no public API for this - only an
  HTML search-results page meant for browsers, which would require
  fragile screen-scraping that breaks on any layout change.

Quirk observed live: when the (optional, undocumented) `partner` query
param is missing or not recognized, Tellows appends a plain-text
"Partner Data not correct" line AFTER the closing `</tellows>` tag, in
the same response body. This makes the response not well-formed XML, so
we trim everything after `</tellows>` before parsing.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import time
import xml.etree.ElementTree as ET

import requests

_LOGGER = logging.getLogger(__name__)

API_URL = "https://www.tellows.de/basic/num/{number}"
DEFAULT_CACHE_TTL = 6 * 3600  # seconds; caller ratings don't change minute to minute
DEFAULT_SPAM_SCORE_THRESHOLD = 7  # Tellows scale is 1 (trustworthy) - 9 (dangerous)

_NUMBER_STRIP_RE = re.compile(r"[^\d+]")


def normalize_number(number: str | None) -> str | None:
    """Strip formatting so Tellows can parse the number.

    Tellows accepts both national ("030123456") and E.164 ("+4930123456")
    forms, so this only removes spaces/dashes/parens - no need to rewrite
    to a single canonical form like PhoneBlock's hashing requires.
    """
    digits = _NUMBER_STRIP_RE.sub("", number or "")
    return digits or None


@dataclass
class TellowsInfo:
    name: str | None
    category: str | None
    is_company: bool
    location: str | None
    score: int
    searches: int
    comments: int
    is_spam: bool


class TellowsClient:
    """Thin client for Tellows' public /basic/num XML API. Blocking, use from an executor."""

    def __init__(
        self,
        spam_score_threshold: int = DEFAULT_SPAM_SCORE_THRESHOLD,
        timeout: float = 8,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._spam_score_threshold = spam_score_threshold
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._session = requests.Session()
        self._cache: dict[str, tuple[float, TellowsInfo | None]] = {}

    def lookup(self, number: str | None) -> TellowsInfo | None:
        """Look up a number on Tellows. Returns None on any failure."""
        normalized = normalize_number(number)
        if not normalized:
            return None

        cached = self._cache.get(normalized)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        info = self._lookup_uncached(normalized)
        self._cache[normalized] = (now, info)
        return info

    def _lookup_uncached(self, number: str) -> TellowsInfo | None:
        try:
            response = self._session.get(
                API_URL.format(number=number),
                params={"xml": "1"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            raw = response.text
        except Exception as err:  # noqa: BLE001 - best-effort side enrichment,
            # must never break call-list/coordinator updates; any failure
            # (network, Tellows outage, unexpected response) just skips
            # enrichment for this number.
            _LOGGER.debug("Tellows-Abfrage fehlgeschlagen: %s", err)
            return None

        end = raw.find("</tellows>")
        if end == -1:
            _LOGGER.debug("Tellows-Antwort hat kein <tellows>-Element: %r", raw[:200])
            return None
        try:
            root = ET.fromstring(raw[: end + len("</tellows>")])
        except ET.ParseError as err:
            _LOGGER.debug("Tellows-Antwort nicht parsbar: %s", err)
            return None

        score_text = root.findtext("score")
        try:
            score = int(score_text) if score_text else 0
        except ValueError:
            score = 0

        details = root.find("numberDetails")
        name = details.findtext("name") if details is not None else None
        category = details.findtext("category") if details is not None else None
        is_company = bool(details is not None and details.findtext("isCompany") == "1")

        def _count(tag: str) -> int:
            text = root.findtext(tag)
            try:
                return int(text) if text else 0
            except ValueError:
                return 0

        return TellowsInfo(
            name=name or None,
            category=category or None,
            is_company=is_company,
            location=root.findtext("location") or None,
            score=score,
            searches=_count("searches"),
            comments=_count("comments"),
            is_spam=score >= self._spam_score_threshold,
        )
