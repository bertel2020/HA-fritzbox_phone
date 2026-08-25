"""Sensor platform for the FRITZ!Box phone integration."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CallEntry, Phonebook, Tam
from .callmonitor import FritzCallMonitor
from .const import (
    ATTR_FILENAME,
    ATTR_MESSAGE_INDEX,
    ATTR_READ,
    CALLMONITOR_STATE_IDLE,
    CONF_CALLMONITOR_PORT,
    CONF_ENABLE_CALLMONITOR,
    DEFAULT_CALLMONITOR_PORT,
    DEFAULT_ENABLE_CALLMONITOR,
    DOMAIN,
    MISSED_CALL_TYPE,
    SERVICE_DELETE_MESSAGE,
    SERVICE_DOWNLOAD_MESSAGE,
    SERVICE_MARK_MESSAGE_READ,
)
from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity

_LOGGER = logging.getLogger(__name__)


def _format_call_duration(raw: str | None) -> str | None:
    """Format the CallMonitor protocol's DISCONNECT duration (whole
    seconds, exact - unlike the polled call list's rounded "hh:mm") as
    "m:ss" or "h:mm:ss"."""
    if raw is None:
        return None
    try:
        total_seconds = int(raw)
    except ValueError:
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _compute_call_start(closed: str | None, duration: str | None) -> str | None:
    """Start of the connected call (ISO timestamp), derived as
    closed - duration - CallMonitor's DISCONNECT line gives the end time
    and the exact duration, but not the start time directly."""
    if not closed or duration is None:
        return None
    try:
        closed_dt = datetime.fromisoformat(closed)
        seconds = int(duration)
    except ValueError:
        return None
    return (closed_dt - timedelta(seconds=seconds)).isoformat()


def _seconds_between(earlier: str, later: str) -> int | None:
    try:
        delta = datetime.fromisoformat(later) - datetime.fromisoformat(earlier)
    except ValueError:
        return None
    return max(0, round(delta.total_seconds()))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FritzBoxPhoneCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        FritzBoxCallListSensor(coordinator, entry),
        FritzBoxMissedCallsSensor(coordinator, entry),
    ]
    entities.extend(
        FritzBoxPhonebookSensor(coordinator, entry, phonebook.id)
        for phonebook in coordinator.data.phonebooks
    )
    entities.extend(
        FritzBoxTamSensor(coordinator, entry, tam.index) for tam in coordinator.data.tams
    )
    if entry.options.get(CONF_ENABLE_CALLMONITOR, DEFAULT_ENABLE_CALLMONITOR):
        entities.append(
            FritzBoxCallMonitorSensor(
                coordinator,
                entry,
                entry.data[CONF_HOST],
                entry.options.get(CONF_CALLMONITOR_PORT, DEFAULT_CALLMONITOR_PORT),
            )
        )
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_MARK_MESSAGE_READ,
        {
            vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
            vol.Optional(ATTR_READ, default=True): bool,
        },
        "async_mark_message_read",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_MESSAGE,
        {vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int)},
        "async_delete_message",
    )
    platform.async_register_entity_service(
        SERVICE_DOWNLOAD_MESSAGE,
        {
            vol.Required(ATTR_MESSAGE_INDEX): vol.Coerce(int),
            vol.Required(ATTR_FILENAME): str,
        },
        "async_download_message",
    )


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
        "recording_url": call.recording_url,
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
                    "image_url": contact.image_url,
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

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, tam_index: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._tam_index = tam_index
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
                    "download_url": message.download_url,
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
        await self.hass.async_add_executor_job(
            self.coordinator.client.mark_message, self._tam_index, message_index, read
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_message(self, message_index: int) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.client.delete_message, self._tam_index, message_index
        )
        await self.coordinator.async_request_refresh()

    async def async_download_message(self, message_index: int, filename: str) -> None:
        path = await self.hass.async_add_executor_job(
            self.coordinator.download_message, self._tam_index, message_index, filename
        )
        _LOGGER.info("Anrufbeantworter-Nachricht gespeichert unter %s", path)


class FritzBoxCallMonitorSensor(FritzBoxPhoneEntity, SensorEntity):
    """Live call state via the FRITZ!Box CallMonitor protocol (port 1012).

    Unlike the other sensors this does not depend on the polling
    coordinator: it keeps its own persistent socket connection and pushes
    state changes the instant the box reports them (ringing/dialing/
    talking/idle), same as Home Assistant core's fritzbox_callmonitor
    integration - but reusing this integration's own phonebook data for
    caller-ID lookup instead of a separate config entry.
    """

    _attr_icon = "mdi:phone-in-talk"
    _attr_translation_key = "call_monitor"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "ringing", "dialing", "talking"]

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, host: str, port: int
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_call_monitor"
        self._state = CALLMONITOR_STATE_IDLE
        self._attributes: dict[str, Any] = {}
        self._monitor = FritzCallMonitor(host, port, self._handle_event)

    @property
    def available(self) -> bool:
        # Independent of the TR-064 polling coordinator - the CallMonitor
        # keeps its own always-on socket connection.
        return True

    @property
    def native_value(self) -> str:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attributes

    def _handle_event(self, state: str, attributes: dict[str, Any]) -> None:
        resolved = dict(attributes)
        call_type = resolved.get("type")
        if call_type == "incoming" and resolved.get("from"):
            name, vip = self.coordinator.resolve_contact(resolved["from"])
            resolved["from_name"] = name
            resolved["vip"] = vip
            resolved["area_name"] = self.coordinator.get_area_name(resolved["from"])
            if not name:
                # Unknown caller and not (yet) ringing/answered enough to
                # matter for outgoing/connected legs - worth a spam check.
                info = self.coordinator.check_phoneblock(resolved["from"])
                if info is not None:
                    resolved["is_spam"] = info.is_spam
                    resolved["spam_confidence"] = info.spam_confidence
                    resolved["spam_rating"] = info.rating
                    resolved["spam_location"] = info.location
                reverse = self.coordinator.identify_caller(resolved["from"])
                if reverse is not None and reverse.name:
                    resolved["reverse_name"] = reverse.name
                    resolved["reverse_category"] = reverse.category
        elif call_type == "outgoing" and resolved.get("to"):
            name, vip = self.coordinator.resolve_contact(resolved["to"])
            resolved["to_name"] = name
            resolved["vip"] = vip
            resolved["area_name"] = self.coordinator.get_area_name(resolved["to"])
        elif "with" in resolved:
            # CONNECT doesn't repeat the RING/CALL event's `initiated`
            # timestamp - carry it forward so the eventual idle summary
            # can still show how long the phone rang before pickup.
            if "initiated" not in resolved and "initiated" in self._attributes:
                resolved["initiated"] = self._attributes["initiated"]
            name, vip = self.coordinator.resolve_contact(resolved["with"])
            resolved["with_name"] = name
            resolved["vip"] = vip
            resolved["area_name"] = self.coordinator.get_area_name(resolved["with"])
        elif state == CALLMONITOR_STATE_IDLE:
            # DISCONNECT only carries `duration` (exact seconds) and
            # `closed` - keep whoever the last ringing/dialing/talking
            # event resolved (name, number, device, vip, area, spam/
            # reverse-lookup fields, initiated/accepted timestamps) so the
            # final state still shows a full call summary instead of
            # losing that context the moment the call ends.
            resolved = {**self._attributes, **resolved}
            resolved["duration_formatted"] = _format_call_duration(resolved.get("duration"))
            # DISCONNECT's `duration` is exact but only covers the
            # connected/talking part of the call - `accepted` (if the call
            # was answered) is the true, direct start of that window and
            # preferred over deriving it from closed - duration.
            resolved["started"] = resolved.get("accepted") or _compute_call_start(
                resolved.get("closed"), resolved.get("duration")
            )
            if resolved.get("initiated") and resolved.get("accepted"):
                ring_seconds = _seconds_between(resolved["initiated"], resolved["accepted"])
                resolved["ring_duration_formatted"] = _format_call_duration(
                    str(ring_seconds) if ring_seconds is not None else None
                )
        self._state = state
        self._attributes = resolved
        self.schedule_update_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.hass.async_add_executor_job(self._monitor.connect)
        self.async_on_remove(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._stop_monitor)
        )

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        await self.hass.async_add_executor_job(self._monitor.disconnect)

    def _stop_monitor(self, event: Event | None = None) -> None:
        self._monitor.disconnect()
