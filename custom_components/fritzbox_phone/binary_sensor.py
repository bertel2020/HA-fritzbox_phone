"""Binary sensors: "phone is ringing" and "unread answering machine messages"."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .callmonitor import FritzCallMonitor
from .const import (
    CALLMONITOR_STATE_RINGING,
    CONF_PER_NUMBER_SENSORS,
    DEFAULT_PER_NUMBER_SENSORS,
)
from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity
from .payloads import digits, own_numbers
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

    # Ringing and unread messages per own number of the box, found in the
    # calls like the per-number sensors of the sensor platform (only with
    # more than one number; a number that has shown up keeps its sensors).
    known_numbers: set[str] = set()

    @callback
    def _async_add_number_sensors() -> None:
        if not entry.options.get(CONF_PER_NUMBER_SENSORS, DEFAULT_PER_NUMBER_SENSORS):
            return
        numbers = own_numbers(coordinator.data.calls)
        if len(numbers) <= 1 and not known_numbers:
            return
        new: list[BinarySensorEntity] = []
        for key, number in numbers.items():
            if key in known_numbers:
                continue
            known_numbers.add(key)
            if (monitor := entry.runtime_data.call_monitor) is not None:
                new.append(FritzBoxOwnNumberRingingSensor(coordinator, entry, monitor, key, number))
            if coordinator.data.tams:
                new.append(FritzBoxOwnNumberUnreadMessagesSensor(coordinator, entry, key, number))
        if new:
            async_add_entities(new)

    _async_add_number_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_number_sensors))

    # A number that is configured later gets its sensor without a reload.
    known_lines: set[int] = set()

    @callback
    def _async_add_line_sensors() -> None:
        new = [line for line in coordinator.data.voip_lines if line.index not in known_lines]
        known_lines.update(line.index for line in new)
        if new:
            async_add_entities(
                FritzBoxLineSensor(coordinator, entry, line.index) for line in new
            )

    _async_add_line_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_line_sensors))

    # A handset that is registered later gets its sensor without a reload.
    known_handsets: set[str] = set()

    @callback
    def _async_add_handset_sensors() -> None:
        phones = coordinator.data.phones
        new = [h["id"] for h in (phones.dect if phones else []) if h["id"] not in known_handsets]
        known_handsets.update(new)
        if new:
            async_add_entities(FritzBoxHandsetSensor(coordinator, entry, hid) for hid in new)

    _async_add_handset_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_handset_sensors))


class FritzBoxRingingSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while a call is ringing - the simplest trigger for automations."""

    _attr_translation_key = "ringing"

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


class FritzBoxOwnNumberRingingSensor(FritzBoxRingingSensor):
    """On while a call to one of the box's own numbers is ringing."""

    _attr_translation_key = "ringing_number"

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        monitor: FritzCallMonitor,
        key: str,
        number: str,
    ) -> None:
        super().__init__(coordinator, entry, monitor)
        self._key = key
        self._number = number
        self._attr_unique_id = f"{entry.entry_id}_ringing_{key}"

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"number": self._number}

    @property
    def is_on(self) -> bool:
        return self._monitor.view_for(self._key)[0] == CALLMONITOR_STATE_RINGING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.is_on:
            return {}
        attributes = self._monitor.view_for(self._key)[1]
        return {
            "own_number": self._number,
            "number": attributes.get("from"),
            "name": attributes.get("from_name") or attributes.get("reverse_name"),
            "is_spam": bool(attributes.get("is_spam")),
        }


class FritzBoxUnreadMessagesSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while any answering machine holds a message nobody has heard."""

    _attr_translation_key = "unread_messages"

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


class FritzBoxOwnNumberUnreadMessagesSensor(FritzBoxUnreadMessagesSensor):
    """On while an answering machine holds an unheard message left on one number."""

    _attr_translation_key = "unread_messages_number"

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, key: str, number: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._number = number
        self._attr_unique_id = f"{entry.entry_id}_unread_messages_{key}"

    @property
    def translation_placeholders(self) -> dict[str, str]:
        return {"number": self._number}

    @property
    def _unread(self) -> int:
        return sum(
            1
            for tam in self.coordinator.data.tams
            for message in tam.messages
            if message.new and digits(message.called or "") == self._key
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"own_number": self._number, "count": self._unread}


class FritzBoxLineSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while the provider accepts a telephone number of the box."""

    _attr_translation_key = "line_registered"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_line_{index}_registered"

    @property
    def _line(self):
        return self.coordinator.get_voip_line(self._index)

    @property
    def available(self) -> bool:
        return super().available and self._line is not None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        line = self._line
        return {"number": (line.number if line and line.number else str(self._index + 1))}

    @property
    def is_on(self) -> bool | None:
        line = self._line
        return line.registered if line else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        line = self._line
        if line is None:
            return {}
        return {
            "number": line.number,
            "status": line.status,
            "in_use": line.in_use,
        }


class FritzBoxHandsetSensor(FritzBoxPhoneEntity, BinarySensorEntity):
    """On while a DECT handset has a radio link to the box (in use, not just in range)."""

    _attr_translation_key = "dect_handset"

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, handset_id: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._handset_id = handset_id
        self._attr_unique_id = f"{entry.entry_id}_dect_{handset_id}"

    @property
    def _handset(self) -> dict[str, Any] | None:
        return self.coordinator.get_dect_handset(self._handset_id)

    @property
    def available(self) -> bool:
        return super().available and self._handset is not None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        handset = self._handset
        return {"name": (handset.get("name") if handset else None) or self._handset_id}

    @property
    def is_on(self) -> bool | None:
        handset = self._handset
        return bool(handset["active"]) if handset else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        handset = self._handset
        if handset is None:
            return {}
        return {"name": handset.get("name"), "model": handset.get("model"), **self._privacy_attributes}
