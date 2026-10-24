"""Event entity announcing every call the CallMonitor reports."""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .callmonitor import FritzCallMonitor
from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity
from .runtime import FritzBoxPhoneConfigEntry

PARALLEL_UPDATES = 0

# "updated": the spam check / reverse lookup of a call that was already
# announced came back with something.
EVENT_TYPES = ["ringing", "dialing", "talking", "ended", "updated"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FritzBoxPhoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if (monitor := entry.runtime_data.call_monitor) is not None:
        async_add_entities([FritzBoxCallEvent(entry.runtime_data.coordinator, entry, monitor)])


class FritzBoxCallEvent(FritzBoxPhoneEntity, EventEntity):
    """Fires per call event; the payload (number, name, spam verdict, ...)
    arrives as event attributes, ready for a UI automation trigger."""

    _attr_translation_key = "call"
    _attr_icon = "mdi:phone-log"
    _attr_event_types = EVENT_TYPES

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        monitor: FritzCallMonitor,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_call_event"
        self._monitor = monitor

    @property
    def available(self) -> bool:
        return self._monitor.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._monitor.async_add_event_listener(self._handle_call_event))
        self.async_on_remove(self._monitor.async_add_listener(self._handle_availability))

    @callback
    def _handle_call_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._trigger_event(event_type, payload)
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, _context: Context | None) -> None:
        self.async_write_ha_state()
