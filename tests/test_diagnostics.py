"""Diagnostics must be useful without leaking credentials or numbers."""
from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.fritzbox_phone.const import (
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
)

from .common import FakeBox, make_call, make_message, make_phonebook, make_tam, setup_integration


async def test_diagnostics(hass: HomeAssistant, hass_client) -> None:
    box = FakeBox(
        calls=[make_call("1", caller_number="030123456", name="Anna Geheim"), make_call("2", 2)],
        tams=[make_tam([make_message(1, "030999888")])],
        phonebooks=[make_phonebook(("Anna Geheim", "030123456"))],
    )
    entry = await setup_integration(
        hass,
        box,
        {CONF_PHONEBLOCK_USERNAME: "pb-user", CONF_PHONEBLOCK_PASSWORD: "pb-secret"},
    )
    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result["coordinator"]["calls"]["total"] == 2
    assert result["coordinator"]["calls"]["by_type"] == {"incoming": 1, "missed": 1}
    assert result["coordinator"]["answering_machines"][0]["new_messages"] == 1
    assert result["coordinator"]["phonebooks"] == [{"id": 0, "contacts": 1}]
    assert result["box"]["model"] == "FRITZ!Box 7590"

    dump = json.dumps(result)
    for secret in ("secret", "pb-secret", "pb-user", "fritz.box", "030123456", "030999888", "Anna"):
        assert secret not in dump, secret
