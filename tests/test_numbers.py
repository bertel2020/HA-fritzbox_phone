"""Number normalisation and phonebook matching."""
from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.numbers import normalize

from .common import FakeBox, get_coordinator, make_phonebook, setup_integration


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("030123456", "+4930123456"),
        ("+49 30 123456", "+4930123456"),
        ("0049 (30) 123-456", "+4930123456"),
        ("0171 1234567", "+491711234567"),
        ("+43 512 12345", "+4351212345"),
        ("110", "110"),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_normalize(raw, expected) -> None:
    assert normalize(raw, "DE", "+49") == expected


def test_local_number_gets_the_boxes_area_code() -> None:
    assert normalize("954934", "DE", "+49", "07527") == "+497527954934"
    # Without a known area code it must stay as it is, not be guessed.
    assert normalize("954934", "DE", "+49", None) == "954934"


async def test_contacts_match_across_spellings(hass: HomeAssistant) -> None:
    box = FakeBox(
        own_area_code="07527",
        phonebooks=[make_phonebook(("Anna", "+49 30 123456"), ("Nachbar", "07527 954934"))],
    )
    entry = await setup_integration(hass, box)
    coordinator = get_coordinator(hass, entry)

    for spelling in ("030123456", "+4930123456", "0049 30 123456"):
        assert coordinator.resolve_contact(spelling) == ("Anna", False)
    # Local-area caller, reported by the box without area code.
    assert coordinator.resolve_contact("954934") == ("Nachbar", False)
    assert coordinator.resolve_contact("0301111111") == (None, False)
    assert coordinator.resolve_contact("") == (None, False)


async def test_phonebook_is_not_downloaded_on_every_poll(hass: HomeAssistant) -> None:
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    entry = await setup_integration(hass, box)
    coordinator = get_coordinator(hass, entry)
    fetches = 0
    original = coordinator.client.get_phonebooks

    def counting():
        nonlocal fetches
        fetches += 1
        return original()

    coordinator.client.get_phonebooks = counting
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert fetches == 0

    coordinator._phonebooks_fetched -= 1000
    await coordinator.async_refresh()
    assert fetches == 1
