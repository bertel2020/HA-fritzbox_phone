"""Sensor platform for the FRITZ!Box phone integration."""
from __future__ import annotations

import logging
from typing import Any


from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CallEntry, Phonebook, Tam
from .callmonitor import FritzCallMonitor
from .const import (
    CONTEXT_KEY_CALL_LIST,
    CONTEXT_KEY_MISSED_CALLS,
    CONTEXT_KEY_TAM,
    MISSED_CALL_TYPE,
)
from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry
from .entity import FritzBoxPhoneEntity
from .views import recording_path

_LOGGER = logging.getLogger(__name__)

# All state comes from the coordinator (or the call monitor's own socket), so
# entities never need to be throttled against each other.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator

    entities: list[SensorEntity] = [
        FritzBoxCallListSensor(coordinator, entry),
        FritzBoxMissedCallsSensor(coordinator, entry),
    ]
    if (monitor := entry.runtime_data.call_monitor) is not None:
        entities.append(FritzBoxCallMonitorSensor(coordinator, entry, monitor))
    async_add_entities(entities)

    # Phonebooks and answering machines are discovered, not fixed at setup:
    # one that appears later (a new phonebook, a freshly configured
    # answering machine) gets its entities without a reload. One that
    # disappears stays as an unavailable entity, which the user can delete
    # in the UI - removing it automatically could drop its history over a
    # box that merely hiccuped.
    known_phonebooks: set[int] = set()
    known_tams: set[int] = set()

    @callback
    def _async_add_new_entities() -> None:
        new: list[SensorEntity] = []
        for phonebook in coordinator.data.phonebooks:
            if phonebook.id not in known_phonebooks:
                known_phonebooks.add(phonebook.id)
                new.append(FritzBoxPhonebookSensor(coordinator, entry, phonebook.id))
        for tam in coordinator.data.tams:
            if tam.index not in known_tams:
                known_tams.add(tam.index)
                new.append(FritzBoxTamSensor(coordinator, entry, tam.index))
        if new:
            async_add_entities(new)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


def _call_to_dict(call: CallEntry) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": call.type_name,
        "name": call.name,
        "caller": call.caller,
        "caller_number": call.caller_number,
        "called": call.called,
        "called_number": call.called_number,
        "device": call.device,
        "port": call.port,
        "date": call.date,
        "duration": call.duration,
        "is_fax": call.is_fax,
        "is_answering_machine": call.is_tam,
        # The recording itself is delivered by views.py; the box's session
        # id (part of the raw URL) must not end up in the state machine.
        "has_recording": call.recording_url is not None,
        "tam_index": call.tam_index,
        "tam_message_index": call.tam_message_index,
        "area_name": call.area_name,
        "is_spam": call.is_spam,
        "spam_confidence": call.spam_confidence,
        "spam_rating": call.spam_rating,
        "spam_location": call.spam_location,
        "reverse_name": call.reverse_name,
        "reverse_category": call.reverse_category,
    }


class FritzBoxCallListSensor(FritzBoxPhoneEntity, SensorEntity):
    """All calls currently in the FRITZ!Box call list (bounded by options)."""

    _attr_icon = "mdi:phone-log"
    _attr_translation_key = "call_list"
    # Whole lists in attributes outgrow the recorder's per-state size
    # limit and would be dropped there anyway; the logbook events keep
    # the history of what happened.
    _unrecorded_attributes = frozenset({"calls"})
    _context_key = CONTEXT_KEY_CALL_LIST

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_call_list"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.calls)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"calls": [_call_to_dict(call) for call in self.coordinator.data.calls]}


class FritzBoxMissedCallsSensor(FritzBoxPhoneEntity, SensorEntity):
    """Missed calls within the currently loaded call list."""

    _attr_icon = "mdi:phone-missed"
    _attr_translation_key = "missed_calls"
    _unrecorded_attributes = frozenset({"calls"})
    _context_key = CONTEXT_KEY_MISSED_CALLS

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_missed_calls"

    @property
    def _missed(self) -> list[CallEntry]:
        return [call for call in self.coordinator.data.calls if call.type == MISSED_CALL_TYPE]

    @property
    def native_value(self) -> int:
        return len(self._missed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"calls": [_call_to_dict(call) for call in self._missed]}


