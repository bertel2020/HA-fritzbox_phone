"""The call barring requests the client sends to the box."""
from __future__ import annotations

import threading
from xml.etree import ElementTree as ET

import pytest
from fritzconnection.core.exceptions import FritzActionError

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
            "NewOutgoing": "eAllCalls",
            "NewPhonebookID": 0,
        }

    box.call_action = call_action
    deflections = client.get_deflections()
    assert [(d.id, d.enabled, d.to_number) for d in deflections] == [
        (0, True, "0171 0"),
        (1, False, "0171 1"),
    ]
    assert (deflections[0].outgoing, deflections[0].phonebook_id) == ("eAllCalls", 0)

    client.set_deflection_enable(1, True)
    assert box.actions[-1] == (
        "SetDeflectionEnable",
        {"NewDeflectionId": 1, "NewEnable": 1},
    )


def test_voip_lines_read_number_and_status() -> None:
    client, box = _client([])

    def call_action(service, action, **arguments):
        box.actions.append((action, arguments))
        if action == "GetExistingVoIPNumbers":
            return {"NewExistingVoIPNumbers": 2}
        index = arguments["NewVoIPAccountIndex"]
        if index == 1:  # a gap in the account indices
            raise FritzActionError("713")
        return {
            "NewVoIPNumber": f"030 {index}",
            "NewVoIPPassword": "secret",
            "NewX_AVM-DE_VoIPStatus": "Registered" if index == 0 else "Unregistered",
        }

    box.call_action = call_action
    lines = client.get_voip_lines()
    assert [(x.index, x.number, x.registered) for x in lines] == [
        (0, "030 0", True),
        (2, "030 2", False),
    ]
    assert "secret" not in repr(lines)


def _phone_box(box, restore_fails: bool = False) -> None:
    config = {"phone": "Fon 1"}

    def call_action(service, action, **arguments):
        box.actions.append((action, arguments))
        if action == "X_AVM-DE_GetPhonePort":
            index = arguments["NewIndex"]
            names = {0: "Fon 1", 1: "DECT Kueche"}
            if index not in names:
                raise FritzActionError("713")
            return {"NewX_AVM-DE_PhoneName": names[index]}
        if action == "X_AVM-DE_DialGetConfig":
            return {"NewX_AVM-DE_PhoneName": config["phone"]}
        if action == "X_AVM-DE_DialSetConfig":
            config["phone"] = arguments["NewX_AVM-DE_PhoneName"]
            return {}
        if action == "GetNumberOfDectEntries":
            return {"NewNumberOfEntries": 1}
        if action == "GetGenericDectEntry":
            return {"NewName": "Kueche", "NewModel": "FRITZ!Fon C6", "NewActive": 1}
        if action == "X_AVM-DE_GetClients":
            return {
                "NewX_AVM-DE_ClientList": "<List><Item><PhoneName>Softphone</PhoneName>"
                "<OutGoingNumber>030 1</OutGoingNumber><InternalNumber>620</InternalNumber>"
                "<InComingNumbers><Item>030 1</Item><Item>030 2</Item></InComingNumbers></Item>"
                "<Item><PhoneName>Tisch</PhoneName><InComingNumbers>030 2, 030 3</InComingNumbers>"
                "</Item></List>"
            }
        return {}

    box.call_action = call_action


def test_phones_are_collected_from_all_groups() -> None:
    client, box = _client([])
    _phone_box(box)
    phones = client.get_phones()
    assert phones.dial_phones == ["Fon 1", "DECT Kueche"]
    assert phones.dial_phone == "Fon 1"
    assert phones.dect == [{"name": "Kueche", "model": "FRITZ!Fon C6", "active": True}]
    assert phones.ip == [
        {
            "name": "Softphone",
            "number": "030 1",
            "internal_number": "620",
            "incoming_numbers": ["030 1", "030 2"],
        },
        {
            "name": "Tisch",
            "number": None,
            "internal_number": None,
            "incoming_numbers": ["030 2", "030 3"],
        },
    ]


def test_dial_with_a_phone_restores_the_dial_help() -> None:
    client, box = _client([])
    _phone_box(box)
    client.dial("030 9", phone="DECT Kueche")
    sequence = [
        (a, args.get("NewX_AVM-DE_PhoneName") or args.get("NewX_AVM-DE_PhoneNumber"))
        for a, args in box.actions
        if a.startswith("X_AVM-DE_Dial")
    ]
    assert sequence == [
        ("X_AVM-DE_DialGetConfig", None),
        ("X_AVM-DE_DialSetConfig", "DECT Kueche"),
        ("X_AVM-DE_DialNumber", "030 9"),
        ("X_AVM-DE_DialSetConfig", "Fon 1"),
    ]


def test_dial_with_an_unknown_phone_is_refused() -> None:
    client, box = _client([])
    _phone_box(box)
    with pytest.raises(ValueError):
        client.dial("030 9", phone="Nope")
    assert not any(a == "X_AVM-DE_DialNumber" for a, _ in box.actions)
