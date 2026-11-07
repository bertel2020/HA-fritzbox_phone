"""Switch platform for the FRITZ!Box phone integration (answering machine, call forwarding)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import FritzBoxPhoneCoordinator
from .runtime import FritzBoxPhoneConfigEntry
from .entity import FritzBoxPhoneEntity


# Switching an answering machine is a write to the box: one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: FritzBoxPhoneConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()
    known_deflections: set[int] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_tams = [tam for tam in coordinator.data.tams if tam.index not in known]
        known.update(tam.index for tam in new_tams)
        new_deflections = [
            d for d in coordinator.data.deflections if d.id not in known_deflections
        ]
        known_deflections.update(d.id for d in new_deflections)
        entities: list[SwitchEntity] = [
            FritzBoxTamSwitch(coordinator, entry, tam.index) for tam in new_tams
        ]
        entities.extend(
            FritzBoxDeflectionSwitch(coordinator, entry, d.id) for d in new_deflections
        )
        if entities:
            async_add_entities(entities)

    _async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))


class FritzBoxTamSwitch(FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables a FRITZ!Box answering machine (X_AVM-DE_TAM SetEnable)."""

    _attr_translation_key = "tam_enabled"

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, tam_index: int
    ) -> None:
        super().__init__(coordinator, entry)
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

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_enable(False)

    async def _async_set_enable(self, enable: bool) -> None:
        await self._async_box_call(
            self.coordinator.client.set_tam_enable, self._tam_index, enable
        )
        await self.coordinator.async_request_refresh()


class FritzBoxDeflectionSwitch(FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables a call forwarding rule (X_AVM-DE_OnTel SetDeflectionEnable)."""

    _attr_translation_key = "deflection_enabled"

    def __init__(
        self, coordinator: FritzBoxPhoneCoordinator, entry: ConfigEntry, deflection_id: int
    ) -> None:
        super().__init__(coordinator, entry)
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
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enable(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_enable(False)

    async def _async_set_enable(self, enable: bool) -> None:
        await self._async_box_call(
            self.coordinator.client.set_deflection_enable, self._deflection_id, enable
        )
        await self.coordinator.async_request_refresh()
