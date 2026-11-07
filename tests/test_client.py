"""The TR-064 client: what it asks the box and how it reads the answers."""
from __future__ import annotations

import threading
from xml.etree import ElementTree as ET

from fritzconnection.core.exceptions import FritzActionError, FritzSecurityError
import pytest
import requests

from custom_components.fritzbox_phone import api
from custom_components.fritzbox_phone.api import FritzBoxPhoneClient, RecordingTooLarge


class _Box:
    """Answers actions from a table; a value that is an exception is raised."""

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.actions: list[tuple[str, str, dict]] = []
        self.port = 49000
        self.modelname = "FRITZ!Box 7590"
        self.session = None

    def call_action(self, service: str, action: str, **arguments):
        self.actions.append((service, action, arguments))
        answer = self.answers.get(action, {})
        if isinstance(answer, Exception):
            raise answer
        return answer


def _client(answers: dict[str, object] | None = None, xml: str | None = None, use_tls=False):
    client = FritzBoxPhoneClient("fritz.box", None, "user", "pw", use_tls)
    client.fc = _Box(answers)
    if xml is not None:
        client._xml = lambda url: ET.fromstring(xml)
    return client, client.fc


# --- connecting -----------------------------------------------------------


def test_connect_reads_serial_and_version(monkeypatch) -> None:
    box = _Box({"GetInfo": {"NewSerialNumber": "ABC", "NewSoftwareVersion": "7.57"}})
    monkeypatch.setattr(api, "FritzConnection", lambda **kwargs: box)
    client = FritzBoxPhoneClient("fritz.box", None, "user", "pw", False)
    client.connect()
    assert (client.serial_number, client.software_version) == ("ABC", "7.57")
    assert client.model_name == "FRITZ!Box 7590"


def test_connect_survives_a_user_who_may_not_read_device_info(monkeypatch) -> None:
    box = _Box({"GetInfo": FritzSecurityError("no")})
    monkeypatch.setattr(api, "FritzConnection", lambda **kwargs: box)
    client = FritzBoxPhoneClient("fritz.box", None, "user", "pw", False)
    client.connect()
    assert client.serial_number is None and client.software_version is None


def test_own_area_code() -> None:
    client, _ = _client(
        {"X_AVM-DE_GetVoIPCommonAreaCode": {"NewX_AVM-DE_OKZPrefix": "0", "NewX_AVM-DE_OKZ": "7527"}}
    )
    assert client.get_own_area_code() == "07527"
    client, _ = _client({"X_AVM-DE_GetVoIPCommonAreaCode": {}})
    assert client.get_own_area_code() is None
    client, _ = _client({"X_AVM-DE_GetVoIPCommonAreaCode": FritzActionError("x")})
    assert client.get_own_area_code() is None


# --- phonebooks -----------------------------------------------------------

PHONEBOOK = """<phonebooks><phonebook><contact>
<category>1</category><uniqueid>7</uniqueid>
<person><realName> Anna </realName><imageURL>/download.lua?path=a.jpg</imageURL></person>
<telephony><number type="home"> 030 123 </number><number type="mobile"> </number></telephony>
</contact><contact><person><realName></realName></person></contact></phonebook></phonebooks>"""


def test_phonebooks_are_read_with_contacts_and_images() -> None:
    client, box = _client(
        {
            "GetPhonebookList": {"NewPhonebookList": "0, x,1"},
            "GetPhonebook": {"NewPhonebookURL": "http://fritz.box:49000/pb.lua?sid=abc", "NewPhonebookName": ""},
        },
        PHONEBOOK,
    )
    books = client.get_phonebooks()
    assert [b.id for b in books] == [0, 1]
    assert books[0].name == "Telefonbuch 0"
    anna, nameless = books[0].contacts
    assert (anna.name, anna.vip, anna.uniqueid) == ("Anna", True, "7")
    assert [(n.number, n.type) for n in anna.numbers] == [("030 123", "home")]
    assert anna.image_url == "http://fritz.box:49000/download.lua?path=a.jpg&sid=abc"
    assert nameless.name == "?" and nameless.numbers == [] and not nameless.vip


def test_phonebooks_are_empty_when_the_box_has_none() -> None:
    client, _ = _client({"GetPhonebookList": FritzActionError("x")})
    assert client.get_phonebooks() == []
    client, _ = _client({"GetPhonebook": {}, "GetPhonebookList": {"NewPhonebookList": "0"}}, PHONEBOOK)
    assert client.get_phonebooks()[0].contacts == []


