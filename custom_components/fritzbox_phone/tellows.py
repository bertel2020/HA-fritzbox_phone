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

import aiohttp
from defusedxml import ElementTree as ET

from .cache import LookupCache

_LOGGER = logging.getLogger(__name__)

API_URL = "https://www.tellows.de/basic/num/{number}"
DEFAULT_SPAM_SCORE_THRESHOLD = 7  # Tellows scale is 1 (trustworthy) - 9 (dangerous)
# The real answer is a few hundred bytes; anything far beyond that is not
# the API talking.
MAX_RESPONSE_BYTES = 64 * 1024

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
    """Thin async client for Tellows' public /basic/num XML API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        spam_score_threshold: int = DEFAULT_SPAM_SCORE_THRESHOLD,
        timeout: float = 8,
        cache: LookupCache[TellowsInfo] | None = None,
    ) -> None:
        self._session = session
        self._spam_score_threshold = spam_score_threshold
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._cache: LookupCache[TellowsInfo] = cache or LookupCache()

    async def lookup(self, number: str | None) -> TellowsInfo | None:
        """Look up a number on Tellows. Returns None on any failure."""
        normalized = normalize_number(number)
        if not normalized:
            return None

        hit, cached = self._cache.get(normalized)
        if hit:
            return cached

        try:
            info = await self._lookup_uncached(normalized)
        except Exception as err:  # noqa: BLE001 - best-effort side enrichment,
            # must never break call-list/coordinator updates; any failure
            # (network, Tellows outage, unexpected response) just skips
            # enrichment for this number.
            _LOGGER.debug("Tellows-Abfrage fehlgeschlagen: %s", err)
            self._cache.set(normalized, None, failed=True)
            return None
        self._cache.set(normalized, info)
        return info

    async def _lookup_uncached(self, number: str) -> TellowsInfo:
        async with self._session.get(
            API_URL.format(number=number), params={"xml": "1"}, timeout=self._timeout
        ) as response:
            response.raise_for_status()
            body = await response.content.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Tellows-Antwort ist ungewöhnlich groß")
        try:
            raw = body.decode("utf-8")
        except UnicodeDecodeError:
            raw = body.decode("latin-1")

        end = raw.find("</tellows>")
        if end == -1:
            raise ValueError("Tellows-Antwort hat kein <tellows>-Element")
        # defusedxml refuses entity-expansion and external-entity tricks.
        root = ET.fromstring(raw[: end + len("</tellows>")])

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
