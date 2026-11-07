"""Sensor platform for the FRITZ!Box phone integration."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .api import CallEntry, Phonebook, Tam
from .callmonitor import FritzCallMonitor
from .const import (
    CONF_CALL_HISTORY_DAYS,
    CONF_CALL_LIST_DAYS,
    CONF_CALL_LIST_MAX,
    CONTEXT_KEY_CALL_LIST,
    CONTEXT_KEY_MISSED_CALLS,
    CONTEXT_KEY_TAM,
    DEFAULT_CALL_HISTORY_DAYS,
    DEFAULT_CALL_LIST_DAYS,
    DEFAULT_CALL_LIST_MAX,
    DOMAIN,
    MISSED_CALL_TYPE,
    OUTGOING_CALL_TYPE,
)
from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry
from .entity import FritzBoxPhoneEntity
from .health import STATUS_ERROR, STATUS_OK, STATUS_UNKNOWN, LookupHealth
from .payloads import call_to_dict, contact_to_dict, message_to_dict
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
        FritzBoxCallsTodaySensor(coordinator, entry),
        FritzBoxTalkTimeTodaySensor(coordinator, entry),
    ]
    if (monitor := entry.runtime_data.call_monitor) is not None:
        entities.append(FritzBoxCallMonitorSensor(coordinator, entry, monitor))
    # Only the lookups that are switched on get a status sensor (a change of
    # the options reloads the entry).
    if coordinator.phoneblock is not None:
        entities.append(FritzBoxSpamCallsTodaySensor(coordinator, entry))
        entities.append(FritzBoxSpamCallsTotalSensor(coordinator, entry))
        entities.append(
            FritzBoxLookupStatusSensor(
                coordinator, entry, "phoneblock_status", coordinator.phoneblock.health
            )
        )
    if coordinator.tellows is not None:
        entities.append(
            FritzBoxLookupStatusSensor(
                coordinator, entry, "reverse_lookup_status", coordinator.tellows.health
            )
        )
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


# Kept under its old name for code that imported it from here.
_call_to_dict = call_to_dict


class FritzBoxCallListSensor(FritzBoxPhoneEntity, SensorEntity):
    """All calls currently in the FRITZ!Box call list (bounded by options)."""

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
        options = self._entry.options
        return {
            "calls": [call_to_dict(call) for call in self.coordinator.data.calls],
            # The window the box was asked for, so a dashboard can name it.
            "call_list_days": options.get(CONF_CALL_LIST_DAYS, DEFAULT_CALL_LIST_DAYS),
            "call_list_max": options.get(CONF_CALL_LIST_MAX, DEFAULT_CALL_LIST_MAX),
            "call_history_days": options.get(CONF_CALL_HISTORY_DAYS, DEFAULT_CALL_HISTORY_DAYS),
            **self._privacy_attributes,
        }


class FritzBoxMissedCallsSensor(FritzBoxPhoneEntity, SensorEntity):
    """Missed calls within the currently loaded call list."""

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
        return {"calls": [call_to_dict(call) for call in self._missed]}


_AVM_DATE_FORMAT = "%d.%m.%y %H:%M"
_TALK_TIME_CALL_TYPES = {1, 3}  # incoming and outgoing calls that were connected


def _call_date(call: CallEntry) -> date | None:
    """The day a call list entry belongs to (the box prints "07.09.26 16:10")."""
    try:
        return datetime.strptime(call.date or "", _AVM_DATE_FORMAT).date()
    except ValueError:
        return None


def _call_minutes(call: CallEntry) -> int:
    """The call list's duration is "h:mm" (minutes rounded up) - not m:ss."""
    hours, _, minutes = (call.duration or "").partition(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return 0


class _TodaySensor(FritzBoxPhoneEntity, SensorEntity):
    """Statistics over the part of the call list that falls on today.

    They can only be as complete as the call list window set in the
    options (days / maximum number of entries).
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"

    @property
    def _today(self) -> list[CallEntry]:
        today = dt_util.now().date()
        return [call for call in self.coordinator.data.calls if _call_date(call) == today]


class FritzBoxCallsTodaySensor(_TodaySensor):
    """Number of calls today, split by direction in the attributes."""

    _attr_translation_key = "calls_today"

    @property
    def native_value(self) -> int:
        return len(self._today)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        calls = self._today
        return {
            "incoming": sum(1 for call in calls if call.type == 1),
            "outgoing": sum(1 for call in calls if call.type == OUTGOING_CALL_TYPE),
            "missed": sum(1 for call in calls if call.type == MISSED_CALL_TYPE),
        }


class FritzBoxTalkTimeTodaySensor(_TodaySensor):
    """Minutes spent in connected calls today (each call rounded up by the box)."""

    _attr_translation_key = "talk_time_today"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def native_value(self) -> int:
        return sum(
            _call_minutes(call) for call in self._today if call.type in _TALK_TIME_CALL_TYPES
        )


class FritzBoxSpamCallsTodaySensor(_TodaySensor):
    """Number of calls today that PhoneBlock rated as spam."""

    _attr_translation_key = "spam_calls_today"

    @property
    def native_value(self) -> int:
        return sum(1 for call in self._today if call.is_spam)


class FritzBoxSpamCallsTotalSensor(FritzBoxPhoneEntity, RestoreSensor):
    """Spam calls seen since the sensor exists - a counter for long-term statistics.

    The call list only holds what the box still lists, so this adds up the
    calls that newly turn up as spam. What is on the list when Home
    Assistant starts is not counted again after a restart.
    """

    _attr_translation_key = "spam_calls_total"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_spam_calls_total"
        self._total = 0
        self._seen: set[str] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            try:
                self._total = int(data.native_value)
            except (TypeError, ValueError):
                pass
        self._count_new()

    def _count_new(self) -> None:
        spam = {call.id for call in self.coordinator.data.calls if call.is_spam}
        if self._seen is not None:
            self._total += len(spam - self._seen)
        self._seen = spam

    @callback
    def _handle_coordinator_update(self) -> None:
        self._count_new()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> int:
        return self._total


class FritzBoxPhonebookSensor(FritzBoxPhoneEntity, SensorEntity):
    """Number of contacts in a single FRITZ!Box phonebook, plus the full list."""

    _attr_translation_key = "phonebook"
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
    def translation_placeholders(self) -> dict[str, str]:
        phonebook = self._phonebook
        return {"name": phonebook.name if phonebook else str(self._phonebook_id)}

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
            "phonebook_id": phonebook.id,
            "contacts": [contact_to_dict(contact) for contact in phonebook.contacts],
            **self._privacy_attributes,
        }


class FritzBoxTamSensor(FritzBoxPhoneEntity, SensorEntity):
    """New-message count and message list of a single answering machine."""

    _attr_translation_key = "answering_machine"
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
    def translation_placeholders(self) -> dict[str, str]:
        tam = self._tam
        return {"name": tam.name if tam else str(self._tam_index)}

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
            "tam_index": self._tam_index,
            "enabled": tam.enabled,
            "running": tam.running,
            "capacity_minutes_remaining": tam.capacity_minutes,
            "total_messages": len(tam.messages),
            **self._privacy_attributes,
            "messages": [
                message_to_dict(
                    self._entry.entry_id,
                    self._tam_index,
                    message,
                    self.coordinator.message_key(message),
                )
                for message in tam.messages
            ],
        }

    async def async_mark_message_read(
        self, message_index: int, read: bool = True, message_key: str | None = None
    ) -> None:
        await self._async_box_call(
            self.coordinator.mark_message, self._tam_index, message_index, read, message_key
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_message(
        self, message_index: int, message_key: str | None = None
    ) -> None:
        await self._async_box_call(
            self.coordinator.delete_message, self._tam_index, message_index, message_key
        )
        await self.coordinator.async_request_refresh()

    async def async_play_message(
        self, message_index: int, media_player: str, message_key: str | None = None
    ) -> None:
        tam = self._tam
        message = next(
            (m for m in (tam.messages if tam else []) if m.index == message_index), None
        )
        if message is None or not message.download_url:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="message_not_playable",
                translation_placeholders={"index": str(message_index)},
            )
        # The key makes the recording view refuse the request if the box has
        # renumbered its messages in the meantime.
        path = recording_path(
            self._entry.entry_id,
            self._tam_index,
            message.index,
            message_key or self.coordinator.message_key(message),
        )
        try:
            base = get_url(self.hass, allow_external=False)
        except NoURLAvailableError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_internal_url"
            ) from err
        # A signed address, as the speaker has no Home Assistant login.
        url = base + async_sign_path(self.hass, path, timedelta(minutes=10))
        await self.hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": media_player,
                "media_content_id": url,
                "media_content_type": "music",
            },
            blocking=True,
            context=self._context,
        )

    async def async_download_message(
        self, message_index: int, filename: str, message_key: str | None = None
    ) -> None:
        path = await self._async_box_call(
            self.coordinator.download_message,
            self._tam_index,
            message_index,
            filename,
            message_key,
        )
        _LOGGER.info("Anrufbeantworter-Nachricht gespeichert unter %s", path)


class FritzBoxLookupStatusSensor(FritzBoxPhoneEntity, SensorEntity):
    """Whether an online lookup (PhoneBlock, Tellows) is answering.

    The lookups swallow their errors so a poll never fails because of them;
    this makes a dead service visible - e.g. rejected PhoneBlock credentials
    that would otherwise look like "no spam found". Refreshed with every
    poll. Carries no numbers: only counts, a time and the kind of error.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_OK, STATUS_ERROR, STATUS_UNKNOWN]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # A failing lookup also raises a repair issue and a log warning, so the
    # sensor is opt-in; entries that already have it keep it enabled.
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        key: str,
        health: LookupHealth,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._health = health

    @property
    def native_value(self) -> str:
        return self._health.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._health.as_dict()
        data.pop("status")
        return data


class FritzBoxCallMonitorSensor(FritzBoxPhoneEntity, SensorEntity):
    """Live call state via the FRITZ!Box CallMonitor protocol (port 1012).

    Unlike the other sensors this does not depend on the polling
    coordinator: the FritzCallMonitor it shows keeps its own persistent
    socket connection and pushes state changes the instant the box reports
    them (ringing/dialing/talking/idle), same as Home Assistant core's
    fritzbox_callmonitor integration - but reusing this integration's own
    phonebook data for caller-ID lookup instead of a separate config entry.
    """

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