def test_add_contact_sends_a_phonebook_entry() -> None:
    client, box = _client({"SetPhonebookEntryUID": {"NewPhonebookEntryUniqueID": "42"}})
    assert client.add_contact("030 5", "Bert", 2) == "42"
    _, action, arguments = box.actions[-1]
    assert (action, arguments["NewPhonebookID"]) == ("SetPhonebookEntryUID", 2)
    contact = ET.fromstring(arguments["NewPhonebookEntryData"])
    assert contact.findtext("person/realName") == "Bert"
    assert contact.findtext("telephony/number") == "030 5"


ENTRY = (
    "<contact><category>1</category><person><realName>Maria</realName>"
    "<imageURL>/i.jpg</imageURL></person>"
    '<telephony nid="1"><number type="mobile" prio="1">0160 1</number></telephony>'
    "<mod_time>5</mod_time><uniqueid>12</uniqueid></contact>"
)


def test_add_number_to_contact_writes_the_whole_entry_back_with_its_id() -> None:
    client, box = _client(
        {
            "GetPhonebookEntryUID": {"NewPhonebookEntryData": ENTRY},
            "SetPhonebookEntryUID": {"NewPhonebookEntryUniqueID": "12"},
        }
    )
    client.add_number_to_contact("12", "030 77", "home", 2)
    assert [a for _, a, _ in box.actions] == ["GetPhonebookEntryUID", "SetPhonebookEntryUID"]
    _, _, arguments = box.actions[-1]
    assert arguments["NewPhonebookID"] == 2
    contact = ET.fromstring(arguments["NewPhonebookEntryData"])
    assert contact.findtext("uniqueid") == "12"
    assert contact.findtext("category") == "1"
    assert contact.findtext("person/imageURL") == "/i.jpg"
    assert [(n.get("type"), n.text) for n in contact.findall("telephony/number")] == [
        ("mobile", "0160 1"),
        ("home", "030 77"),
    ]
    assert contact.find("telephony").get("nid") == "2"


def test_add_number_to_contact_undoes_a_new_entry_the_box_made_instead() -> None:
    client, box = _client(
        {
            "GetPhonebookEntryUID": {"NewPhonebookEntryData": ENTRY},
            "SetPhonebookEntryUID": {"NewPhonebookEntryUniqueID": "99"},
            "DeletePhonebookEntryUID": {},
        }
    )
    with pytest.raises(FritzActionError):
        client.add_number_to_contact("12", "030 77")
    _, action, arguments = box.actions[-1]
    assert (action, arguments["NewPhonebookEntryUniqueID"]) == ("DeletePhonebookEntryUID", "99")


def test_add_number_to_contact_fails_when_the_box_has_no_such_entry() -> None:
    client, box = _client({"GetPhonebookEntryUID": {"NewPhonebookEntryData": ""}})
    with pytest.raises(FritzActionError):
        client.add_number_to_contact("12", "030 77")
    assert [a for _, a, _ in box.actions] == ["GetPhonebookEntryUID"]


# --- call list ------------------------------------------------------------

CALLS = """<root>
<Call><Id>1</Id><Type>2</Type><Caller>030 1</Caller><CallerNumber>0301</CallerNumber>
<CalledNumber>9</CalledNumber><Name>Max</Name><Device>Tel</Device><Port>40</Port>
<Date>01.01.26 10:00</Date><Duration>0:00</Duration><Count>2</Count><Path>/rec.lua?p=1</Path></Call>
<Call><Id>2</Id><Type>x</Type><Port>5</Port></Call></root>"""


def test_call_list_asks_for_days_and_maximum_and_reads_entries() -> None:
    urls: list[str] = []
    client, box = _client({"GetCallList": {"NewCallListURL": "http://b/calls.lua?sid=s1"}})
    client._xml = lambda url: (urls.append(url), ET.fromstring(CALLS))[1]
    calls = client.get_call_list(7, 100)
    assert urls == ["http://b/calls.lua?sid=s1&days=7&max=100"]
    first, second = calls
    assert (first.type_name, first.name, first.caller_number, first.is_tam, first.is_fax) == (
        "missed", "Max", "0301", True, False,
    )
    assert first.recording_url == "http://fritz.box:49000/rec.lua?p=1&sid=s1"
    assert second.type_name == "unknown" and second.is_fax and not second.is_tam


def test_call_list_without_url_or_support_is_empty() -> None:
    assert _client({"GetCallList": {}})[0].get_call_list(0, 0) == []
    assert _client({"GetCallList": FritzSecurityError("x")})[0].get_call_list(0, 0) == []


@pytest.mark.parametrize(
    ("port", "expected"),
    [("6", True), ("45", True), ("5", False), ("abc", False), (None, False), ("", False)],
)
def test_tam_ports(port, expected) -> None:
    assert FritzBoxPhoneClient._is_tam_port(port) is expected


# --- answering machine ----------------------------------------------------

