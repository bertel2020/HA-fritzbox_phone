"""Recording downloads: size limit and the view's answer to it."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone import api
from custom_components.fritzbox_phone.api import FritzBoxPhoneClient, RecordingTooLarge

from .common import FakeBox, make_message, make_tam, setup_integration


class _Response:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        yield from self._chunks


def _client(response: _Response) -> FritzBoxPhoneClient:
    client = FritzBoxPhoneClient("fritz.box", None, "user", "pw", False)
    client.fc = SimpleNamespace(session=SimpleNamespace(get=lambda *a, **k: response))
    return client


def test_download_returns_the_body() -> None:
    response = _Response([b"RI", b"FF"])
    assert _client(response).download("http://fritz.box/rec") == b"RIFF"
    assert response.closed


def test_download_refuses_a_declared_oversize_body_without_reading_it() -> None:
    response = _Response([b"x"], {"Content-Length": str(api.MAX_RECORDING_BYTES + 1)})
    with pytest.raises(RecordingTooLarge):
        _client(response).download("http://fritz.box/rec")


def test_download_stops_reading_an_undeclared_oversize_body() -> None:
    chunk = b"x" * (api.MAX_RECORDING_BYTES // 2 + 1)
    with pytest.raises(RecordingTooLarge):
        _client(_Response([chunk, chunk, chunk])).download("http://fritz.box/rec")


async def test_view_answers_413_for_an_oversize_recording(
    hass: HomeAssistant, hass_client
) -> None:
    box = FakeBox(tams=[make_tam([make_message(3, download_url="http://fritz.box/rec")])])
    entry = await setup_integration(hass, box)
    client = await hass_client()
    with patch(
        "custom_components.fritzbox_phone.coordinator.FritzBoxPhoneCoordinator.fetch_recording",
        side_effect=RecordingTooLarge("zu groß"),
    ):
        response = await client.get(f"/api/fritzbox_phone/recording/{entry.entry_id}/0/3")
    assert response.status == 413
