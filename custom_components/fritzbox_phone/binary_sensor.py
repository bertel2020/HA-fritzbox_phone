"""Binary sensors: "phone is ringing" and "unread answering machine messages"."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .callmonitor import FritzCallMonitor
from .const import CALLMONITOR_STATE_RINGING
from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity
from .runtime import FritzBoxPhoneConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FritzBoxPhoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = []
    if (monitor := entry.runtime_data.call_monitor) is not None:
        entities.append(FritzBoxRingingSensor(coordinator, entry, monitor))
    async_add_entities(entities)

    # Only meaningful with an answering machine, which may show up later.
    unread_added = False

    @callback
    def _async_add_unread_sensor() -> None:
        nonlocal unread_added
        if not unread_added and coordinator.data.tams:
            unread_added = True
            async_add_entities([FritzBoxUnreadMessagesSensor(coordinator, entry)])

    _async_add_unread_sensor()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_unread_sensor))


class FritzBoxRingingSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while a call is ringing - the simplest trigger for automations."""

    _attr_translation_key = "ringing"
    _attr_icon = "mdi:phone-ring"

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        monitor: FritzCallMonitor,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ringing"
        self._monitor = monitor

    @property
    def available(self) -> bool:
        return self._monitor.connected

    @property
    def is_on(self) -> bool:
        return self._monitor.state == CALLMONITOR_STATE_RINGING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.is_on:
            return {}
        attributes = self._monitor.attributes
        return {
            "number": attributes.get("from"),
            "name": attributes.get("from_name") or attributes.get("reverse_name"),
            "is_spam": bool(attributes.get("is_spam")),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._monitor.async_add_listener(self._handle_monitor_update))

    @callback
    def _handle_monitor_update(self, context: Context | None) -> None:
        if context is not None:
            self.async_set_context(context)
        self.async_write_ha_state()


class FritzBoxUnreadMessagesSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while any answering machine holds a message nobody has heard."""

    _attr_translation_key = "unread_messages"
    _attr_icon = "mdi:voicemail"

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_unread_messages"

    @property
    def _unread(self) -> int:
        return sum(
            1 for tam in self.coordinator.data.tams for message in tam.messages if message.new
        )

    @property
    def is_on(self) -> bool:
        return self._unread > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"count": self._unread}