class FritzBoxPhonebookSensor(FritzBoxPhoneEntity, SensorEntity):
    """Number of contacts in a single FRITZ!Box phonebook, plus the full list."""

    _attr_icon = "mdi:contacts"
    _unrecorded_attributes = frozenset({"contacts"})

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, phonebook_id: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._phonebook_id = phonebook_id
        self._attr_unique_id = f"{entry.entry_id}_phonebook_{phonebook_id}"

    @property
    def _phonebook(self) -> Phonebook | None:
        return next(
            (pb for pb in self.coordinator.data.phonebooks if pb.id == self._phonebook_id),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self._phonebook is not None

    @property
    def name(self) -> str:
        phonebook = self._phonebook
        return phonebook.name if phonebook else f"Telefonbuch {self._phonebook_id}"

    @property
    def native_value(self) -> int | None:
        phonebook = self._phonebook
        return len(phonebook.contacts) if phonebook else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        phonebook = self._phonebook
        if phonebook is None:
            return {}
        return {
            "contacts": [
                {
                    "name": contact.name,
                    "vip": contact.vip,
                    "uniqueid": contact.uniqueid,
                    "has_image": contact.image_url is not None,
                    "numbers": [
                        {"number": number.number, "type": number.type}
                        for number in contact.numbers
                    ],
                }
                for contact in phonebook.contacts
            ]
        }


class FritzBoxTamSensor(FritzBoxPhoneEntity, SensorEntity):
    """New-message count and message list of a single answering machine."""

    _attr_icon = "mdi:voicemail"
    _unrecorded_attributes = frozenset({"messages"})

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, tam_index: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._tam_index = tam_index
        self._context_key = CONTEXT_KEY_TAM.format(tam_index)
        self._attr_unique_id = f"{entry.entry_id}_tam_{tam_index}"

    @property
    def _tam(self) -> Tam | None:
        return self.coordinator.get_tam(self._tam_index)

    @property
    def available(self) -> bool:
        return super().available and self._tam is not None

    @property
    def name(self) -> str:
        tam = self._tam
        return tam.name if tam else f"Anrufbeantworter {self._tam_index}"

    @property
    def native_value(self) -> int | None:
        tam = self._tam
        if tam is None:
            return None
        return sum(1 for message in tam.messages if message.new)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tam = self._tam
        if tam is None:
            return {}
        return {
            "enabled": tam.enabled,
            "running": tam.running,
            "capacity_minutes_remaining": tam.capacity_minutes,
            "total_messages": len(tam.messages),
            "messages": [
                {
                    "index": message.index,
                    "name": message.name,
                    "number": message.number,
                    "called": message.called,
                    "date": message.date,
                    "duration": message.duration,
                    "new": message.new,
                    "in_phonebook": message.inbook,
                    "has_recording": message.download_url is not None,
                    "recording_path": (
                        recording_path(self._entry.entry_id, self._tam_index, message.index)
                        if message.download_url
                        else None
                    ),
                    "area_name": message.area_name,
                    "is_spam": message.is_spam,
                    "spam_confidence": message.spam_confidence,
                    "spam_rating": message.spam_rating,
                    "spam_location": message.spam_location,
                    "reverse_name": message.reverse_name,
                    "reverse_category": message.reverse_category,
                }
                for message in tam.messages
            ],
        }

    async def async_mark_message_read(self, message_index: int, read: bool = True) -> None:
        await self._async_box_call(
            self.coordinator.client.mark_message, self._tam_index, message_index, read
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_message(self, message_index: int) -> None:
        await self._async_box_call(
            self.coordinator.client.delete_message, self._tam_index, message_index
        )
        await self.coordinator.async_request_refresh()

    async def async_download_message(self, message_index: int, filename: str) -> None:
        path = await self._async_box_call(
            self.coordinator.download_message, self._tam_index, message_index, filename
        )
        _LOGGER.info("Anrufbeantworter-Nachricht gespeichert unter %s", path)


class FritzBoxCallMonitorSensor(FritzBoxPhoneEntity, SensorEntity):
    """Live call state via the FRITZ!Box CallMonitor protocol (port 1012).

    Unlike the other sensors this does not depend on the polling
    coordinator: the FritzCallMonitor it shows keeps its own persistent
    socket connection and pushes state changes the instant the box reports
    them (ringing/dialing/talking/idle), same as Home Assistant core's
    fritzbox_callmonitor integration - but reusing this integration's own
    phonebook data for caller-ID lookup instead of a separate config entry.
    """

    _attr_icon = "mdi:phone-in-talk"
    _attr_translation_key = "call_monitor"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "ringing", "dialing", "talking"]

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        monitor: FritzCallMonitor,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_call_monitor"
        self._monitor = monitor

    @property
    def available(self) -> bool:
        # Independent of the TR-064 polling coordinator - what matters is
        # whether the monitor's own socket to the box is up.
        return self._monitor.connected

    @property
    def native_value(self) -> str:
        return self._monitor.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._monitor.attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._monitor.async_add_listener(self._handle_monitor_update))

    @callback
    def _handle_monitor_update(self, context: Context | None) -> None:
        """Write the new state under the Context of the call event.

        Sharing the Context is what lets the logbook explain the state
        change ("Was ist passiert") with the message logbook.py builds
        from the event - a state written without it shows up as
        "Für diese Aktivität wurde kein Grund festgehalten".
        """
        if context is not None:
            self.async_set_context(context)
        self.async_write_ha_state()
