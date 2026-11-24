"""The phone the box's dial help rings first."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import FritzBoxPhoneCoordinator
from .entity import FritzBoxPhoneEntity
from .runtime import FritzBoxPhoneConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FritzBoxPhoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FritzBoxDialPhoneSelect(entry.runtime_data.coordinator, entry)])


class FritzBoxDialPhoneSelect(FritzBoxPhoneEntity, SelectEntity):
    """Choice of the phone that rings first for a call started from here
    (X_VoIP DialSetConfig); the same setting as in Telefonie > Telefoniegeräte."""

    _attr_translation_key = "dial_phone"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: FritzBoxPhoneCoordinator, entry: FritzBoxPhoneConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_dial_phone"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.phones is not None

    @property
    def options(self) -> list[str]:
        phones = self.coordinator.data.phones
        return list(phones.dial_phones) if phones else []

    @property
    def current_option(self) -> str | None:
        phones = self.coordinator.data.phones
        # "unconfigured" is the box's word for "none chosen".
        return phones.dial_phone if phones and phones.dial_phone in phones.dial_phones else None

    async def async_select_option(self, option: str) -> None:
        await self._async_box_call(self.coordinator.client.set_dial_phone, option)
        self.coordinator.invalidate_phones()
        await self.coordinator.async_request_refresh()
