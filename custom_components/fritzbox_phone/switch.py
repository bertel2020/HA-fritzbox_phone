"""Switch platform for the FRITZ!Box phone integration (answering machine on/off)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FritzBoxPhoneCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FritzBoxTamSwitch(coordinator, entry, tam.index) for tam in coordinator.data.tams
    )


class FritzBoxTamSwitch(FritzBoxPhoneEntity, SwitchEntity):
    """Enables/disables a FRITZ!Box answering machine (X_AVM-DE_TAM SetEnable)."""

    _attr_icon = "mdi:voicemail"

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
    def name(self) -> str:
        tam = self._tam
        return f"{tam.name if tam else self._tam_index} aktiv"

    @property
    def is_on(self) -> bool | None:
        tam = self._tam
        return tam.enabled if tam else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_enable(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_enable(False)

    async def _async_set_enable(self, enable: bool) -> None:
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_tam_enable, self._tam_index, enable
        )
        await self.coordinator.async_request_refresh()
