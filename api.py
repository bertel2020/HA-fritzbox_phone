"""Synchronous TR-064 client for phonebook, call list and TAM access.

All methods on FritzBoxPhoneClient perform blocking network I/O and must
only be called from an executor thread (see coordinator.py).

Based on the AVM specifications:
- TR-064_Contact_SCPD.pdf (service X_AVM-DE_OnTel1): phonebooks, call list
- TR-064_TAM.pdf (service X_AVM-DE_TAM1): answering machine(s)
- TR-064_VoIP.pdf (service X_VoIP1): own area code (X_AVM-DE_GetVoIPCommonAreaCode)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import requests

from fritzconnection import FritzConnection
from fritzconnection.core.exceptions import FritzConnectionException
from fritzconnection.core.utils import get_xml_root

from .const import CALL_TYPE_NAMES, FAX_PORT, TAM_PORT, TAM_PORT_RANGE

_LOGGER = logging.getLogger(__name__)

ONTEL_SERVICE = "X_AVM-DE_OnTel1"
TAM_SERVICE = "X_AVM-DE_TAM1"
DEVICEINFO_SERVICE = "DeviceInfo1"
VOIP_SERVICE = "X_VoIP1"


@dataclass
class PhonebookNumber:
    number: str
    type: str | None = None


@dataclass
class PhonebookContact:
    name: str
    uniqueid: str | None
    vip: bool
    image_url: str | None
    numbers: list[PhonebookNumber] = field(default_factory=list)


@dataclass
class Phonebook:
    id: int
    name: str
    contacts: list[PhonebookContact] = field(default_factory=list)


@dataclass
class CallEntry:
    id: str
    type: int
    type_name: str
    name: str | None
    caller: str | None
    caller_number: str | None
    called: str | None
    called_number: str | None
    device: str | None
    port: str | None
    date: str | None
    duration: str | None
    count: str | None
    is_fax: bool
    is_tam: bool
    recording_url: str | None
    # Populated by the coordinator's enrichment passes (api.py itself has
    # no knowledge of PhoneBlock or offline geocoding - see coordinator.py).
    spam_confidence: int | None = None
    spam_rating: str | None = None
    spam_location: str | None = None
    is_spam: bool = False
    area_name: str | None = None
    reverse_name: str | None = None
    reverse_category: str | None = None


@dataclass
class TamMessage:
    index: int
    tam: int
    name: str | None
    number: str | None
    called: str | None
    date: str | None
    duration: str | None
    new: bool
    inbook: bool
    download_url: str | None
    spam_confidence: int | None = None
    spam_rating: str | None = None
    spam_location: str | None = None
    is_spam: bool = False
    area_name: str | None = None
    reverse_name: str | None = None
    reverse_category: str | None = None


@dataclass
class Tam:
    index: int
    name: str
    enabled: bool
    running: bool
    capacity_minutes: int | None
    messages: list[TamMessage] = field(default_factory=list)


class FritzBoxPhoneClient:
    """Thin wrapper around fritzconnection for phone-related TR-064 services."""

    def __init__(
        self,
        host: str,
        port: int | None,
        username: str,
        password: str,
        use_tls: bool,
        timeout: float = 15,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout
        self.fc: FritzConnection | None = None

    def connect(self) -> None:
        """Open the TR-064 connection. Blocking."""
        self.fc = FritzConnection(
            address=self._host,
            port=self._port,
            user=self._username,
            password=self._password,
            use_tls=self._use_tls,
            timeout=self._timeout,
        )

    @property
    def serial_number(self) -> str | None:
        try:
            info = self.fc.call_action(DEVICEINFO_SERVICE, "GetInfo")
        except FritzConnectionException:
            return None
        return info.get("NewSerialNumber")

    @property
    def model_name(self) -> str:
        return self.fc.modelname

    def get_own_area_code(self) -> str | None:
        """The box's own configured area code (Ortskennzahl), e.g. "07527".

        FRITZ!Box reports caller numbers from its own local area WITHOUT
        any area code at all (standard German local-dialing convention),
        which offline geocoding can't work with on its own - this fills
        that in (see geocoding.py). Not supported by every box/firmware,
        returns None in that case.
        """
        try:
            result = self.fc.call_action(VOIP_SERVICE, "X_AVM-DE_GetVoIPCommonAreaCode")
        except FritzConnectionException as err:
            _LOGGER.debug("X_AVM-DE_GetVoIPCommonAreaCode failed: %s", err)
            return None
        prefix = result.get("NewX_AVM-DE_OKZPrefix") or ""
        okz = result.get("NewX_AVM-DE_OKZ") or ""
        area_code = f"{prefix}{okz}"
        return area_code or None

    # ------------------------------------------------------------------
    # Phonebooks
    # ------------------------------------------------------------------

    def get_phonebooks(self) -> list[Phonebook]:
        try:
            result = self.fc.call_action(ONTEL_SERVICE, "GetPhonebookList")
        except FritzConnectionException as err:
            _LOGGER.debug("GetPhonebookList failed: %s", err)
            return []
        raw_ids = (result.get("NewPhonebookList") or "").strip()
        phonebooks: list[Phonebook] = []
        for id_str in raw_ids.split(","):
            if not id_str:
                continue
            pb_id = int(id_str)
            info = self.fc.call_action(
                ONTEL_SERVICE, "GetPhonebook", NewPhonebookId=pb_id
            )
            url = info.get("NewPhonebookURL")
            name = info.get("NewPhonebookName") or f"Telefonbuch {pb_id}"
            contacts = self._download_phonebook(url) if url else []
            phonebooks.append(Phonebook(id=pb_id, name=name, contacts=contacts))
        return phonebooks

    def _download_phonebook(self, url: str) -> list[PhonebookContact]:
        sid = self._extract_sid(url)
        root = get_xml_root(url, timeout=self._timeout, session=self.fc.session)
        contacts: list[PhonebookContact] = []
        for contact_el in root.iter("contact"):
            person = contact_el.find("person")
            image_url = (
                self._absolute_url(person.findtext("imageURL"), sid) if person is not None else None
            )
            name = person.findtext("realName", default="").strip() if person is not None else ""
            uniqueid = contact_el.findtext("uniqueid")
            # category == "1" marks the contact as VIP (TR-064_Contact_SCPD.pdf, table 68)
            vip = contact_el.findtext("category") == "1"
            numbers: list[PhonebookNumber] = []
            telephony = contact_el.find("telephony")
            if telephony is not None:
                for number_el in telephony.findall("number"):
                    number_value = (number_el.text or "").strip()
                    if number_value:
                        numbers.append(
                            PhonebookNumber(number=number_value, type=number_el.get("type"))
                        )
            contacts.append(
                PhonebookContact(
                    name=name or "?",
                    uniqueid=uniqueid,
                    vip=vip,
                    image_url=image_url,
                    numbers=numbers,
                )
            )
        return contacts

    # ------------------------------------------------------------------
    # Call list
    # ------------------------------------------------------------------

    def get_call_list(self, days: int, max_entries: int) -> list[CallEntry]:
        try:
            result = self.fc.call_action(ONTEL_SERVICE, "GetCallList")
        except FritzConnectionException as err:
            _LOGGER.debug("GetCallList failed: %s", err)
            return []
        url = result.get("NewCallListURL")
        if not url:
            return []
        if days:
            url += f"&days={days}"
        if max_entries:
            url += f"&max={max_entries}"
        sid = self._extract_sid(url)
        root = get_xml_root(url, timeout=self._timeout, session=self.fc.session)
        entries: list[CallEntry] = []
        for call_el in root.iter("Call"):
            call_type = int(call_el.findtext("Type", default="0") or 0)
            port = call_el.findtext("Port")
            path = call_el.findtext("Path")
            entries.append(
                CallEntry(
                    id=call_el.findtext("Id", default=""),
                    type=call_type,
                    type_name=CALL_TYPE_NAMES.get(call_type, "unknown"),
                    name=call_el.findtext("Name") or None,
                    caller=call_el.findtext("Caller") or None,
                    caller_number=call_el.findtext("CallerNumber") or None,
                    called=call_el.findtext("Called") or None,
                    called_number=call_el.findtext("CalledNumber") or None,
                    device=call_el.findtext("Device") or None,
                    port=port,
                    date=call_el.findtext("Date") or None,
                    duration=call_el.findtext("Duration") or None,
                    count=call_el.findtext("Count") or None,
                    is_fax=port == str(FAX_PORT),
                    is_tam=self._is_tam_port(port),
                    recording_url=self._absolute_url(path, sid) if path else None,
                )
            )
        return entries

    @staticmethod
    def _is_tam_port(port: str | None) -> bool:
        if not port:
            return False
        try:
            port_int = int(port)
        except ValueError:
            return False
        return port_int == TAM_PORT or port_int in TAM_PORT_RANGE

    # ------------------------------------------------------------------
    # Answering machine(s) (TAM)
    # ------------------------------------------------------------------

    def get_tams(self) -> list[Tam]:
        try:
            result = self.fc.call_action(TAM_SERVICE, "GetList")
        except FritzConnectionException as err:
            # box/firmware without answering machine support
            _LOGGER.debug("X_AVM-DE_TAM GetList unavailable: %s", err)
            return []
        raw_list = result.get("NewTAMList")
        if not raw_list:
            return []
        root = ET.fromstring(raw_list)
        running = root.findtext("TAMRunning") == "1"
        capacity_str = root.findtext("Capacity")
        capacity_minutes = int(capacity_str) if capacity_str and capacity_str.isdigit() else None
        tams: list[Tam] = []
        for item in root.findall("Item"):
            name = (item.findtext("Name") or "").strip()
            if not name:
                # unconfigured TAM slot
                continue
            index = int(item.findtext("Index", default="0"))
            tam = Tam(
                index=index,
                name=name,
                enabled=item.findtext("Enable") == "1",
                running=running,
                capacity_minutes=capacity_minutes,
                messages=self.get_tam_messages(index),
            )
            tams.append(tam)
        return tams

    def get_tam_messages(self, index: int) -> list[TamMessage]:
        try:
            result = self.fc.call_action(TAM_SERVICE, "GetMessageList", NewIndex=index)
        except FritzConnectionException as err:
            _LOGGER.debug("GetMessageList(%s) failed: %s", index, err)
            return []
        url = result.get("NewURL")
        if not url:
            return []
        sid = self._extract_sid(url)
        root = get_xml_root(url, timeout=self._timeout, session=self.fc.session)
        messages: list[TamMessage] = []
        for msg_el in root.iter("Message"):
            # AVM's XML inverts the usual meaning: New=0 -> unread/new,
            # New=1 -> already marked/read (TR-064_TAM.pdf, table 14).
            is_new = msg_el.findtext("New", default="0") == "0"
            path = msg_el.findtext("Path")
            messages.append(
                TamMessage(
                    index=int(msg_el.findtext("Index", default="0")),
                    tam=int(msg_el.findtext("Tam", default=str(index))),
                    name=msg_el.findtext("Name") or None,
                    number=msg_el.findtext("Number") or None,
                    called=msg_el.findtext("Called") or None,
                    date=msg_el.findtext("Date") or None,
                    duration=msg_el.findtext("Duration") or None,
                    new=is_new,
                    inbook=msg_el.findtext("Inbook") == "1",
                    download_url=self._absolute_url(path, sid) if path else None,
                )
            )
        return messages

    def set_tam_enable(self, index: int, enable: bool) -> None:
        self.fc.call_action(
            TAM_SERVICE, "SetEnable", NewIndex=index, NewEnable=int(enable)
        )

    def mark_message(self, index: int, message_index: int, read: bool = True) -> None:
        self.fc.call_action(
            TAM_SERVICE,
            "MarkMessage",
            NewIndex=index,
            NewMessageIndex=message_index,
            NewMarkedAsRead=int(read),
        )

    def delete_message(self, index: int, message_index: int) -> None:
        self.fc.call_action(
            TAM_SERVICE,
            "DeleteMessage",
            NewIndex=index,
            NewMessageIndex=message_index,
        )

    def download(self, url: str) -> bytes:
        """Download a resource URL (e.g. a TAM recording) using the
        authenticated TR-064 session."""
        try:
            response = self.fc.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            status = err.response.status_code if err.response is not None else "?"
            raise ValueError(
                f"Aufnahme konnte nicht heruntergeladen werden (HTTP {status}) - "
                "möglicherweise wurde die Nachricht zwischenzeitlich gelöscht "
                "oder enthält keine Sprachaufnahme."
            ) from err
        return response.content

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sid(url: str) -> str | None:
        """Pull the "sid" query parameter out of a list URL (CallListURL /
        TAM GetMessageList's NewURL / PhonebookURL).

        AVM's own docs (TR-064_Contact_SCPD.pdf table 18/23, TR-064_TAM.pdf
        table 6) list "sid" as a supported parameter of these URLs, and the
        box embeds a valid one when it generates them. File references
        *inside* the downloaded XML (a message's Path, a contact's
        imageURL) are bare paths without their own sid though (see this
        same PDFs' XML examples) - reusing the list URL's sid is required
        to actually download them, digest auth alone is not sufficient for
        these particular endpoints.
        """
        query = urlparse(url).query
        values = parse_qs(query).get("sid")
        return values[0] if values else None

    def _absolute_url(self, path: str | None, sid: str | None = None) -> str | None:
        """Resolve a relative download.lua path returned inside phonebook /
        call-list / TAM XML content into an absolute URL, using the same
        host and port as the TR-064 connection (TR-064_Contact_SCPD.pdf,
        section 5.1.1.1 / 5.2.1.1)."""
        if not path:
            return None
        if path.startswith("http://") or path.startswith("https://"):
            return path
        # AVM reports an empty/"/"-only Path for messages without an actual
        # recording (e.g. an immediate hang-up with 0:00 duration) - without
        # this guard that turns into a request to the bare host:port, which
        # 404s with no useful information.
        if not path.startswith("/") or path.strip("/") == "":
            return None
        protocol = "https" if self._use_tls else "http"
        url = f"{protocol}://{self._host}:{self.fc.port}{path}"
        if sid:
            separator = "&" if "?" in path else "?"
            url = f"{url}{separator}sid={sid}"
        return url
