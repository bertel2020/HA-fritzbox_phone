"""Entity discovery, device info and recorder exclusions."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.fritzbox_phone.const import (
    CONF_ENABLE_CALLMONITOR,
    CONF_PER_NUMBER_SENSORS,
    DOMAIN,
)
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
    make_call,
    make_message,
    make_phonebook,
    make_tam,
    get_device,
    setup_integration,
)


async def test_device_info_comes_from_the_box(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, FakeBox())
    device = get_device(hass, entry)
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


async def test_call_list_per_own_number(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er

    box = FakeBox(calls=[make_call("1", called_number="0301111")])
    entry = await setup_integration(hass, box)
    registry = er.async_get(hass)

    def sensor(number: str) -> str | None:
        return registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_call_list_{number}"
        )

    # A single number needs no per-number list.
    assert sensor("0301111") is None

    box.calls = [
        make_call("1", called_number="0301111"),
        make_call("2", called_number="0302222"),
        make_call("3", 3, caller_number="0301111", called_number="0309999"),
    ]
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    first = hass.states.get(sensor("0301111"))
    assert first.state == "2"  # the incoming call and the outgoing one
    assert first.attributes["own_number"] == "0301111"
    assert hass.states.get(sensor("0302222")).state == "1"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_other_sensors_per_own_number(hass: HomeAssistant, fake_monitor) -> None:
    from homeassistant.helpers import entity_registry as er

    today = dt_util.now().strftime("%d.%m.%y %H:%M")
    box = FakeBox(
        calls=[
            make_call("1", called_number="0301111", date=today, duration="0:05"),
            make_call("2", 2, called_number="0302222", date=today),
            make_call("3", 3, caller_number="0301111", called_number="0309999", date=today),
        ],
        tams=[
            make_tam(
                [
                    make_message(1, called="0301111"),
                    make_message(2, called="0302222"),
                    make_message(3, called="0302222"),
                ]
            )
        ],
    )
    entry = await setup_integration(
        hass, box, {CONF_ENABLE_CALLMONITOR: True, CONF_PER_NUMBER_SENSORS: True}
    )
    registry = er.async_get(hass)

    def state(platform: str, base: str, number: str):
        entity = registry.async_get_entity_id(
            platform, DOMAIN, f"{entry.entry_id}_{base}_{number}"
        )
        assert entity is not None, base
        return hass.states.get(entity)

    assert state("sensor", "calls_today", "0301111").state == "2"
    assert state("sensor", "calls_today", "0302222").state == "1"
    assert state("sensor", "missed_calls", "0301111").state == "0"
    assert state("sensor", "missed_calls", "0302222").state == "1"
    assert state("sensor", "talk_time_today", "0301111").state == "6"
    assert state("sensor", "call_monitor", "0302222").state == "idle"
    assert state("binary_sensor", "ringing", "0301111").state == "off"
    assert state("binary_sensor", "unread_messages", "0301111").attributes["count"] == 1
    assert state("binary_sensor", "unread_messages", "0302222").attributes["count"] == 2
    # Spam detection is off, so there is nothing to split.
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_spam_calls_today_0301111"
        )
        is None
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
