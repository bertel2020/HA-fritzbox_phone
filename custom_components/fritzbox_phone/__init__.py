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
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, service
import voluptuous as vol
from homeassistant.helpers.typing import ConfigType

from .api import FritzBoxPhoneClient
from .callmonitor import FritzCallMonitor
from .const import (
    ATTR_FILENAME,
    ATTR_MESSAGE_INDEX,
    ATTR_READ,
    CARD_JS_FILENAME,
    CARD_JS_URL,
    CONF_CALLMONITOR_PORT,
    CONF_ENABLE_CALLMONITOR,
    CONF_USE_TLS,
    DEFAULT_CALLMONITOR_PORT,
    DEFAULT_ENABLE_CALLMONITOR,
    DOMAIN,
    SERVICE_DELETE_MESSAGE,
    SERVICE_DOWNLOAD_MESSAGE,
    SERVICE_MARK_MESSAGE_READ,
)
from .coordinator import FritzBoxPhoneCoordinator
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

    for name, schema, func in (
        (
            SERVICE_MARK_MESSAGE_READ,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Optional(ATTR_READ, default=True): bool,
            },
            "async_mark_message_read",
        ),
        (
            SERVICE_DELETE_MESSAGE,
            {vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int)},
            "async_delete_message",
        ),
        (
            SERVICE_DOWNLOAD_MESSAGE,
            {
                vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
                vol.Required(ATTR_FILENAME): str,
            },
            "async_download_message",
        ),
    ):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=SENSOR_DOMAIN,
            schema=schema,
            func=func,
        )
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
    """Serve the fritzbox-phone-card.js Lovelace card from the www/ folder.

    This only exposes the file at a stable URL; adding it as a Lovelace
    resource (Settings -> Dashboards -> Resources) is still a manual,
    one-time step, since that varies between storage- and YAML-mode
    dashboards.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_FRONTEND_REGISTERED_KEY):
        return
    js_path = Path(__file__).parent / "www" / CARD_JS_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_JS_URL, str(js_path), cache_headers=False)]
    )
    domain_data[_FRONTEND_REGISTERED_KEY] = True


async def _async_update_listener(hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
