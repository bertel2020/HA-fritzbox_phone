"""Fake FRITZ!Box client and data builders for the tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fritzbox_phone.api import (
    CallEntry,
    Phonebook,
    PhonebookContact,
    PhonebookNumber,
    Tam,
    TamMessage,
)
from custom_components.fritzbox_phone.const import CONF_ENABLE_CALLMONITOR, DOMAIN

ENTRY_DATA = {CONF_HOST: "fritz.box", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}


def make_call(call_id: str, call_type: int = 1, **kwargs: Any) -> CallEntry:
    values: dict[str, Any] = {
        "id": call_id,
        "type": call_type,
        "type_name": {1: "incoming", 2: "missed", 3: "outgoing"}.get(call_type, "unknown"),
        "name": None,
        "caller": None,
        "caller_number": "030123456",
        "called": None,
        "called_number": "0301111",
        "device": "Telefon",
        "port": "0",
        "date": "01.01.26 10:00",
        "duration": "0:01",
        "count": None,
        "is_fax": False,
        "is_tam": False,
        "recording_url": None,
    }
    values.update(kwargs)
    return CallEntry(**values)


def make_message(index: int, number: str = "030123456", new: bool = True, **kwargs: Any) -> TamMessage:
    values: dict[str, Any] = {
        "index": index,
        "tam": 0,
        "name": None,
        "number": number,
        "called": None,
        "date": f"01.01.26 10:0{index}",
        "duration": "0:01",
        "new": new,
        "inbook": False,
        "download_url": None,
    }
    values.update(kwargs)
    return TamMessage(**values)


def make_tam(messages: list[TamMessage], index: int = 0) -> Tam:
    return Tam(
        index=index,
        name="Anrufbeantworter",
        enabled=True,
        running=True,
        capacity_minutes=60,
        messages=messages,
    )


def make_phonebook(*contacts: tuple[str, str]) -> Phonebook:
    return Phonebook(
        id=0,
        name="Telefonbuch",
        contacts=[
            PhonebookContact(
                name=name,
                uniqueid=str(i),
                vip=False,
                image_url=None,
                numbers=[PhonebookNumber(number=number)],
            )
            for i, (name, number) in enumerate(contacts)
        ],
    )


@dataclass
class FakeBox:
    """The state of the pretend FRITZ!Box; tests mutate it between polls."""

    calls: list[CallEntry] = field(default_factory=list)
    tams: list[Tam] = field(default_factory=list)
    phonebooks: list[Phonebook] = field(default_factory=list)
    own_area_code: str | None = None
    connect_error: Exception | None = None
    poll_error: Exception | None = None
    serial: str = "ABC123"
    calls_log: list[tuple] = field(default_factory=list)


def build_client_class(box: FakeBox):
    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.serial_number = box.serial
            self.software_version = "8.00"
            self.fc = None

        def connect(self) -> None:
            if box.connect_error is not None:
                raise box.connect_error

        @property
        def model_name(self) -> str:
            return "FRITZ!Box 7590"

        def _poll(self):
            if box.poll_error is not None:
                raise box.poll_error

        def get_call_list(self, days: int, max_entries: int):
            self._poll()
            return list(box.calls)

        def get_tams(self):
            self._poll()
            return list(box.tams)

        def get_phonebooks(self):
            self._poll()
            return list(box.phonebooks)

        def get_own_area_code(self):
            return box.own_area_code

        def get_tam_messages(self, index: int):
            return next((t.messages for t in box.tams if t.index == index), [])

        def set_tam_enable(self, index: int, enable: bool) -> None:
            box.calls_log.append(("set_tam_enable", index, enable))

        def mark_message(self, index: int, message_index: int, read: bool = True) -> None:
            box.calls_log.append(("mark_message", index, message_index, read))

        def delete_message(self, index: int, message_index: int) -> None:
            box.calls_log.append(("delete_message", index, message_index))

        def download(self, url: str) -> bytes:
            return b"RIFF"

    return FakeClient


async def setup_integration(
    hass: HomeAssistant, box: FakeBox, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=box.serial,
        data=ENTRY_DATA,
        options={CONF_ENABLE_CALLMONITOR: False, **(options or {})},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.fritzbox_phone.FritzBoxPhoneClient", build_client_class(box)
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def get_coordinator(hass: HomeAssistant, entry: MockConfigEntry):
    return hass.data[DOMAIN][entry.entry_id]
