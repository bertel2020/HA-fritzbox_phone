"""Entity discovery, device info and recorder exclusions."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.fritzbox_phone.const import DOMAIN
from custom_components.fritzbox_phone.sensor import (
    FritzBoxCallListSensor,
    FritzBoxMissedCallsSensor,
    FritzBoxPhonebookSensor,
    FritzBoxTamSensor,
)

from .common import (
    FakeBox,
    entity_id,
    get_coordinator,
    make_message,
    make_phonebook,
    make_tam,
    setup_integration,
)


async def test_device_info_comes_from_the_box(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox())
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.manufacturer == "AVM"
    assert device.model == "FRITZ!Box 7590"
    assert device.serial_number == "ABC123"
    assert device.sw_version == "8.00"
    assert device.configuration_url == "http://fritz.box"


async def test_new_answering_machine_and_phonebook_appear_without_reload(
    hass: HomeAssistant,
) -> None:
    box = FakeBox()
    entry = await setup_integration(hass, box)
    registry = {
        "tam": (f"{entry.entry_id}_tam_0", "sensor"),
        "tam_switch": (f"{entry.entry_id}_tam_0_enabled", "switch"),
        "unread": (f"{entry.entry_id}_unread_messages", "binary_sensor"),
        "book": (f"{entry.entry_id}_phonebook_0", "sensor"),
    }

    from homeassistant.helpers import entity_registry as er

    def exists(key: str) -> bool:
        unique_id, domain = registry[key]
        return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id) is not None

    assert not any(exists(key) for key in registry)

    box.tams = [make_tam([make_message(1)])]
    box.phonebooks = [make_phonebook(("Anna", "030123456"))]
    coordinator = get_coordinator(hass, entry)
    coordinator._phonebooks_fetched -= 1000  # phonebooks refresh every 15 minutes
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert {key: exists(key) for key in registry} == dict.fromkeys(registry, True)

    assert hass.states.get(entity_id(hass, entry, "unread_messages", "binary_sensor")).state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_big_attribute_lists_stay_out_of_the_recorder() -> None:
    assert "calls" in FritzBoxCallListSensor._unrecorded_attributes
    assert "calls" in FritzBoxMissedCallsSensor._unrecorded_attributes
    assert "contacts" in FritzBoxPhonebookSensor._unrecorded_attributes
    assert "messages" in FritzBoxTamSensor._unrecorded_attributes
