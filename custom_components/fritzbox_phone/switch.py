"""Switch platform for the FRITZ!Box phone integration (answering machine, call forwarding)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry
from .entity import FritzBoxPhoneEntity


# Switching an answering machine is a write to the box: one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    timers = TimedSwitchStore(hass)
    await timers.async_load()
    known: set[int] = set()
    known_deflections: set[int] = set()
    known_alarms: set[int] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_tams = [tam for tam in coordinator.data.tams if tam.index not in known]
        known.update(tam.index for tam in new_tams)
        new_deflections = [
            d for d in coordinator.data.deflections if d.id not in known_deflections
        ]
        known_deflections.update(d.id for d in new_deflections)
        new_alarms = [c for c in coordinator.data.alarm_clocks if c.index not in known_alarms]
        known_alarms.update(c.index for c in new_alarms)
        entities: list[SwitchEntity] = [
            FritzBoxTamSwitch(coordinator, entry, tam.index, timers) for tam in new_tams
        ]
        entities.extend(
            FritzBoxDeflectionSwitch(coordinator, entry, d.id, timers) for d in new_deflections
        )
        entities.extend(
            FritzBoxAlarmClockSwitch(coordinator, entry, c.index, timers) for c in new_alarms
        )
        if entities:
            async_add_entities(entities)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class TimedSwitchStore:
    """When a switch that was turned on for a while has to go off again.

    Kept on disk, so a restart of Home Assistant does not leave an answering
    machine or a forwarding rule on for good.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, str]] = Store(hass, 1, f"{DOMAIN}_timed_switches")
        self._expiry: dict[str, str] = {}

    async def async_load(self) -> None:
        self._expiry = await self._store.async_load() or {}

    def get(self, unique_id: str) -> datetime | None:
        raw = self._expiry.get(unique_id)
        return dt_util.parse_datetime(raw) if raw else None

    def set(self, unique_id: str, expiry: datetime | None) -> None:
        if expiry is None:
            if self._expiry.pop(unique_id, None) is None:
                return
        else:
            self._expiry[unique_id] = expiry.isoformat()
        self._store.async_delay_save(lambda: dict(self._expiry), 1)


class TimedSwitchMixin:
    """`turn_on_for`: on now, off again after a number of minutes."""

    _timers: TimedSwitchStore
    _unsub_timer: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_timer)
        if (expiry := self._timers.get(self.unique_id)) is not None:
            # Also runs a timer that ran out while Home Assistant was down.
            self._arm_timer(max(expiry, dt_util.utcnow()))

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _arm_timer(self, expiry: datetime) -> None:
        self._cancel_timer()
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, HassJob(self._async_timer_ran_out, cancel_on_shutdown=True), expiry
        )

    async def _async_timer_ran_out(self, _now: datetime) -> None:
        self._unsub_timer = None
        self._timers.set(self.unique_id, None)
        await self._async_set_enable(False)

    async def async_turn_on_for(self, minutes: int) -> None:
        await self.async_turn_on()
        expiry = dt_util.utcnow() + timedelta(minutes=minutes)
        self._timers.set(self.unique_id, expiry)
        self._arm_timer(expiry)

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Switched off by hand: the timer has nothing left to do.
        self._cancel_timer()
        self._timers.set(self.unique_id, None)
        await self._async_set_enable(False)


class FritzBoxTamSwitch(TimedSwitchMixin, FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables a FRITZ!Box answering machine (X_AVM-DE_TAM SetEnable)."""

    _attr_translation_key = "tam_enabled"

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        tam_index: int,
        timers: TimedSwitchStore,
    ) -> None:
        super().__init__(coordinator, entry)
        self._timers = timers
        self._tam_index = tam_index
        self._attr_unique_id = f"{entry.entry_id}_tam_{tam_index}_enabled"

    @property
    def _tam(self):
        return self.coordinator.get_tam(self._tam_index)

    @property
    def available(self) -> bool:
        return super().available and self._tam is not None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        tam = self._tam
        return {"name": tam.name if tam else str(self._tam_index)}

    @property
    def is_on(self) -> bool | None:
        tam = self._tam
        return tam.enabled if tam else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Ties the switch to its answering machine sensor (same tam_index).
        return {"tam_index": self._tam_index}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enable(True)

    async def _async_set_enable(self, enable: bool) -> None:
        await self._async_box_call(
            self.coordinator.client.set_tam_enable, self._tam_index, enable
        )
        await self.coordinator.async_request_refresh()


class FritzBoxDeflectionSwitch(TimedSwitchMixin, FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables a call forwarding rule (X_AVM-DE_OnTel SetDeflectionEnable)."""

    _attr_translation_key = "deflection_enabled"

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        deflection_id: int,
        timers: TimedSwitchStore,
    ) -> None:
        super().__init__(coordinator, entry)
        self._timers = timers
        self._deflection_id = deflection_id
        self._attr_unique_id = f"{entry.entry_id}_deflection_{deflection_id}_enabled"

    @property
    def _deflection(self):
        return self.coordinator.get_deflection(self._deflection_id)

    @property
    def available(self) -> bool:
        return super().available and self._deflection is not None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        deflection = self._deflection
        target = deflection.to_number if deflection and deflection.to_number else None
        return {"target": target or str(self._deflection_id + 1)}

    @property
    def is_on(self) -> bool | None:
        deflection = self._deflection
        return deflection.enabled if deflection else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        deflection = self._deflection
        if deflection is None:
            return {}
        return {
            "deflection_id": deflection.id,
            "type": deflection.type,
            "number": deflection.number,
            "to_number": deflection.to_number,
            "mode": deflection.mode,
            "outgoing": deflection.outgoing,
            "phonebook_id": deflection.phonebook_id,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enable(True)

    async def _async_set_enable(self, enable: bool) -> None:
        await self._async_box_call(
            self.coordinator.client.set_deflection_enable, self._deflection_id, enable
        )
        await self.coordinator.async_request_refresh()


class FritzBoxAlarmClockSwitch(TimedSwitchMixin, FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables an alarm clock (X_VoIP SetAlarmClockEnable)."""

    _attr_translation_key = "alarm_clock_enabled"

    def __init__(
        self,
        coordinator: FritzBoxPhoneCoordinator,
        entry: ConfigEntry,
        index: int,
        timers: TimedSwitchStore,
    ) -> None:
        super().__init__(coordinator, entry)
        self._timers = timers
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_alarm_clock_{index}_enabled"

    @property
    def _clock(self):
        return self.coordinator.get_alarm_clock(self._index)

    @property
    def available(self) -> bool:
        return super().available and self._clock is not None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        clock = self._clock
        return {"name": clock.name if clock and clock.name else str(self._index + 1)}

    @property
    def is_on(self) -> bool | None:
        clock = self._clock
        return clock.enabled if clock else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        clock = self._clock
        if clock is None:
            return {}
        return {
            "alarm_clock_index": clock.index,
            "time": clock.time,
            "weekdays": clock.weekdays,
            "phone_name": clock.phone_name,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enable(True)

    async def _async_set_enable(self, enable: bool) -> None:
        await self._async_box_call(
            self.coordinator.client.set_alarm_clock_enable, self._index, enable
        )
        await self.coordinator.async_request_refresh()
