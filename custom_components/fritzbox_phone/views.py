"""Authenticated delivery of answering machine recordings.

Recordings used to be copied into config/www and served from /local, where
anybody on the network could fetch them without logging in. This view
streams a recording straight from the FRITZ!Box instead, behind Home
Assistant's authentication - the dashboard card obtains a short-lived
signed URL for it (auth/sign_path) so a plain <audio> element can play it.
The box's own session id never leaves the integration.
"""
from __future__ import annotations

from http import HTTPStatus
import logging

from aiohttp import web
from fritzconnection.core.exceptions import FritzConnectionException
import requests

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN, RECORDING_URL_TEMPLATE, RECORDING_URL_PATTERN

_LOGGER = logging.getLogger(__name__)


def recording_path(entry_id: str, tam_index: int, message_index: int) -> str:
    """URL path of a message's recording (needs authentication or a signature)."""
    return RECORDING_URL_TEMPLATE.format(
        entry_id=entry_id, tam_index=tam_index, message_index=message_index
    )


def audio_content_type(audio: bytes) -> str:
    """FRITZ!Box recordings are WAV; sniff the common alternatives anyway."""
    if audio[:3] == b"ID3" or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if audio[:4] == b"OggS":
        return "audio/ogg"
    return "audio/wav"


class FritzBoxRecordingView(HomeAssistantView):
    """GET /api/fritzbox_phone/recording/<entry_id>/<tam_index>/<message_index>"""

    url = RECORDING_URL_PATTERN
    name = f"api:{DOMAIN}:recording"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, tam_index: str, message_index: str
    ) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        coordinator = entry.runtime_data.coordinator
        if not (tam_index.isdigit() and message_index.isdigit()):
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        try:
            audio = await hass.async_add_executor_job(
                coordinator.fetch_recording, int(tam_index), int(message_index)
            )
        except ValueError:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        except (FritzConnectionException, requests.RequestException, OSError) as err:
            _LOGGER.debug("Aufnahme konnte nicht geladen werden: %s", err)
            return web.Response(status=HTTPStatus.BAD_GATEWAY)

        return web.Response(
            body=audio,
            content_type=audio_content_type(audio),
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )
