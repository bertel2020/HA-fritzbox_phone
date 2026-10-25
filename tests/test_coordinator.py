"""Coordinator: failed polls must not look like empty data."""
from __future__ import annotations

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
)
import requests

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.fritzbox_phone.const import (
    DOMAIN,
    EVENT_CALL_LIST_CHANGED,
    EVENT_MISSED_CALL,
)

from .common import FakeBox, get_coordinator, make_call, setup_integration


async def test_failed_poll_keeps_data_and_fires_no_events(hass: HomeAssistant) -> None:
    box = FakeBox(calls=[make_call("1"), make_call("2", call_type=2)])
    entry = await setup_integration(hass, box)
    coordinator = get_coordinator(hass, entry)
    list_events = async_capture_events(hass, EVENT_CALL_LIST_CHANGED)
    missed_events = async_capture_events(hass, EVENT_MISSED_CALL)

    for error in (
        FritzConnectionException("boom"),
        requests.ReadTimeout("slow"),
        OSError("gone"),
    ):
        box.poll_error = error
        await coordinator.async_refresh()
        assert coordinator.last_update_success is False
        assert len(coordinator.data.calls) == 2  # last good data survives

    box.poll_error = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success is True
    assert list_events == []
    assert missed_events == []


async def test_new_call_after_recovery_fires_one_event(hass: HomeAssistant) -> None:
    box = FakeBox(calls=[make_call("1")])
    entry = await setup_integration(hass, box)
    coordinator = get_coordinator(hass, entry)
    events = async_capture_events(hass, EVENT_CALL_LIST_CHANGED)

    box.poll_error = FritzConnectionException("boom")
    await coordinator.async_refresh()
    box.poll_error = None
    box.calls = [make_call("2"), make_call("1")]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["added_count"] == 1


async def test_auth_error_during_poll_starts_reauth(hass: HomeAssistant) -> None:
    box = FakeBox(calls=[make_call("1")])
    entry = await setup_integration(hass, box)
    coordinator = get_coordinator(hass, entry)

    box.poll_error = FritzAuthorizationError("401")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_auth_error_at_setup_starts_reauth(hass: HomeAssistant) -> None:
    box = FakeBox(connect_error=FritzAuthorizationError("401"))
    entry = await setup_integration(hass, box)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_connection_error_at_setup_is_retried(hass: HomeAssistant) -> None:
    box = FakeBox(connect_error=requests.ConnectionError("down"))
    entry = await setup_integration(hass, box)
    assert entry.state is ConfigEntryState.SETUP_RETRY
