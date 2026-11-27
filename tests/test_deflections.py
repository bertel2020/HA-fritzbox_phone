"""Call forwarding rules as switches."""
from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.exceptions import ServiceValidationError
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.fritzbox_phone.api import Deflection, Phones, VoipLine

from .common import FakeBox, entity_id, get_coordinator, setup_integration


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


async def test_turn_on_for_switches_off_again(hass: HomeAssistant) -> None:
    box = FakeBox(deflections=[_deflection(0, False)])
    entry = await setup_integration(hass, box)
    switch = entity_id(hass, entry, "deflection_0_enabled", "switch")

    await hass.services.async_call(
        "fritzbox_phone", "turn_on_for", {"entity_id": switch, "minutes": 30}, blocking=True
    )
    assert box.calls_log[-1] == ("set_deflection_enable", 0, True)
    # the switch tells when the timer ends, so a panel can show it
    end = dt_util.parse_datetime(hass.states.get(switch).attributes["turn_off_at"])
    assert timedelta(minutes=29) < end - dt_util.utcnow() <= timedelta(minutes=30)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert box.calls_log[-1] == ("set_deflection_enable", 0, False)
    assert "turn_off_at" not in hass.states.get(switch).attributes


async def test_switching_off_by_hand_cancels_the_timer(hass: HomeAssistant) -> None:
    box = FakeBox(deflections=[_deflection(0, False)])
    entry = await setup_integration(hass, box)
    switch = entity_id(hass, entry, "deflection_0_enabled", "switch")

    await hass.services.async_call(
        "fritzbox_phone", "turn_on_for", {"entity_id": switch, "minutes": 30}, blocking=True
    )
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    box.calls_log.clear()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert box.calls_log == []


async def test_dial_phone_select_follows_and_sets_the_box(hass: HomeAssistant) -> None:
    box = FakeBox(phones=Phones(dial_phones=["Fon 1", "DECT Kueche"], dial_phone="unconfigured"))
    entry = await setup_integration(hass, box)
    select = entity_id(hass, entry, "dial_phone", "select")

    state = hass.states.get(select)
    assert state.state == "unknown"
    assert state.attributes["options"] == ["Fon 1", "DECT Kueche"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": select, "option": "DECT Kueche"}, blocking=True
    )
    await hass.async_block_till_done()
    assert box.calls_log[-1] == ("set_dial_phone", "DECT Kueche")
    assert hass.states.get(select).state == "DECT Kueche"


async def test_dect_handsets_get_a_sensor_each(hass: HomeAssistant) -> None:
    box = FakeBox(
        phones=Phones(
            dect=[
                {"id": "1", "name": "Kueche", "model": "C6", "active": True},
                {"id": "2", "name": "Bad", "model": None, "active": False},
            ]
        )
    )
    entry = await setup_integration(hass, box)

    kitchen = hass.states.get(entity_id(hass, entry, "dect_1", "binary_sensor"))
    bathroom = hass.states.get(entity_id(hass, entry, "dect_2", "binary_sensor"))
    assert (kitchen.state, bathroom.state) == (STATE_ON, STATE_OFF)
    assert kitchen.attributes["friendly_name"].endswith("Kueche radio link")
    assert kitchen.attributes["model"] == "C6"


async def test_handset_state_follows_every_poll(hass: HomeAssistant) -> None:
    box = FakeBox(phones=Phones(dect=[{"id": "2", "name": "Bad", "model": None, "active": False}]))
    entry = await setup_integration(hass, box)
    sensor = entity_id(hass, entry, "dect_2", "binary_sensor")
    assert hass.states.get(sensor).state == STATE_OFF

    box.phones.dect[0]["active"] = True
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == STATE_ON


async def test_hidden_phones_leave_the_choices(hass: HomeAssistant) -> None:
    from custom_components.fritzbox_phone.const import CONF_HIDDEN_PHONES

    box = FakeBox(
        phones=Phones(dial_phones=["FON1: Telefon", "FON2: Telefon", "DECT: Mobilteil 1"],
                      dial_phone="FON2: Telefon")
    )
    entry = await setup_integration(hass, box, {CONF_HIDDEN_PHONES: ["FON1: Telefon", "FON2: Telefon"]})

    sensor = hass.states.get(entity_id(hass, entry, "phones", "sensor"))
    assert sensor.attributes["dial_phones"] == ["DECT: Mobilteil 1"]
    assert get_coordinator(hass, entry).all_dial_phones == [
        "FON1: Telefon", "FON2: Telefon", "DECT: Mobilteil 1"
    ]
    select = hass.states.get(entity_id(hass, entry, "dial_phone", "select"))
    # The phone the box has chosen stays visible although it is hidden.
    assert select.attributes["options"] == ["DECT: Mobilteil 1", "FON2: Telefon"]
    assert select.state == "FON2: Telefon"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "fritzbox_phone", "dial", {"number": "030 1", "phone": "FON1: Telefon"}, blocking=True
        )
