"""Shared base entity for the FRITZ!Box phone integration."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fritzconnection.core.exceptions import FritzConnectionException
import requests

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USE_TLS, DOMAIN
from .coordinator import FritzBoxPhoneCoordinator


class FritzBoxPhoneEntity(CoordinatorEntity[FritzBoxPhoneCoordinator]):
    """Base entity sharing device info across all platforms."""

    _attr_has_entity_name = True

    # Subclasses that want the logbook to explain their state changes set
    # this to the key the coordinator parks the matching event Context
    # under (see FritzBoxPhoneCoordinator._async_report_changes).
    _context_key: str | None = None

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        client = coordinator.client
        scheme = "https" if entry.data.get(CONF_USE_TLS) else "http"
        self._attr_device_info = DeviceInfo(
            # Kept as the entry id (not the serial number) so existing
            # installations keep their device and its history.
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AVM",
            model=client.model_name or "FRITZ!Box",
            serial_number=client.serial_number,
            sw_version=client.software_version,
            configuration_url=f"{scheme}://{entry.data[CONF_HOST]}",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Adopt the Context of the event that explains this update.

        Home Assistant only shows a reason ("Was ist passiert") for a
        state change that shares its Context with a logbook entry, so the
        state has to be written under the Context of the event the
        coordinator fired for this very change.
        """
        if self._context_key is not None:
            if (context := self.coordinator.take_context(self._context_key)) is not None:
                self.async_set_context(context)
        super()._handle_coordinator_update()

    async def _async_box_call(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run a blocking FRITZ!Box request, reporting failures as service errors."""
        try:
            return await self.hass.async_add_executor_job(func, *args)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except (FritzConnectionException, requests.RequestException, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="box_request_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    # The answering machine services are registered for every sensor of the
    # integration (a service cannot be limited to one entity class); the
    # other sensors answer them with a clear message instead of an
    # AttributeError. FritzBoxTamSensor overrides these.

    async def async_mark_message_read(self, message_index: int, read: bool = True) -> None:
        raise self._not_an_answering_machine()

    async def async_delete_message(self, message_index: int) -> None:
        raise self._not_an_answering_machine()

    async def async_download_message(self, message_index: int, filename: str) -> None:
        raise self._not_an_answering_machine()

    @staticmethod
    def _not_an_answering_machine() -> ServiceValidationError:
        return ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_answering_machine"
        )
