"""The card is served and announced to the frontend automatically."""
from __future__ import annotations

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager
from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.const import CARD_JS_URL

from .common import FakeBox, setup_integration


async def test_card_is_served_and_registered(hass: HomeAssistant, hass_client_no_auth) -> None:
    hass.config.components.add("frontend")
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])

    await setup_integration(hass, FakeBox())

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert [url for url in urls if url.startswith(f"{CARD_JS_URL}?v=")]

    client = await hass_client_no_auth()
    response = await client.get(CARD_JS_URL)
    assert response.status == 200
    assert "fritzbox-phone-card" in await response.text()


async def test_second_entry_does_not_register_twice(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])
    await setup_integration(hass, FakeBox())
    await setup_integration(hass, FakeBox(serial="OTHER"))
    assert len(hass.data[DATA_EXTRA_MODULE_URL].urls) == 1
