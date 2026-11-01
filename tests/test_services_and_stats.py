"""Dial / hangup / lookup services and the "today" statistics."""
from __future__ import annotations

from datetime import datetime
import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

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
    make_message,
    make_phonebook,
    make_tam,
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


async def test_block_and_unblock_number(hass: HomeAssistant) -> None:
    box = FakeBox()
    await _setup(hass, box)
    events = async_capture_events(hass, "fritzbox_phone_number_blocked")
    released = async_capture_events(hass, "fritzbox_phone_number_unblocked")

    await hass.services.async_call(
        DOMAIN, "block_number", {"number": "0900 123", "name": "Spam"}, blocking=True
    )
    assert box.blocked == ["0900 123"]
    assert box.calls_log == [("block", "0900 123", "Spam")]
    await hass.async_block_till_done()
    assert [event.data["already_blocked"] for event in events] == [False]
    assert events[0].data["number"] == "0900 123"

    # Blocking twice is reported, not repeated.
    await hass.services.async_call(DOMAIN, "block_number", {"number": "0900 123"}, blocking=True)
    await hass.async_block_till_done()
    assert box.blocked == ["0900 123"]
    assert [event.data["already_blocked"] for event in events] == [False, True]

    await hass.services.async_call(DOMAIN, "unblock_number", {"number": "0900 123"}, blocking=True)
    await hass.async_block_till_done()
    assert box.blocked == []
    assert len(released) == 1


async def test_unblocking_a_number_that_is_not_blocked_is_refused(hass: HomeAssistant) -> None:
    await _setup(hass, FakeBox())
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "unblock_number", {"number": "0900 123"}, blocking=True
        )


@pytest.mark.parametrize("number", ["", "abc", "0900;rm", "1" * 40])
async def test_block_rejects_what_is_not_a_phone_number(hass: HomeAssistant, number) -> None:
    box = FakeBox()
    await _setup(hass, box)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "block_number", {"number": number}, blocking=True)
    assert box.blocked == []


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


async def test_spam_statistics(hass: HomeAssistant, freezer, aioclient_mock) -> None:
    freezer.move_to(datetime(2026, 10, 24, 12, 0))
    aioclient_mock.get(PHONEBLOCK_URL, json={"spamConfidence": 90, "rating": "E_ADVERTISING"})
    box = FakeBox(
        calls=[
            make_call("1", 1, date="24.10.26 09:00"),
            make_call("2", 1, date="23.10.26 09:00", caller_number="040111"),
        ]
    )
    entry = await _setup(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "user",
            CONF_PHONEBLOCK_PASSWORD: "pw",
        },
    )

    today = entity_id(hass, entry, "spam_calls_today")
    total = entity_id(hass, entry, "spam_calls_total")
    assert hass.states.get(today).state == "1"
    # What the list held at the start is not counted as new.
    assert hass.states.get(total).state == "0"
    assert hass.states.get(total).attributes["state_class"] == "total_increasing"

    box.calls.append(make_call("3", 1, date="24.10.26 11:00", caller_number="0899"))
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(today).state == "2"
    assert hass.states.get(total).state == "1"

    # The same calls on the next poll are not counted again.
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(total).state == "1"


async def test_spam_statistics_need_phoneblock(hass: HomeAssistant) -> None:
    entry = await _setup(hass, FakeBox())
    registry = er.async_get(hass)
    for suffix in ("spam_calls_today", "spam_calls_total"):
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{suffix}") is None


async def test_play_message_on_a_speaker(hass: HomeAssistant) -> None:
    hass.config.internal_url = "http://ha.local:8123"
    box = FakeBox(tams=[make_tam([make_message(1, download_url="http://box/a.wav")])])
    entry = await _setup(hass, box)
    played = async_mock_service(hass, "media_player", "play_media")

    await hass.services.async_call(
        DOMAIN,
        "play_message",
        {
            "entity_id": entity_id(hass, entry, "tam_0"),
            "message_index": 1,
            "media_player": "media_player.kitchen",
        },
        blocking=True,
    )

    data = played[0].data
    assert data["entity_id"] == "media_player.kitchen"
    prefix = f"http://ha.local:8123/api/fritzbox_phone/recording/{entry.entry_id}/0/1?"
    assert data["media_content_id"].startswith(prefix)
    # Signed, because the speaker has no login; the key guards against renumbering.
    assert "authSig=" in data["media_content_id"] and "key=" in data["media_content_id"]


async def test_play_message_refuses_what_cannot_be_played(hass: HomeAssistant) -> None:
    hass.config.internal_url = "http://ha.local:8123"
    box = FakeBox(tams=[make_tam([make_message(1)])])  # no recording
    entry = await _setup(hass, box)
    played = async_mock_service(hass, "media_player", "play_media")
    target = {"media_player": "media_player.kitchen", "message_index": 1}

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "play_message", {"entity_id": entity_id(hass, entry, "tam_0"), **target}, blocking=True
        )
    with pytest.raises(ServiceValidationError):  # not an answering machine
        await hass.services.async_call(
            DOMAIN, "play_message", {"entity_id": entity_id(hass, entry, "call_list"), **target}, blocking=True
        )
    assert played == []


async def test_add_contact(hass: HomeAssistant) -> None:
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    await _setup(hass, box)

    await hass.services.async_call(
        DOMAIN, "add_contact", {"number": "040 999", "name": "  Bob  "}, blocking=True
    )
    assert box.calls_log == [("add_contact", "040 999", "Bob", 0)]

    await hass.services.async_call(
        DOMAIN,
        "add_contact",
        {"number": "040 888", "name": "Carla", "phonebook_id": 2},
        blocking=True,
    )
    assert box.calls_log[-1] == ("add_contact", "040 888", "Carla", 2)


async def test_add_contact_refuses_a_known_number_in_any_spelling(hass: HomeAssistant) -> None:
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    await _setup(hass, box)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_contact", {"number": "+49 30 123456", "name": "Anna 2"}, blocking=True
        )
    assert box.calls_log == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 65])
async def test_add_contact_needs_a_sensible_name(hass: HomeAssistant, name) -> None:
    box = FakeBox()
    await _setup(hass, box)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "add_contact", {"number": "040 999", "name": name}, blocking=True
        )
    assert box.calls_log == []
