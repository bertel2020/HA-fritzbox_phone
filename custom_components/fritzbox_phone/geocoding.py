"""Offline country/area-code lookup for phone numbers.

Uses Google's libphonenumber (via the `phonenumbers` package), which
bundles its own area-code/country geocoding tables - no network access,
no third-party service, no privacy trade-off. This is what a FRITZ!Box's
own web UI shows next to unrecognized callers (e.g. "Berlin" for a 030
number); TR-064 has no action exposing a lookup for arbitrary numbers
(verified against the X_AVM-DE_OnTel and X_AVM-DE_TAM specifications).

X_VoIP's X_AVM-DE_GetVoIPCommonAreaCode *is* used here though - not to
look up a caller, but because the FRITZ!Box itself reports caller numbers
from its own local area (Ortsnetz) WITHOUT an area code at all (standard
German local-dialing convention, e.g. "954934" instead of "07527954934")
- `phonenumbers` can't geocode those without the area code prepended, so
the coordinator passes the box's own configured one in as a fallback.
"""
from __future__ import annotations

import logging

import phonenumbers
from phonenumbers import geocoder

_LOGGER = logging.getLogger(__name__)


def describe_number(
    number: str | None, default_region: str = "DE", local_area_code: str | None = None
) -> str | None:
    """Best-effort city/country description for a phone number.

    Returns e.g. "Berlin" for a German landline, "Innsbruck" for an
    Austrian one, or just "Deutschland" for a German mobile number (mobile
    prefixes aren't geographically tied, so libphonenumber only knows the
    country). Returns None if the number can't be parsed/is invalid.

    `local_area_code` (e.g. "07527") is prepended when `number` doesn't
    already start with "0" or "+" - see module docstring.
    """
    if not number:
        return None
    to_parse = number
    if local_area_code and not number.startswith(("+", "0")):
        to_parse = f"{local_area_code}{number}"
    try:
        parsed = phonenumbers.parse(to_parse, default_region)
    except phonenumbers.NumberParseException as err:
        _LOGGER.debug("Konnte Nummer nicht parsen für Orts-Lookup: %s", err)
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return geocoder.description_for_number(parsed, "de") or None
