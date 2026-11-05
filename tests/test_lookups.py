"""PhoneBlock / Tellows clients, the lookup cache and coordinator enrichment."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.fritzbox_phone import cache as cache_module
from custom_components.fritzbox_phone.cache import LookupCache
from custom_components.fritzbox_phone.const import (
    DOMAIN,
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
    CONF_REVERSE_LOOKUP_ENABLED,
)
from custom_components.fritzbox_phone.phoneblock import API_URL as PHONEBLOCK_URL
from custom_components.fritzbox_phone.phoneblock import PhoneBlockClient
from custom_components.fritzbox_phone.tellows import MAX_RESPONSE_BYTES, TellowsClient

from .common import FakeBox, build_client_class, entity_id, get_coordinator, make_call, make_message, make_tam, setup_integration

TELLOWS_URL = "https://www.tellows.de/basic/num/+4930123456"
TELLOWS_XML = (
    "<tellows><score>8</score><location>Berlin</location><searches>12</searches>"
    "<comments>3</comments><numberDetails><name>Teleshop</name>"
    "<category>Werbung</category><isCompany>1</isCompany></numberDetails></tellows>"
    "\nPartner Data not correct"
)


def test_cache_expires_and_evicts(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
    cache: LookupCache[str] = LookupCache(ttl=100, failure_ttl=10, max_entries=2)

    cache.set("a", "value")
    cache.set("b", None, failed=True)
    assert cache.get("a") == (True, "value")
    assert cache.get("b") == (True, None)

    now[0] += 11  # failures are forgotten much sooner than results
    assert cache.get("b") == (False, None)
    assert cache.get("a") == (True, "value")

    cache.set("c", "x")
    cache.set("d", "y")  # over the limit: least recently used goes
    assert len(cache) == 2
    assert cache.get("a") == (False, None)

    now[0] += 101
    assert cache.get("d") == (False, None)


async def test_phoneblock_flags_spam_and_caches(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(
        PHONEBLOCK_URL,
        json={"spamConfidence": 80, "rating": "E_ADVERTISING", "location": "Berlin"},
    )
    client = PhoneBlockClient(
        async_get_clientsession(hass), "user", "pw", country_prefix="+49", spam_threshold=50
    )
    info = await client.check("+4930123456")
    assert info is not None
    assert info.is_spam and info.spam_confidence == 80 and info.rating == "E_ADVERTISING"
    await client.check("+4930123456")
    assert aioclient_mock.call_count == 1
    # Only hashes leave the house.
    assert "4930123456" not in str(aioclient_mock.mock_calls[0][1])


async def test_phoneblock_failure_is_remembered_briefly(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, status=500)
    client = PhoneBlockClient(
        async_get_clientsession(hass), "user", "pw", country_prefix="+49", spam_threshold=50
    )
    assert await client.check("+4930123456") is None
    assert await client.check("+4930123456") is None
    assert aioclient_mock.call_count == 1


async def test_phoneblock_reports_an_outage_once_and_its_recovery(
    hass: HomeAssistant, aioclient_mock, caplog
) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, status=401)
    client = PhoneBlockClient(
        async_get_clientsession(hass),
        "user",
        "pw",
        country_prefix="+49",
        spam_threshold=50,
        cache=LookupCache(failure_ttl=0),
    )
    assert client.health.status == "unknown"

    for number in ("+4930111", "+4930222"):
        await client.check(number)
    assert client.health.status == "unknown"  # two lost requests are a hiccup
    assert "Abfragen in Folge" not in caplog.text

    await client.check("+4930333")
    assert client.health.status == "error"
    assert client.health.last_error == "ClientResponseError 401"
    assert caplog.text.count("Abfragen in Folge fehlgeschlagen") == 1
    assert "Zugangsdaten" in caplog.text

    await client.check("+4930444")
    assert caplog.text.count("Abfragen in Folge fehlgeschlagen") == 1  # still only once

    aioclient_mock.clear_requests()
    aioclient_mock.get(PHONEBLOCK_URL, json={"spamConfidence": 10})
    await client.check("+4930555")
    assert client.health.status == "ok"
    assert client.health.consecutive_failures == 0
    assert "antwortet wieder" in caplog.text
    # What is kept is the kind of error, never a number.
    dump = str(client.health.as_dict())
    assert "4930" not in dump


async def test_tellows_parses_response_with_trailing_junk(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(TELLOWS_URL, text=TELLOWS_XML)
    client = TellowsClient(async_get_clientsession(hass))
    info = await client.lookup("+4930123456")
    assert info is not None
    assert (info.name, info.category, info.score, info.is_spam) == ("Teleshop", "Werbung", 8, True)


async def test_tellows_rejects_entity_bombs_and_huge_bodies(
    hass: HomeAssistant, aioclient_mock
) -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE tellows [<!ENTITY a "aaaa">'
        '<!ENTITY b "&a;&a;&a;&a;">]><tellows><score>1</score><x>&b;</x></tellows>'
    )
    aioclient_mock.get(TELLOWS_URL, text=bomb)
    client = TellowsClient(async_get_clientsession(hass))
    assert await client.lookup("+4930123456") is None

    aioclient_mock.clear_requests()
    aioclient_mock.get(TELLOWS_URL, text="<tellows>" + "x" * (MAX_RESPONSE_BYTES + 10) + "</tellows>")
    other = TellowsClient(async_get_clientsession(hass))
    assert await other.lookup("+4930123456") is None


async def test_coordinator_enriches_unknown_callers(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, json={"spamConfidence": 90, "rating": "G_FRAUD"})
    aioclient_mock.get(TELLOWS_URL, text=TELLOWS_XML)
    box = FakeBox(
        calls=[
            make_call("1", caller_number="030123456"),
            make_call("2", caller_number="030123456", name="Bekannt"),
            make_call("3", call_type=3, called_number="030123456"),
        ],
        tams=[make_tam([make_message(1, "030123456")])],
    )
    entry = await setup_integration(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "p",
            CONF_REVERSE_LOOKUP_ENABLED: True,
        },
    )
    data = get_coordinator(hass, entry).data
    unknown, known, outgoing = data.calls
    assert unknown.is_spam and unknown.spam_confidence == 90
    assert unknown.reverse_name == "Teleshop"
    assert known.spam_confidence is None and known.reverse_name is None
    assert outgoing.spam_confidence is None
    message = data.tams[0].messages[0]
    assert message.is_spam and message.reverse_name == "Teleshop"
    # Four entries, one number: one request per service.
    assert aioclient_mock.call_count == 2


async def _enable_status_sensor(hass: HomeAssistant, entry, key: str, box: FakeBox) -> None:
    """The status sensors are disabled by default; switch one on like a user would."""
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id(hass, entry, key), disabled_by=None)
    with patch(
        "custom_components.fritzbox_phone.FritzBoxPhoneClient", build_client_class(box)
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()


async def test_status_sensors_exist_only_for_enabled_lookups(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup_integration(hass, FakeBox())
    registry = er.async_get(hass)
    for key in ("phoneblock_status", "reverse_lookup_status"):
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}") is None

    other_box = FakeBox(serial="OTHER")
    entry = await setup_integration(
        hass,
        other_box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "p",
        },
    )
    assert entity_id(hass, entry, "phoneblock_status")
    assert (
        registry.async_get(entity_id(hass, entry, "phoneblock_status")).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )
    await _enable_status_sensor(hass, entry, "phoneblock_status", other_box)
    assert registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_reverse_lookup_status"
    ) is None
    sensor = hass.states.get(entity_id(hass, entry, "phoneblock_status"))
    assert sensor.state == "unknown"
    assert registry.async_get(sensor.entity_id).entity_category is EntityCategory.DIAGNOSTIC


async def test_status_sensor_shows_rejected_credentials(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, status=401)
    box = FakeBox(
        calls=[make_call(str(i), caller_number=f"03012345{i}") for i in range(3)],
    )
    entry = await setup_integration(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "wrong",
        },
    )
    await _enable_status_sensor(hass, entry, "phoneblock_status", box)
    state = hass.states.get(entity_id(hass, entry, "phoneblock_status"))
    assert state.state == "error"
    assert state.attributes["consecutive_failures"] == 3
    assert state.attributes["last_error"] == "ClientResponseError 401"
    assert "03012345" not in str(state.attributes)


async def test_rejected_credentials_raise_a_repair_that_clears_again(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, status=401)
    box = FakeBox(calls=[make_call(str(i), caller_number=f"03012345{i}") for i in range(3)])
    entry = await setup_integration(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "wrong",
        },
    )
    issue_id = f"phoneblock_credentials_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "phoneblock_credentials_rejected"
    assert issue.is_fixable is False

    coordinator = get_coordinator(hass, entry)
    coordinator.phoneblock.health.record_success()
    await coordinator.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    # and it does not outlive the entry
    coordinator.phoneblock.health.consecutive_failures = 3
    coordinator.phoneblock.health._last_status = 401
    coordinator.async_update_repairs()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    await hass.config_entries.async_unload(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_an_outage_is_not_a_credentials_repair(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(PHONEBLOCK_URL, status=503)
    box = FakeBox(calls=[make_call(str(i), caller_number=f"03012345{i}") for i in range(3)])
    entry = await setup_integration(
        hass,
        box,
        {
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "u",
            CONF_PHONEBLOCK_PASSWORD: "pw",
        },
    )
    await _enable_status_sensor(hass, entry, "phoneblock_status", box)
    assert hass.states.get(entity_id(hass, entry, "phoneblock_status")).state == "error"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"phoneblock_credentials_{entry.entry_id}") is None
