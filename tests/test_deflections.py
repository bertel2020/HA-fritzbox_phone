"""Call forwarding rules as switches."""
from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.api import Deflection, Phones, VoipLine

from .common import FakeBox, entity_id, setup_integration


def _deflection(deflection_id: int, enabled: bool, to_number: str = "0171 1234567") -> Deflection:
    return Deflection(
        id=deflection_id,
        enabled=enabled,
        type="fromAssignedNumber",
        number="030 111",
        to_number=to_number,
        mode="eDeflectImmediately",
        outgoing="eAllCalls",
        phonebook_id=0,
    )


async def test_deflection_switches_follow_the_box(hass: HomeAssistant) -> None:
    box = FakeBox(deflections=[_deflection(0, True), _deflection(1, False, "040 222")])
    entry = await setup_integration(hass, box)

    first = hass.states.get(entity_id(hass, entry, "deflection_0_enabled", "switch"))
    second = hass.states.get(entity_id(hass, entry, "deflection_1_enabled", "switch"))
    assert (first.state, second.state) == (STATE_ON, STATE_OFF)
    assert first.attributes["to_number"] == "0171 1234567"
    assert (first.attributes["outgoing"], first.attributes["phonebook_id"]) == ("eAllCalls", 0)
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
    # The follow-up refresh is debounced; do not wait for it.
    await entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(switch).state == STATE_ON


async def test_a_box_without_deflections_gets_no_switch(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox())
    assert not [
        state for state in hass.states.async_all("switch") if "deflection" in state.entity_id
    ]
    assert entry.runtime_data.coordinator.data.deflections == []


async def test_line_sensors_show_the_registration(hass: HomeAssistant) -> None:
    box = FakeBox(
        voip_lines=[
            VoipLine(index=0, number="030 111", status="Registered"),
            VoipLine(index=1, number="040 222", status="Unregistered"),
        ]
    )
    entry = await setup_integration(hass, box)

    first = hass.states.get(entity_id(hass, entry, "line_0_registered", "binary_sensor"))
    second = hass.states.get(entity_id(hass, entry, "line_1_registered", "binary_sensor"))
    assert (first.state, second.state) == (STATE_ON, STATE_OFF)
    assert second.attributes["status"] == "Unregistered"
    assert first.attributes["friendly_name"].endswith("Line 030 111")


async def test_phones_sensor_lists_what_dial_can_ring(hass: HomeAssistant) -> None:
    box = FakeBox(
        phones=Phones(
            dial_phones=["Fon 1", "DECT Kueche"],
            dial_phone="Fon 1",
            dect=[{"name": "Kueche", "model": "C6", "active": True}],
        )
    )
    entry = await setup_integration(hass, box)

    state = hass.states.get(entity_id(hass, entry, "phones", "sensor"))
    assert state.state == "2"
    assert state.attributes["dial_phones"] == ["Fon 1", "DECT Kueche"]
    assert state.attributes["dect"][0]["name"] == "Kueche"
