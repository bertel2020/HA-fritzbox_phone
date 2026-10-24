"""The FRITZ!Box phone integration (phonebook, call list, answering machine)."""
from __future__ import annotations

import logging
from pathlib import Path

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
    FritzSecurityError,
)
import requests
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import FritzBoxPhoneClient
from .callmonitor import FritzCallMonitor
from .const import (
    CARD_JS_FILENAME,
    CARD_JS_URL,
    CONF_CALLMONITOR_PORT,
    CONF_ENABLE_CALLMONITOR,
    CONF_USE_TLS,
    DEFAULT_CALLMONITOR_PORT,
    DEFAULT_ENABLE_CALLMONITOR,
    DOMAIN,
)
from .coordinator import FritzBoxPhoneCoordinator
from .services import async_setup_services
from .runtime import FritzBoxPhoneConfigEntry, FritzBoxPhoneRuntimeData
from .views import FritzBoxRecordingView

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_FRONTEND_REGISTERED_KEY = "_frontend_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register what does not belong to a single config entry."""
    hass.http.register_view(FritzBoxRecordingView())

    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry) -> bool:
    """Set up FRITZ!Box phone from a config entry."""
    client = FritzBoxPhoneClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        use_tls=entry.data.get(CONF_USE_TLS, False),
    )
    try:
        await hass.async_add_executor_job(client.connect)
    except (FritzAuthorizationError, FritzSecurityError) as err:
        raise ConfigEntryAuthFailed(
            f"Anmeldung an der FRITZ!Box {entry.data[CONF_HOST]} abgelehnt: {err}"
        ) from err
    except (FritzConnectionException, requests.RequestException, OSError) as err:
        raise ConfigEntryNotReady(
            f"Verbindung zur FRITZ!Box {entry.data[CONF_HOST]} fehlgeschlagen: {err}"
        ) from err

    coordinator = FritzBoxPhoneCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    await _async_register_frontend_resource(hass)

    monitor = None
    if entry.options.get(CONF_ENABLE_CALLMONITOR, DEFAULT_ENABLE_CALLMONITOR):
        monitor = FritzCallMonitor(
            hass,
            entry.data[CONF_HOST],
            entry.options.get(CONF_CALLMONITOR_PORT, DEFAULT_CALLMONITOR_PORT),
            coordinator,
        )
    entry.runtime_data = FritzBoxPhoneRuntimeData(coordinator=coordinator, call_monitor=monitor)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if monitor is not None:
        # The first connection attempt must not hold up the setup: a box
        # that has the CallMonitor switched off would otherwise cost the
        # socket timeout on every start.
        entry.async_create_background_task(hass, monitor.async_start(), "call monitor start")
        entry.async_on_unload(monitor.async_stop)

        async def _stop_monitor(_event: Event) -> None:
            await monitor.async_stop()

        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_monitor))
    return True


async def _async_register_frontend_resource(hass: HomeAssistant) -> None:
    """Serve fritzbox-phone-card.js and load it in every dashboard session.

    The file is served at a stable URL and also announced to the frontend
    (add_extra_js_url), so the card is available without adding a Lovelace
    resource by hand - which also works in YAML-mode dashboards. The
    version in the URL makes browsers fetch a new card after an update.
    A resource added manually in the past keeps working; the card guards
    against being defined twice.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_FRONTEND_REGISTERED_KEY):
        return
    js_path = Path(__file__).parent / "www" / CARD_JS_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_JS_URL, str(js_path), cache_headers=False)]
    )
    # A real installation always has the frontend; headless setups (and
    # tests) do not, and have nothing to announce the card to.
    if "frontend" in hass.config.components:
        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{CARD_JS_URL}?v={version}")
    domain_data[_FRONTEND_REGISTERED_KEY] = True


async def _async_update_listener(hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
