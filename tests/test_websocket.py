"""The websocket commands the panel reads instead of entity attributes."""

from __future__ import annotations

from dataclasses import replace

from fritzconnection.core.exceptions import FritzConnectionException, FritzServiceError
import pytest

from homeassistant.core import HomeAssistant

from custom_components.fritzbox_phone.api import Phonebook, PhonebookContact, PhonebookNumber
from custom_components.fritzbox_phone.const import (
    CONF_CALL_LIST_DAYS,
    CONF_CALL_LIST_MAX,
    CONF_PRIVACY_MODE,
    DOMAIN,
)
from custom_components.fritzbox_phone.payloads import message_id, stable_call_id

from .common import (
    FakeBox,
    entity_id,
    make_call,
    make_message,
    make_phonebook,
    make_tam,
    setup_integration,
)

NOW = "2026-01-10T11:00:00+00:00"  # 12:00 in Berlin, a Saturday


@pytest.fixture(autouse=True)
async def berlin(hass: HomeAssistant, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)


def _box() -> FakeBox:
    return FakeBox(
        calls=[
            make_call("1", 1, caller_number="030111", date="10.01.26 09:15", name="Anna"),
            make_call("2", 2, caller_number="030222", date="09.01.26 20:00"),
            make_call(
                "3", 3, caller_number="0302222", called_number="030333", date="01.01.26 18:45"
            ),
        ],
        tams=[make_tam([make_message(1), make_message(2, new=False)])],
        phonebooks=[
            Phonebook(
                id=0,
                name="Telefonbuch",
                contacts=[
                    PhonebookContact(
                        name="Anna",
                        uniqueid="7",
                        vip=True,
                        image_url="http://box/img",
                        numbers=[PhonebookNumber(number="030111", type="home")],
                    ),
                    PhonebookContact(
                        name="Bernd",
                        uniqueid="8",
                        vip=False,
                        image_url=None,
                        numbers=[PhonebookNumber(number="0171 555", type="mobile")],
                    ),
                ],
            ),
            replace(make_phonebook(("Carla", "040123")), id=2, name="Firma"),
        ],
        blocked=["0900123"],
    )


async def _ws(hass_ws_client, hass, **message):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def test_entries(hass: HomeAssistant, hass_ws_client) -> None:
    entry = await setup_integration(
        hass, _box(), {CONF_CALL_LIST_DAYS: 14, CONF_CALL_LIST_MAX: 80, CONF_PRIVACY_MODE: True}
    )
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/entries")
    assert response["success"]
    assert response["result"]["entries"] == [
        {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "host": "fritz.box",
            "serial": "ABC123",
            "loaded": True,
            "call_list_days": 14,
            "call_list_max": 80,
            "privacy_mode": True,
            "history_days": 0,
            "version": "2.2.0",
        }
    ]

    await hass.config_entries.async_unload(entry.entry_id)
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/entries")
    (listed,) = response["result"]["entries"]
    # Still known from the unique id while the entry is not loaded.
    assert (listed["loaded"], listed["serial"]) == (False, "ABC123")


@pytest.mark.parametrize(
    "command",
    ["phonebooks", "contacts", "calls", "tams", "blocklist", "stats"],
)
async def test_unknown_or_unloaded_entry_is_not_found(
    hass: HomeAssistant, hass_ws_client, command: str
) -> None:
    entry = await setup_integration(hass, _box())
    extra = {"phonebook_id": 0} if command == "contacts" else {}
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/{command}", entry_id="nope", **extra)
    assert not response["success"]
    assert response["error"]["code"] == "not_found"

    await hass.config_entries.async_unload(entry.entry_id)
    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/{command}", entry_id=entry.entry_id, **extra
    )
    assert response["error"]["code"] == "not_found"


async def test_commands_need_an_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token
) -> None:
    entry = await setup_integration(hass, _box())
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": f"{DOMAIN}/entries"},
        {"type": f"{DOMAIN}/calls", "entry_id": entry.entry_id},
        {"type": f"{DOMAIN}/blocklist", "entry_id": entry.entry_id},
    ):
        await client.send_json_auto_id(message)
        response = await client.receive_json()
        assert response["error"]["code"] == "unauthorized"


async def test_phonebooks_and_contacts(hass: HomeAssistant, hass_ws_client) -> None:
    entry = await setup_integration(hass, _box(), {CONF_PRIVACY_MODE: True})
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/phonebooks", entry_id=entry.entry_id)
    assert response["result"]["phonebooks"] == [
        {"id": 0, "name": "Telefonbuch", "count": 2},
        {"id": 2, "name": "Firma", "count": 1},
    ]

    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/contacts", entry_id=entry.entry_id, phonebook_id=0
    )
    result = response["result"]
    assert result["privacy_mode"] is True
    assert result["contacts"][0] == {
        "name": "Anna",
        "vip": True,
        "uniqueid": "7",
        "has_image": True,
        "numbers": [{"number": "030111", "type": "home"}],
    }
    assert len(result["contacts"]) == 2

    for query, names in (("bern", ["Bernd"]), ("555", ["Bernd"]), ("0301", ["Anna"]), ("x", [])):
        response = await _ws(
            hass_ws_client,
            hass,
            type=f"{DOMAIN}/contacts",
            entry_id=entry.entry_id,
            phonebook_id=0,
            query=query,
        )
        assert [c["name"] for c in response["result"]["contacts"]] == names, query

    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/contacts", entry_id=entry.entry_id, phonebook_id=9
    )
    assert response["error"]["code"] == "not_found"


