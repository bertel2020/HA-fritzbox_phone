"""Shared base entity for the FRITZ!Box phone integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FritzBoxPhoneCoordinator


class FritzBoxPhoneEntity(CoordinatorEntity[FritzBoxPhoneCoordinator]):
    """Base entity sharing device info across all platforms."""

    _attr_has_entity_name = True

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
