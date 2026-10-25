"""PhoneBlock / Tellows clients, the lookup cache and coordinator enrichment."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.fritzbox_phone import cache as cache_module
from custom_components.fritzbox_phone.cache import LookupCache
from custom_components.fritzbox_phone.const import (
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
    CONF_REVERSE_LOOKUP_ENABLED,
)
from custom_components.fritzbox_phone.phoneblock import API_URL as PHONEBLOCK_URL
from custom_components.fritzbox_phone.phoneblock import PhoneBlockClient
from custom_components.fritzbox_phone.tellows import MAX_RESPONSE_BYTES, TellowsClient

from .common import FakeBox, get_coordinator, make_call, make_message, make_tam, setup_integration

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