async def test_add_contact_takes_the_reported_phonebook_id(
    hass: HomeAssistant, hass_ws_client
) -> None:
    box = _box()
    entry = await setup_integration(hass, box)
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/phonebooks", entry_id=entry.entry_id)
    phonebook_id = response["result"]["phonebooks"][1]["id"]
    await hass.services.async_call(
        DOMAIN,
        "add_contact",
        {"number": "089 1234", "name": "Dora", "phonebook_id": phonebook_id},
        blocking=True,
    )
    assert ("add_contact", "089 1234", "Dora", 2) in box.calls_log


async def test_calls_from_the_list(hass: HomeAssistant, hass_ws_client) -> None:
    box = _box()
    entry = await setup_integration(hass, box, {CONF_CALL_LIST_DAYS: 30, CONF_PRIVACY_MODE: True})
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/calls", entry_id=entry.entry_id)
    result = response["result"]
    assert result["privacy_mode"] is True
    assert result["total"] == 3
    assert result["window"] == {
        "days": 30,
        "max": 50,
        "offset": 0,
        "oldest": "2026-01-01T18:45:00+01:00",
        "source": "list",
    }
    first = result["calls"][0]
    assert first["id"] == stable_call_id(box.calls[0])
    assert first["box_id"] == "1"
    assert first["datetime"] == "2026-01-10T09:15:00+01:00"
    assert (first["vip"], first["in_list"], first["name"]) == (True, True, "Anna")
    assert first["caller_number"] == "030111"  # admin only: never masked
    assert [call["box_id"] for call in result["calls"]] == ["1", "2", "3"]

    # A shorter window, and paging.
    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/calls", entry_id=entry.entry_id, days=7
    )
    assert response["result"]["total"] == 2
    response = await _ws(
        hass_ws_client,
        hass,
        type=f"{DOMAIN}/calls",
        entry_id=entry.entry_id,
        limit=1,
        offset=1,
    )
    assert [c["box_id"] for c in response["result"]["calls"]] == ["2"]
    assert response["result"]["total"] == 3

    # Without the history even a long window stays with the list.
    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/calls", entry_id=entry.entry_id, days=365
    )
    assert response["result"]["window"]["source"] == "list"


async def test_tams(hass: HomeAssistant, hass_ws_client) -> None:
    entry = await setup_integration(hass, _box())
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/tams", entry_id=entry.entry_id)
    (tam,) = response["result"]["tams"]
    assert (tam["index"], tam["name"], tam["enabled"], tam["new_count"]) == (
        0,
        "Anrufbeantworter",
        True,
        1,
    )
    first = tam["messages"][0]
    assert first["index"] == 1
    assert first["tam_index"] == 0
    assert first["key"] == "01.01.26 10:01|030123456"
    assert first["id"] == message_id(0, first["key"])
    assert len({message["id"] for message in tam["messages"]}) == 2


async def test_blocklist(hass: HomeAssistant, hass_ws_client) -> None:
    box = _box()
    entry = await setup_integration(hass, box)
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/blocklist", entry_id=entry.entry_id)
    assert response["result"]["numbers"] == ["0900123"]
    assert response["result"]["supported"] is True

    box.blocklist_error = FritzServiceError("no call barring")
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/blocklist", entry_id=entry.entry_id)
    assert response["result"] == {"numbers": [], "entries": [], "supported": False}

    box.blocklist_error = FritzConnectionException("timeout")
    response = await _ws(hass_ws_client, hass, type=f"{DOMAIN}/blocklist", entry_id=entry.entry_id)
    assert response["error"]["code"] == "box_request_failed"


async def test_stats_from_the_list(hass: HomeAssistant, hass_ws_client) -> None:
    entry = await setup_integration(hass, _box(), {CONF_PRIVACY_MODE: True})
    response = await _ws(
        hass_ws_client, hass, type=f"{DOMAIN}/stats", entry_id=entry.entry_id, days=7
    )
    result = response["result"]
    assert result["privacy_mode"] is True
    assert result["window"]["source"] == "list"
    assert result["window"]["count"] == 2  # the outgoing call is older than 7 days
    assert result["totals"]["incoming"] == 1
    assert result["totals"]["missed"] == 1
    assert result["top_callers"][0] == {
        "number": "030111",
        "name": "Anna",
        "vip": True,
        "count": 1,
        "talk_minutes": 1,
        "spam": False,
    }


async def test_entity_attributes_for_the_panel(hass: HomeAssistant) -> None:
    entry = await setup_integration(hass, _box(), {CONF_CALL_LIST_DAYS: 14, CONF_CALL_LIST_MAX: 80})
    call_list = hass.states.get(entity_id(hass, entry, "call_list")).attributes
    assert (call_list["call_list_days"], call_list["call_list_max"]) == (14, 80)
    assert call_list["call_history_days"] == 0
    firm = hass.states.get(entity_id(hass, entry, "phonebook_2")).attributes
    assert firm["phonebook_id"] == 2
    switch = hass.states.get(entity_id(hass, entry, "tam_0_enabled", "switch")).attributes
    assert switch["tam_index"] == 0
    assert hass.states.get(entity_id(hass, entry, "tam_0")).attributes["tam_index"] == 0