TAM_LIST = """<List><TAMRunning>1</TAMRunning><Capacity>30</Capacity>
<Item><Index>0</Index><Name>AB 1</Name><Enable>1</Enable></Item>
<Item><Index>1</Index><Name> </Name></Item></List>"""
MESSAGES = """<Root><Message><Index>3</Index><Tam>0</Tam><Called>0301</Called><Number>0302</Number>
<Name>Max</Name><Date>01.01.26 10:00</Date><Duration>0:10</Duration><New>0</New><Inbook>1</Inbook>
<Path>/m.lua?x=1</Path></Message><Message><Index>4</Index><New>1</New><Path>/</Path></Message></Root>"""


def test_answering_machines_with_their_messages() -> None:
    client, _ = _client(
        {
            "GetList": {"NewTAMList": TAM_LIST},
            "GetMessageList": {"NewURL": "http://b/m.lua?sid=s2"},
        },
        MESSAGES,
    )
    (tam,) = client.get_tams()
    assert (tam.index, tam.name, tam.enabled, tam.running, tam.capacity_minutes) == (0, "AB 1", True, True, 30)
    new, read = tam.messages
    assert (new.new, new.inbook, new.number) == (True, True, "0302")
    assert new.download_url == "http://fritz.box:49000/m.lua?x=1&sid=s2"
    assert read.new is False and read.download_url is None and read.tam == 0


def test_answering_machine_missing_or_unsupported() -> None:
    assert _client({"GetList": FritzActionError("x")})[0].get_tams() == []
    assert _client({"GetList": {"NewTAMList": ""}})[0].get_tams() == []
    assert _client({"GetMessageList": FritzActionError("x")})[0].get_tam_messages(0) == []
    assert _client({"GetMessageList": {}})[0].get_tam_messages(0) == []


def test_answering_machine_actions() -> None:
    client, box = _client()
    client.set_tam_enable(1, True)
    client.mark_message(1, 5, False)
    client.delete_message(1, 5)
    assert [(a, args) for _, a, args in box.actions] == [
        ("SetEnable", {"NewIndex": 1, "NewEnable": 1}),
        ("MarkMessage", {"NewIndex": 1, "NewMessageIndex": 5, "NewMarkedAsRead": 0}),
        ("DeleteMessage", {"NewIndex": 1, "NewMessageIndex": 5}),
    ]


# --- dial help ------------------------------------------------------------


def test_dial_and_hangup() -> None:
    client, box = _client()
    client.dial("030 1")
    client.hangup()
    assert box.actions[0][1:] == ("X_AVM-DE_DialNumber", {"NewX_AVM-DE_PhoneNumber": "030 1"})
    assert box.actions[1][1] == "X_AVM-DE_DialHangup"


# --- URLs -----------------------------------------------------------------


def test_sid_and_absolute_urls() -> None:
    assert FritzBoxPhoneClient._extract_sid("http://b/x?a=1&sid=zz") == "zz"
    assert FritzBoxPhoneClient._extract_sid("http://b/x") is None
    client, _ = _client(use_tls=True)
    assert client._absolute_url("/f.lua", "s") == "https://fritz.box:49000/f.lua?sid=s"
    assert client._absolute_url("/f.lua?a=1", "s") == "https://fritz.box:49000/f.lua?a=1&sid=s"
    assert client._absolute_url("/f.lua") == "https://fritz.box:49000/f.lua"
    assert client._absolute_url("http://other/x") == "http://other/x"
    assert client._absolute_url("/") is None
    assert client._absolute_url("relative") is None
    assert client._absolute_url(None) is None


# --- downloads ------------------------------------------------------------


class _Response:
    def __init__(self, chunks=(b"abc",), headers=None, status=200) -> None:
        self._chunks, self.headers, self.status_code = chunks, headers or {}, status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def iter_content(self, chunk_size):
        yield from self._chunks


class _Session:
    def __init__(self, response) -> None:
        self.response = response

    def get(self, url, **kwargs):
        return self.response


def _downloader(response):
    client, box = _client()
    box.session = _Session(response)
    client._lock = threading.RLock()
    return client


def test_download_returns_the_body() -> None:
    assert _downloader(_Response((b"ab", b"cd"))).download("http://b/x") == b"abcd"


def test_download_refuses_oversized_recordings(monkeypatch) -> None:
    monkeypatch.setattr(api, "MAX_RECORDING_BYTES", 4)
    with pytest.raises(RecordingTooLarge):
        _downloader(_Response(headers={"Content-Length": "99"})).download("http://b/x")
    with pytest.raises(RecordingTooLarge):
        _downloader(_Response((b"abc", b"de"))).download("http://b/x")


def test_download_explains_a_missing_recording() -> None:
    with pytest.raises(ValueError, match="HTTP 404"):
        _downloader(_Response(status=404)).download("http://b/x")
