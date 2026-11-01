"""The call barring requests the client sends to the box."""
from __future__ import annotations

import threading
from xml.etree import ElementTree as ET

from custom_components.fritzbox_phone.api import (
    FritzBoxPhoneClient,
    PhonebookContact,
    PhonebookNumber,
)


class _Box:
    def __init__(self, blocked: list[PhonebookContact]) -> None:
        self.blocked = blocked
        self.actions: list[tuple[str, dict]] = []

    def call_action(self, service: str, action: str, **arguments):
        self.actions.append((action, arguments))
        if action == "GetCallBarringList":
            return {"NewPhonebookURL": "http://box/list.xml"}
        return {}


def _client(blocked: list[PhonebookContact]) -> tuple[FritzBoxPhoneClient, _Box]:
    client = object.__new__(FritzBoxPhoneClient)
    client._lock = threading.RLock()
    box = _Box(blocked)
    client.fc = box
    client._download_phonebook = lambda url: box.blocked
    return client, box


def _entry(uniqueid: str, number: str) -> PhonebookContact:
    return PhonebookContact(
        name="x", uniqueid=uniqueid, vip=False, image_url=None, numbers=[PhonebookNumber(number=number)]
    )


def test_block_sends_a_contact_with_the_number() -> None:
    client, box = _client([])
    assert client.block_number("030 123456", "Praxis") is True
    action, arguments = box.actions[-1]
    assert action == "SetCallBarringEntry"
    contact = ET.fromstring(arguments["NewPhonebookEntryData"])
    assert contact.findtext("person/realName") == "Praxis"
    assert contact.findtext("telephony/number") == "030 123456"


def test_block_without_a_name_uses_the_number_and_escapes_markup() -> None:
    client, box = _client([])
    client.block_number("030 123456", "<b>&")
    contact = ET.fromstring(box.actions[-1][1]["NewPhonebookEntryData"])
    assert contact.findtext("person/realName") == "<b>&"
    client.block_number("030 123456")
    assert ET.fromstring(box.actions[-1][1]["NewPhonebookEntryData"]).findtext("person/realName") == "030 123456"


def test_block_skips_a_number_that_is_blocked_in_another_spelling() -> None:
    client, box = _client([_entry("7", "+49 30 123456")])
    assert client.block_number("030123456") is False
    assert all(action != "SetCallBarringEntry" for action, _ in box.actions)


def test_unblock_deletes_matching_entries_only() -> None:
    client, box = _client([_entry("7", "030123456"), _entry("8", "040999")])
    assert client.unblock_number("+4930123456") == 1
    deletes = [args for action, args in box.actions if action == "DeleteCallBarringEntryUID"]
    assert deletes == [{"NewPhonebookEntryUniqueID": "7"}]


def test_unblock_of_an_unknown_number_deletes_nothing() -> None:
    client, box = _client([_entry("8", "040999")])
    assert client.unblock_number("030123456") == 0
    assert all(action != "DeleteCallBarringEntryUID" for action, _ in box.actions)


def test_add_contact_sends_a_phonebook_entry() -> None:
    client, box = _client([])
    client.add_contact("040 999", "Bob & Co", 2)
    action, arguments = box.actions[-1]
    assert action == "SetPhonebookEntryUID"
    assert arguments["NewPhonebookID"] == 2
    contact = ET.fromstring(arguments["NewPhonebookEntryData"])
    assert contact.findtext("person/realName") == "Bob & Co"
    assert contact.findtext("telephony/number") == "040 999"


def test_deflections_are_read_one_by_one() -> None:
    client, box = _client([])

    def call_action(service, action, **arguments):
        box.actions.append((action, arguments))
        if action == "GetNumberOfDeflections":
            return {"NewNumberOfDeflections": 2}
        return {
            "NewEnable": arguments["NewDeflectionId"] == 0,
            "NewType": "fromAssignedNumber",
            "NewNumber": "030 111",
            "NewDeflectionToNumber": f"0171 {arguments['NewDeflectionId']}",
            "NewMode": "eDeflectImmediately",
        }

    box.call_action = call_action
    deflections = client.get_deflections()
    assert [(d.id, d.enabled, d.to_number) for d in deflections] == [
        (0, True, "0171 0"),
        (1, False, "0171 1"),
    ]

    client.set_deflection_enable(1, True)
    assert box.actions[-1] == (
        "SetDeflectionEnable",
        {"NewDeflectionId": 1, "NewEnable": 1},
    )
