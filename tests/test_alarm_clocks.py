"""Alarm clock switches."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.fritzbox_phone.api import AlarmClock

from .common import FakeBox, build_client_class, entity_id, setup_integration


def _clock(index: int, enabled: bool) -> AlarmClock:
    return AlarmClock(index, enabled, "Wecker", "0630", "mon,tue", "Fon 1")


async def test_alarm_clock_switch_follows_and_sets_the_box(hass: HomeAssistant) -> None:
    box = FakeBox(alarm_clocks=[_clock(0, True)])
    entry = await setup_integration(hass, box)
    switch = entity_id(hass, entry, "alarm_clock_0_enabled", "switch")
    # Off by default: no state until the user switches the entity on.
    registry = er.async_get(hass)
    assert registry.async_get(switch).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(switch) is None
    registry.async_update_entity(switch, disabled_by=None)
    with patch("custom_components.fritzbox_phone.FritzBoxPhoneClient", build_client_class(box)):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    state = hass.states.get(switch)
    assert state.state == "on"
    assert state.attributes["time"] == "0630"

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert box.calls_log[-1] == ("set_alarm_clock_enable", 0, False)
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert box.calls_log[-1] == ("set_alarm_clock_enable", 0, True)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_box_without_alarm_clocks_gets_no_switch(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox())
    assert not [s for s in hass.states.async_all("switch") if "alarm" in s.entity_id]
    assert await hass.config_entries.async_unload(entry.entry_id)
