"""Both languages stay in step, and entity names come out translated."""
from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from .common import FakeBox, entity_id, make_phonebook, make_tam, make_message, setup_integration

COMPONENT = Path(__file__).parent.parent / "custom_components" / "fritzbox_phone"


def _keys(data: dict, prefix: str = "") -> set[str]:
    found: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            found |= _keys(value, f"{prefix}{key}.")
        else:
            found.add(f"{prefix}{key}")
    return found


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def test_languages_have_the_same_keys() -> None:
    english = _keys(_load("translations/en.json"))
    assert english == _keys(_load("translations/de.json"))
    assert english == _keys(_load("strings.json"))


def test_every_entity_key_has_an_icon() -> None:
    entities = _load("translations/en.json")["entity"]
    icons = _load("icons.json")["entity"]
    for domain, keys in entities.items():
        for key in keys:
            assert key in icons[domain], f"{domain}.{key} has no icon"


async def test_entity_names_are_translated(hass: HomeAssistant) -> None:
    box = FakeBox(
        tams=[make_tam([make_message(1)])],
        phonebooks=[make_phonebook(("Anna", "030123456"))],
    )
    entry = await setup_integration(hass, box)

    def name(suffix: str, domain: str = "sensor") -> str:
        return hass.states.get(entity_id(hass, entry, suffix, domain)).attributes["friendly_name"]

    assert name("call_list") == "Mock Title Call list"
    assert name("missed_calls") == "Mock Title Missed calls"
    assert name("tam_0") == "Mock Title Anrufbeantworter"  # named by the box itself
    assert name("phonebook_0") == "Mock Title Telefonbuch"
    assert name("tam_0_enabled", "switch") == "Mock Title Anrufbeantworter active"
    assert name("unread_messages", "binary_sensor") == "Mock Title Unread messages"
