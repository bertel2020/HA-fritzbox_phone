"""Call monitor: parsing, per-call state, deferred enrichment, reconnect."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.fritzbox_phone.callmonitor import (
    format_call_duration,
    parse_line,
)
from custom_components.fritzbox_phone.const import (
    CONF_ENABLE_CALLMONITOR,
    EVENT_CALL,
)
from custom_components.fritzbox_phone.logbook import _describe_call
from custom_components.fritzbox_phone.phoneblock import PhoneBlockInfo

from .common import (
    FakeBox,
    entity_id,
    get_coordinator,
    make_message,
    make_phonebook,
    make_tam,
    setup_integration,
)


async def wait_for(condition, seconds: float = 3.0) -> None:
    async def poll():
        while not condition():  # noqa: ASYNC110 - polls the effect of a thread
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), seconds)


def line(text: str):
    parsed = parse_line(text)
    assert parsed is not None, text
    return parsed


async def setup_monitor(hass: HomeAssistant, box: FakeBox | None = None):
    box = box or FakeBox()
    entry = await setup_integration(hass, box, {CONF_ENABLE_CALLMONITOR: True})
    monitor = entry.runtime_data.call_monitor
    assert monitor is not None
    await wait_for(lambda: monitor.connected)
    await hass.async_block_till_done()
    return entry, monitor


def test_parse_line() -> None:
    ring = line("24.10.26 10:00:00;RING;7;0301234567;0301111;SIP0;")
    assert (ring.kind, ring.connection_id) == ("RING", "7")
    assert ring.fields == {"from": "0301234567", "to": "0301111", "device": "SIP0"}
    assert ring.timestamp == "2026-10-24T10:00:00"

    call = line("24.10.26 10:00:00;CALL;3;1;0301111;0309999;SIP1;")
    assert call.fields == {"from": "0301111", "to": "0309999", "device": "SIP1"}

    connect = line("24.10.26 10:00:05;CONNECT;7;1;0301234567;")
    assert connect.fields == {"with": "0301234567", "device": "1"}

    disconnect = line("24.10.26 10:01:10;DISCONNECT;7;65;")
    assert disconnect.fields == {"duration": "65"}


@pytest.mark.parametrize(
    "text", ["", "garbage", "24.10.26 10:00:00;RING;7;0301", "24.10.26 10:00:00;UNKNOWN;7;a;b;c"]
)
def test_parse_line_ignores_what_it_does_not_understand(text) -> None:
    assert parse_line(text) is None


def test_format_call_duration() -> None:
    assert format_call_duration("65") == "1:05"
    assert format_call_duration("3725") == "1:02:05"
    assert format_call_duration("x") is None
    assert format_call_duration(None) is None


async def test_state_is_published_before_lookups_finish(
    hass: HomeAssistant, fake_monitor
) -> None:
    entry, monitor = await setup_monitor(hass)
    coordinator = get_coordinator(hass, entry)
    gate = asyncio.Event()

    async def slow_reverse(number):
        await gate.wait()
        from custom_components.fritzbox_phone.tellows import TellowsInfo

        return TellowsInfo("Teleshop", "Werbung", True, None, 8, 1, 1, True)

    async def spam(number):
        return PhoneBlockInfo("E_ADVERTISING", 5, 0, False, False, None, None, 90, True)

    coordinator.async_identify_caller = slow_reverse
    coordinator.async_check_phoneblock = spam
    events = async_capture_events(hass, EVENT_CALL)
    sensor = entity_id(hass, entry, "call_monitor")

    monitor.async_handle_line(line("24.10.26 10:00:00;RING;7;0301234567;0301111;SIP0;"))
    await hass.async_block_till_done()

    # Ringing is visible while the lookups are still running.
    assert hass.states.get(sensor).state == "ringing"
    assert hass.states.get(sensor).attributes.get("reverse_name") is None
    assert [event.data["enriched"] for event in events] == [False]

    gate.set()
    await wait_for(lambda: len(events) == 2)
    await hass.async_block_till_done()

    state = hass.states.get(sensor)
    assert state.state == "ringing"
    assert state.attributes["reverse_name"] == "Teleshop"
    assert state.attributes["is_spam"] is True
    assert events[1].data["enriched"] is True
    assert events[1].data["reverse_name"] == "Teleshop"
    assert "Anrufer näher bestimmt" in _describe_call(events[1])["message"]


async def test_known_contact_needs_no_online_lookup(hass: HomeAssistant, fake_monitor) -> None:
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    entry, monitor = await setup_monitor(hass, box)
    coordinator = get_coordinator(hass, entry)
    lookups = []

    async def record(number):
        lookups.append(number)

    coordinator.async_identify_caller = record
    coordinator.async_check_phoneblock = record
    monitor.async_handle_line(line("24.10.26 10:00:00;RING;7;030123456;0301111;SIP0;"))
    await hass.async_block_till_done()

    state = hass.states.get(entity_id(hass, entry, "call_monitor"))
    assert state.attributes["from_name"] == "Anna"
    assert lookups == []


async def test_simultaneous_calls_are_tracked_per_connection(
    hass: HomeAssistant, fake_monitor
) -> None:
    entry, monitor = await setup_monitor(hass)
    sensor = entity_id(hass, entry, "call_monitor")

    monitor.async_handle_line(line("24.10.26 10:00:00;RING;1;0301;0300;SIP0;"))
    monitor.async_handle_line(line("24.10.26 10:00:02;RING;2;0302;0300;SIP0;"))
    monitor.async_handle_line(line("24.10.26 10:00:03;CONNECT;2;1;0302;"))
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "talking"
    assert hass.states.get(sensor).attributes["with"] == "0302"

    # The talking call ends, but the other one is still ringing.
    monitor.async_handle_line(line("24.10.26 10:00:30;DISCONNECT;2;27;"))
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "ringing"
    assert hass.states.get(sensor).attributes["from"] == "0301"

    monitor.async_handle_line(line("24.10.26 10:00:40;DISCONNECT;1;0;"))
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "idle"


async def test_idle_state_keeps_a_call_summary(hass: HomeAssistant, fake_monitor) -> None:
    box = FakeBox(phonebooks=[make_phonebook(("Anna", "030123456"))])
    entry, monitor = await setup_monitor(hass, box)
    sensor = entity_id(hass, entry, "call_monitor")

    monitor.async_handle_line(line("24.10.26 10:00:00;RING;7;030123456;0301111;SIP0;"))
    monitor.async_handle_line(line("24.10.26 10:00:05;CONNECT;7;1;030123456;"))
    monitor.async_handle_line(line("24.10.26 10:01:10;DISCONNECT;7;65;"))
    await hass.async_block_till_done()

    attributes = hass.states.get(sensor).attributes
    assert hass.states.get(sensor).state == "idle"
    assert attributes["duration_formatted"] == "1:05"
    assert attributes["ring_duration_formatted"] == "0:05"
    assert attributes["with_name"] == "Anna"
    assert attributes["started"] == "2026-10-24T10:00:05"


async def test_lines_from_the_socket_reach_the_entities(
    hass: HomeAssistant, fake_monitor
) -> None:
    entry, monitor = await setup_monitor(hass)
    sensor = entity_id(hass, entry, "call_monitor")
    fake_monitor.instances[-1].queue.put("24.10.26 10:00:00;RING;7;0301234567;0301111;SIP0;")
    await wait_for(lambda: hass.states.get(sensor).state == "ringing")


async def test_other_entities_follow_the_call(hass: HomeAssistant, fake_monitor) -> None:
    box = FakeBox(tams=[make_tam([make_message(1)])])
    entry, monitor = await setup_monitor(hass, box)

    ringing = entity_id(hass, entry, "ringing", "binary_sensor")
    unread = entity_id(hass, entry, "unread_messages", "binary_sensor")
    call_event = entity_id(hass, entry, "call_event", "event")
    assert hass.states.get(ringing).state == "off"
    assert hass.states.get(unread).state == "on"
    assert hass.states.get(unread).attributes["count"] == 1

    monitor.async_handle_line(line("24.10.26 10:00:00;RING;7;0301234567;0301111;SIP0;"))
    await hass.async_block_till_done()
    assert hass.states.get(ringing).state == "on"
    assert hass.states.get(ringing).attributes["number"] == "0301234567"
    assert hass.states.get(call_event).attributes["event_type"] == "ringing"
    assert hass.states.get(call_event).attributes["number"] == "0301234567"

    monitor.async_handle_line(line("24.10.26 10:00:10;DISCONNECT;7;0;"))
    await hass.async_block_till_done()
    assert hass.states.get(ringing).state == "off"
    assert hass.states.get(call_event).attributes["event_type"] == "ended"


async def test_refused_connection_is_retried(hass: HomeAssistant, fake_monitor) -> None:
    fake_monitor.fail_times = 1
    entry = await setup_integration(hass, FakeBox(), {CONF_ENABLE_CALLMONITOR: True})
    monitor = entry.runtime_data.call_monitor
    await wait_for(lambda: monitor._failures == 1)
    await hass.async_block_till_done()

    sensor = entity_id(hass, entry, "call_monitor")
    assert monitor.connected is False
    assert hass.states.get(sensor).state == "unavailable"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await wait_for(lambda: monitor.connected)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "idle"


async def test_lost_connection_is_noticed_and_retried(
    hass: HomeAssistant, fake_monitor
) -> None:
    entry, monitor = await setup_monitor(hass)
    sensor = entity_id(hass, entry, "call_monitor")

    fake_monitor.instances[-1].alive = False  # FritzMonitor gave up
    await wait_for(lambda: not monitor.connected)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "unavailable"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await wait_for(lambda: monitor.connected)
    assert len(fake_monitor.instances) == 2


async def test_unload_stops_the_monitor(hass: HomeAssistant, fake_monitor) -> None:
    entry, monitor = await setup_monitor(hass)
    first = fake_monitor.instances[-1]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert first.alive is False
    assert monitor.connected is False
