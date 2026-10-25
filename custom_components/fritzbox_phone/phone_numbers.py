"""Phone number normalisation shared by phonebook matching and lookups.

The FRITZ!Box reports numbers in whatever shape the carrier delivered
them: international (+49...), national with trunk prefix (030...), or -
for callers in the box's own local area - without any area code at all
(see geocoding.py). Comparing them as plain strings misses real matches,
and hashing/looking up a non-canonical form at PhoneBlock or Tellows
finds nothing. Everything is therefore reduced to one canonical form
(E.164, e.g. "+4930123456") using libphonenumber; numbers it cannot make
sense of fall back to their bare digits.
"""
from __future__ import annotations

import re

import phonenumbers

_STRIP_RE = re.compile(r"[^\d+]")


def digits_only(number: str | None) -> str:
    """Strip everything but digits and a leading '+'."""
    return _STRIP_RE.sub("", number or "")


def normalize(
    number: str | None,
    region: str = "DE",
    country_prefix: str = "+49",
    own_area_code: str | None = None,
) -> str | None:
    """Canonical form of `number`, or None if there are no digits at all.

    `own_area_code` (e.g. "07527") is prepended to numbers that carry
    neither a '+' nor a leading '0', i.e. local-area numbers.
    """
    cleaned = digits_only(number)
    if not cleaned.strip("+"):
        return None
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif not cleaned.startswith(("+", "0")):
        if not own_area_code:
            # A local-area number (or a service code like "110") without
            # a known area code: libphonenumber would happily read it as
            # a national number and invent a wrong canonical form.
            return cleaned
        cleaned = own_area_code + cleaned
    try:
        parsed = phonenumbers.parse(cleaned, region)
    except phonenumbers.NumberParseException:
        parsed = None
    if parsed is not None and phonenumbers.is_possible_number(parsed):
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    # Not parseable as a real number (internal extension, service code,
    # truncated digits): keep it comparable at least.
    if cleaned.startswith("0") and len(cleaned) > 1:
        return country_prefix + cleaned[1:]
    return cleaned
