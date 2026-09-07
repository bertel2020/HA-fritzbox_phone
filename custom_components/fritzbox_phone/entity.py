"""Shared base entity for the FRITZ!Box phone integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AVM",
            model="FRITZ!Box",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
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
