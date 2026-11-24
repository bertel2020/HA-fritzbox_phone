"""The call barring sensor."""
from __future__ import annotations

from fritzconnection.core.exceptions import FritzActionError
from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.const import DOMAIN

from .common import FakeBox, entity_id, get_coordinator, setup_integration


async def test_blocked_numbers_sensor_lists_the_barring(hass: HomeAssistant) -> None:
    box = FakeBox(blocked=["030 111", "030 222"])
    entry = await setup_integration(hass, box)
    state = hass.states.get(entity_id(hass, entry, "blocked_numbers"))
    assert state.state == "2"
    assert state.attributes["numbers"] == ["030 111", "030 222"]
    assert state.attributes["entries"][0]["numbers"] == ["030 111"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_blocking_a_number_updates_the_sensor_at_once(hass: HomeAssistant) -> None:
    box = FakeBox(blocked=["030 111"])
    entry = await setup_integration(hass, box)
    sensor = entity_id(hass, entry, "blocked_numbers")
    box.blocked.append("030 333")
    await hass.services.async_call(DOMAIN, "unblock_number", {"number": "030 111"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).attributes["numbers"] == ["030 333"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_box_without_call_barring_gets_no_sensor(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox(blocklist_error=FritzActionError("x")))
    assert get_coordinator(hass, entry).data.blocked is None
    from homeassistant.helpers import entity_registry as er

    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_blocked_numbers"
    ) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
