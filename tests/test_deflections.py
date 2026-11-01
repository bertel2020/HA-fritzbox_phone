"""Call forwarding rules as switches."""
from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.api import Deflection

from .common import FakeBox, entity_id, setup_integration


def _deflection(deflection_id: int, enabled: bool, to_number: str = "0171 1234567") -> Deflection:
    return Deflection(
        id=deflection_id,
        enabled=enabled,
        type="fromAssignedNumber",
        number="030 111",
        to_number=to_number,
        mode="eDeflectImmediately",
    )


async def test_deflection_switches_follow_the_box(hass: HomeAssistant) -> None:
    box = FakeBox(deflections=[_deflection(0, True), _deflection(1, False, "040 222")])
    entry = await setup_integration(hass, box)

    first = hass.states.get(entity_id(hass, entry, "deflection_0_enabled", "switch"))
    second = hass.states.get(entity_id(hass, entry, "deflection_1_enabled", "switch"))
    assert (first.state, second.state) == (STATE_ON, STATE_OFF)
    assert first.attributes["to_number"] == "0171 1234567"
    assert first.attributes["friendly_name"].endswith("Forwarding to 0171 1234567")


async def test_turning_a_deflection_off_and_on(hass: HomeAssistant) -> None:
    box = FakeBox(deflections=[_deflection(0, True)])
    entry = await setup_integration(hass, box)
    switch = entity_id(hass, entry, "deflection_0_enabled", "switch")

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert box.calls_log[-1] == ("set_deflection_enable", 0, False)
    assert hass.states.get(switch).state == STATE_OFF

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert box.calls_log[-1] == ("set_deflection_enable", 0, True)
    assert hass.states.get(switch).state == STATE_ON


async def test_a_box_without_deflections_gets_no_switch(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox())
    assert not [
        state for state in hass.states.async_all("switch") if "deflection" in state.entity_id
    ]
    assert entry.runtime_data.coordinator.data.deflections == []
