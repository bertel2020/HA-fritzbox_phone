"""Dial / hangup / lookup services and the "today" statistics."""
from __future__ import annotations

from datetime import datetime
import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.fritzbox_phone.const import (
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
    DOMAIN,
)
from custom_components.fritzbox_phone.phoneblock import API_URL as PHONEBLOCK_URL

from .common import (
    FakeBox,
    entity_id,
    make_call,
    make_phonebook,
    setup_integration,
)


_setup = setup_integration


async def test_dial_and_hangup(hass: HomeAssistant) -> None:
    box = FakeBox()
    entry = await _setup(hass, box)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})

    await hass.services.async_call(
        DOMAIN, "dial", {"number": "030 123456", "device_id": device.id}, blocking=True
    )
    # With a single box the device is optional.
    await hass.services.async_call(DOMAIN, "hangup", {}, blocking=True)
    assert box.calls_log == [("dial", "030 123456"), ("hangup",)]


async def test_dial_accepts_entity_and_area_targets(hass: HomeAssistant) -> None:
    from homeassistant.helpers import area_registry as ar

    box = FakeBox()
    entry = await _setup(hass, box)
    sensor = entity_id(hass, entry, "call_list")
    await hass.services.async_call(DOMAIN, "dial", {"number": "1", "entity_id": sensor}, blocking=True)

    area = ar.async_get(hass).async_create("Flur")
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    await hass.services.async_call(DOMAIN, "dial", {"number": "2", "area_id": area.id}, blocking=True)
    assert box.calls_log == [("dial", "1"), ("dial", "2")]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "dial", {"number": "3", "entity_id": "sensor.nope"}, blocking=True
        )


@pytest.mark.parametrize("number", ["", "abc", "030; rm -rf /", "1" * 40, "<b>1</b>"])
async def test_dial_rejects_what_is_not_a_phone_number(hass: HomeAssistant, number) -> None:
    box = FakeBox()
    await _setup(hass, box)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "dial", {"number": number}, blocking=True)
    assert box.calls_log == []


async def test_dial_reports_a_box_error(hass: HomeAssistant) -> None:
    from fritzconnection.core.exceptions import FritzActionError

    box = FakeBox()
    entry = await _setup(hass, box)
    entry.runtime_data.coordinator.client.dial = lambda number: (_ for _ in ()).throw(
        FritzActionError("dial help is off")
    )
    with pytest.raises(HomeAssistantError, match="dial help is off"):
        await hass.services.async_call(DOMAIN, "dial", {"number": "030"}, blocking=True)


async def test_two_boxes_need_a_device(hass: HomeAssistant) -> None:
    first = FakeBox()
    await _setup(hass, first)
    await _setup(hass, FakeBox(serial="OTHER"))
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "hangup", {}, blocking=True)


async def test_lookup_number_returns_what_is_known(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, json={"spamConfidence": 70, "rating": "E_ADVERTISING"})
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    await _setup(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "p",
        },
    )
    known = await hass.services.async_call(
        DOMAIN, "lookup_number", {"number": "+49 30 123456"}, blocking=True, return_response=True
    )
    assert known["number"] == "+4930123456"
    assert known["contact"] == {"name": "Anna", "vip": False}
    assert known["area_name"] == "Berlin"
    assert known["spam"]["confidence"] == 70
    assert known["reverse_lookup"] is None  # Tellows is off


async def test_today_statistics(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(datetime(2026, 10, 24, 12, 0))
    box = FakeBox(
        calls=[
            make_call("1", 1, date="24.10.26 09:00", duration="0:07"),
            make_call("2", 3, date="24.10.26 10:00", duration="1:05"),
            make_call("3", 2, date="24.10.26 11:00", duration="0:00"),
            make_call("4", 1, date="23.10.26 09:00", duration="0:30"),
            make_call("5", 1, date="kaputt", duration=None),
        ]
    )
    entry = await _setup(hass, box)

    calls = hass.states.get(entity_id(hass, entry, "calls_today"))
    assert calls.state == "3"
    assert (calls.attributes["incoming"], calls.attributes["outgoing"]) == (1, 1)
    assert calls.attributes["missed"] == 1

    talk = hass.states.get(entity_id(hass, entry, "talk_time_today"))
    assert talk.state == "72"  # 0:07 + 1:05, the missed call counts nothing
    assert talk.attributes["unit_of_measurement"] == "min"
