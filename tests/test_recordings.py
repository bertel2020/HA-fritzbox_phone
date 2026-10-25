"""Recordings: no session ids in attributes, authenticated delivery, services."""
from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.fritzbox_phone.const import DOMAIN
from custom_components.fritzbox_phone.coordinator import validate_recording_filename

from .common import (
    FakeBox,
    entity_id,
    make_call,
    make_message,
    make_tam,
    setup_integration,
)

SECRET_URL = "http://fritz.box:49000/download.lua?path=/data/tam/rec/rec.0.000&sid=SECRET123"
PATH = "/download.lua?path=/data/tam/rec/rec.0.000"


def _box() -> FakeBox:
    return FakeBox(
        calls=[
            make_call("1", port="6", is_tam=True, recording_url=SECRET_URL, path=PATH),
            make_call("2", recording_url=None),
        ],
        tams=[make_tam([make_message(3, download_url=SECRET_URL, path=PATH)])],
    )


async def test_session_id_is_not_exposed_in_attributes(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, _box())
    for suffix in ("call_list", "tam_0"):
        state = hass.states.get(entity_id(hass, entry, suffix))
        assert "SECRET123" not in str(state.attributes)
        assert "sid=" not in str(state.attributes)


async def test_calls_are_linked_to_their_message(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, _box())
    calls = hass.states.get(entity_id(hass, entry, "call_list")).attributes["calls"]
    assert (calls[0]["tam_index"], calls[0]["tam_message_index"]) == (0, 3)
    assert calls[1]["tam_message_index"] is None

    message = hass.states.get(entity_id(hass, entry, "tam_0")).attributes["messages"][0]
    assert message["recording_path"] == f"/api/fritzbox_phone/recording/{entry.entry_id}/0/3"


async def test_recording_requires_authentication(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry = await setup_integration(hass, _box())
    client = await hass_client_no_auth()
    path = f"/api/fritzbox_phone/recording/{entry.entry_id}/0/3"
    assert (await client.get(path)).status == 401


async def test_recording_is_served_to_logged_in_users(hass: HomeAssistant, hass_client) -> None:
    entry = await setup_integration(hass, _box())
    client = await hass_client()
    response = await client.get(f"/api/fritzbox_phone/recording/{entry.entry_id}/0/3")
    assert response.status == 200
    assert response.content_type == "audio/wav"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert await response.read() == b"RIFF"


async def test_recording_works_with_signed_path(hass: HomeAssistant, hass_client_no_auth) -> None:
    entry = await setup_integration(hass, _box())
    client = await hass_client_no_auth()
    signed = async_sign_path(
        hass, f"/api/fritzbox_phone/recording/{entry.entry_id}/0/3", timedelta(minutes=5)
    )
    assert (await client.get(signed)).status == 200


async def test_unknown_recording_is_404(hass: HomeAssistant, hass_client) -> None:
    entry = await setup_integration(hass, _box())
    client = await hass_client()
    assert (await client.get(f"/api/fritzbox_phone/recording/{entry.entry_id}/0/99")).status == 404
    assert (await client.get("/api/fritzbox_phone/recording/nope/0/3")).status == 404
    assert (await client.get(f"/api/fritzbox_phone/recording/{entry.entry_id}/x/3")).status == 400


async def test_message_services_only_work_on_answering_machines(hass: HomeAssistant) -> None:
    box = _box()
    entry = await setup_integration(hass, box)

    await hass.services.async_call(
        DOMAIN,
        "mark_message_read",
        {"entity_id": entity_id(hass, entry, "tam_0"), "message_index": 3},
        blocking=True,
    )
    assert ("mark_message", 0, 3, True) in box.calls_log

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "delete_message",
            {"entity_id": entity_id(hass, entry, "call_list"), "message_index": 3},
            blocking=True,
        )
    assert not any(call[0] == "delete_message" for call in box.calls_log)


@pytest.mark.parametrize(
    "name", ["../evil.wav", "/etc/passwd.wav", "", "..", ".hidden.wav", "page.html", "a/b.wav"]
)
def test_filename_validation_rejects(name) -> None:
    with pytest.raises(ValueError):
        validate_recording_filename(name)


@pytest.mark.parametrize("name", ["nachricht_3.wav", "Anruf.MP3", "x.ogg"])
def test_filename_validation_accepts(name) -> None:
    assert validate_recording_filename(name) == name
