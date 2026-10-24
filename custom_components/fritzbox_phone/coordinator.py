"""DataUpdateCoordinator for the FRITZ!Box phone integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
    FritzSecurityError,
)
import phonenumbers
import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CallEntry, FritzBoxPhoneClient, Phonebook, Tam, TamMessage, path_key
from .callmonitor import normalize_number
from .geocoding import describe_number
from .phone_numbers import normalize as normalize_phone_number
from .const import (
    CONF_CALL_LIST_DAYS,
    CONF_CALL_LIST_MAX,
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_THRESHOLD,
    CONF_PHONEBLOCK_USERNAME,
    CONF_PREFIXES,
    CONF_REVERSE_LOOKUP_ENABLED,
    CONF_SCAN_INTERVAL,
    CONTEXT_KEY_CALL_LIST,
    CONTEXT_KEY_MISSED_CALLS,
    CONTEXT_KEY_TAM,
    DEFAULT_CALL_LIST_DAYS,
    DEFAULT_CALL_LIST_MAX,
    DEFAULT_COUNTRY_PREFIX,
    DEFAULT_PHONEBLOCK_ENABLED,
    DEFAULT_PHONEBLOCK_THRESHOLD,
    DEFAULT_REVERSE_LOOKUP_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CALL_LIST_CHANGED,
    EVENT_MISSED_CALL,
    EVENT_TAM_MESSAGE,
    MISSED_CALL_TYPE,
    OUTGOING_CALL_TYPE,
    PHONEBOOK_REFRESH_INTERVAL,
)
from .phoneblock import PhoneBlockClient, PhoneBlockInfo
from .tellows import TellowsClient, TellowsInfo

_LOGGER = logging.getLogger(__name__)

# Upper bound on how many changed entries travel inside a single event.
# One poll cycle normally brings one or two; only a long connection gap
# can pile them up, and the recorder should not have to store (nor the
# logbook render) an unbounded list in that case.
MAX_EVENT_ENTRIES = 10

# Online lookups run concurrently, but politely.
MAX_PARALLEL_LOOKUPS = 5
# Seconds a poll waits for them. Whatever is still outstanding finishes in
# the background and is picked up from the cache by the next poll.
ENRICHMENT_BUDGET = 20
FIRST_ENRICHMENT_BUDGET = 5


@dataclass
class FritzBoxPhoneData:
    phonebooks: list[Phonebook]
    calls: list[CallEntry]
    tams: list[Tam]


class FritzBoxPhoneCoordinator(DataUpdateCoordinator[FritzBoxPhoneData]):
    """Polls phonebooks, call list and answering machine(s)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: FritzBoxPhoneClient
    ) -> None:
        self.client = client
        self.entry = entry
        # Needed by the lookup clients below, which run before the base
        # class has stored it.
        self.hass = hass
        self.phoneblock = self._build_phoneblock_client()
        self.tellows = self._build_tellows_client()
        self._own_area_code: str | None = None
        self._own_area_code_fetched = False
        # Phonebooks are re-downloaded only every PHONEBOOK_REFRESH_INTERVAL
        # seconds; the number -> contact indexes are rebuilt with them.
        self._phonebooks: list[Phonebook] | None = None
        self._phonebooks_fetched = 0.0
        self._contacts_by_number: dict[str, tuple[str, bool]] = {}
        self._contacts_by_digits: dict[str, tuple[str, bool]] = {}
        # Change detection for the logbook events. `None` means "no poll
        # yet": the first cycle only records the baseline, otherwise every
        # restart would report the whole call list as brand new.
        self._known_call_ids: set[str] | None = None
        self._known_missed_ids: set[str] | None = None
        self._known_new_messages: dict[int, set[str]] | None = None
        self._pending_contexts: dict[str, Context] = {}
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def _prefixes(self) -> list[str]:
        raw = self.entry.options.get(CONF_PREFIXES, "")
        return [p.strip() for p in raw.split(",") if p.strip()]

    def _country_prefix(self) -> str:
        """Dial prefix of the country the box is in (e.g. "+49").

        The optional `prefixes` setting wins; without it the country
        configured in Home Assistant decides.
        """
        prefixes = self._prefixes()
        if prefixes:
            return prefixes[0]
        country = self.hass.config.country
        if country:
            code = phonenumbers.country_code_for_region(country)
            if code:
                return f"+{code}"
        return DEFAULT_COUNTRY_PREFIX

    def _region_code(self) -> str:
        """ISO region code (e.g. "DE") derived from the configured country
        prefix, for offline number geocoding."""
        digits = self._country_prefix().lstrip("+")
        try:
            return phonenumbers.region_code_for_country_code(int(digits)) or "DE"
        except (ValueError, TypeError):
            return "DE"

    def normalize_number(self, number: str | None) -> str | None:
        """Canonical (E.164) form of a number as the box reports it."""
        return normalize_phone_number(
            number, self._region_code(), self._country_prefix(), self._get_own_area_code()
        )

    def _get_own_area_code(self) -> str | None:
        """The box's own configured area code, fetched once and cached
        (see FritzBoxPhoneClient.get_own_area_code - this never changes
        without a manual reconfiguration of the box, so no point asking
        again every poll cycle)."""
        if not self._own_area_code_fetched:
            self._own_area_code = self.client.get_own_area_code()
            self._own_area_code_fetched = True
        return self._own_area_code

    def _build_phoneblock_client(self) -> PhoneBlockClient | None:
        options = self.entry.options
        if not options.get(CONF_PHONEBLOCK_ENABLED, DEFAULT_PHONEBLOCK_ENABLED):
            return None
        username = options.get(CONF_PHONEBLOCK_USERNAME)
        password = options.get(CONF_PHONEBLOCK_PASSWORD)
        if not username or not password:
            _LOGGER.warning(
                "PhoneBlock aktiviert, aber Benutzername/Kennwort fehlen - "
                "Spam-Abgleich wird übersprungen."
            )
            return None
        threshold = options.get(CONF_PHONEBLOCK_THRESHOLD, DEFAULT_PHONEBLOCK_THRESHOLD)
        return PhoneBlockClient(
            session=async_get_clientsession(self.hass),
            username=username,
            password=password,
            country_prefix=self._country_prefix(),
            spam_threshold=threshold,
        )

    def _build_tellows_client(self) -> TellowsClient | None:
        options = self.entry.options
        if not options.get(CONF_REVERSE_LOOKUP_ENABLED, DEFAULT_REVERSE_LOOKUP_ENABLED):
            return None
        # No account/credentials needed - Tellows' /basic/num API is public.
        return TellowsClient(session=async_get_clientsession(self.hass))

    async def _async_update_data(self) -> FritzBoxPhoneData:
        try:
            data = await self.hass.async_add_executor_job(self._update)
        except (FritzAuthorizationError, FritzSecurityError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (
            FritzConnectionException,
            requests.RequestException,
            ET.ParseError,
            ValueError,
            OSError,
        ) as err:
            # Keeping the previous data (UpdateFailed) matters: a failed
            # poll must never look like an empty call list, or the change
            # detection below would report every call as removed and then
            # as new again.
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        await self._async_enrich_online(data)
        # Fire before returning: the coordinator notifies its entities the
        # moment this returns, and they need the Contexts to already be
        # parked when they write their new state.
        self._async_report_changes(data)
        return data

    @callback
    def take_context(self, key: str) -> Context | None:
        """Hand out (once) the Context of the event explaining this update."""
        return self._pending_contexts.pop(key, None)

    def _event_base(self) -> dict[str, Any]:
        return {
            "config_entry_id": self.entry.entry_id,
            "host": self.entry.data[CONF_HOST],
        }

    @callback
    def _fire(self, event_type: str, context_key: str, data: dict[str, Any]) -> None:
        """Fire one logbook event and park its Context for the entity."""
        context = Context()
        self.hass.bus.async_fire(event_type, self._event_base() | data, context=context)
        self._pending_contexts[context_key] = context

    @callback
    def _async_report_changes(self, data: FritzBoxPhoneData) -> None:
        """Turn this poll's diff into events the logbook can describe."""
        self._pending_contexts.clear()
        self._report_call_list(data.calls)
        self._report_missed_calls(data.calls)
        self._report_tam_messages(data.tams)

    @callback
    def _report_call_list(self, calls: list[CallEntry]) -> None:
        current = {call.id for call in calls}
        known, self._known_call_ids = self._known_call_ids, current
        if known is None:
            return
        added = [call for call in calls if call.id not in known]
        removed = len(known - current)
        if not added and not removed:
            return
        self._fire(
            EVENT_CALL_LIST_CHANGED,
            CONTEXT_KEY_CALL_LIST,
            {
                "added": [self._call_payload(call) for call in added[:MAX_EVENT_ENTRIES]],
                "added_count": len(added),
                "removed": removed,
            },
        )

    @callback
    def _report_missed_calls(self, calls: list[CallEntry]) -> None:
        missed = [call for call in calls if call.type == MISSED_CALL_TYPE]
        current = {call.id for call in missed}
        known, self._known_missed_ids = self._known_missed_ids, current
        if known is None:
            return
        added = [call for call in missed if call.id not in known]
        removed = len(known - current)
        if not added and not removed:
            return
        self._fire(
            EVENT_MISSED_CALL,
            CONTEXT_KEY_MISSED_CALLS,
            {
                "added": [self._call_payload(call) for call in added[:MAX_EVENT_ENTRIES]],
                "added_count": len(added),
                "removed": removed,
            },
        )

    @callback
    def _report_tam_messages(self, tams: list[Tam]) -> None:
        # Keyed by timestamp and number rather than by message index: the
        # box renumbers its recordings whenever one is deleted, which
        # would otherwise look like a batch of new messages.
        current = {
            tam.index: {
                self._message_key(message) for message in tam.messages if message.new
            }
            for tam in tams
        }
        known, self._known_new_messages = self._known_new_messages, current
        if known is None:
            return
        for tam in tams:
            previous = known.get(tam.index)
            if previous is None:
                continue
            added = [
                message
                for message in tam.messages
                if message.new and self._message_key(message) not in previous
            ]
            removed = len(previous - current[tam.index])
            if not added and not removed:
                continue
            self._fire(
                EVENT_TAM_MESSAGE,
                CONTEXT_KEY_TAM.format(tam.index),
                {
                    "tam_index": tam.index,
                    "tam_name": tam.name,
                    "added": [
                        self._message_payload(message)
                        for message in added[:MAX_EVENT_ENTRIES]
                    ],
                    "added_count": len(added),
                    "removed": removed,
                },
            )

    @staticmethod
    def _message_key(message: TamMessage) -> str:
        return f"{message.date}|{message.number}"

    def _call_payload(self, call: CallEntry) -> dict[str, Any]:
        """The fields logbook.py needs to phrase a call list entry."""
        return {
            "type": call.type_name,
            "name": call.name,
            "number": self._call_counterpart_number(call),
            "area_name": call.area_name,
            "reverse_name": call.reverse_name,
            "is_spam": call.is_spam,
            "spam_confidence": call.spam_confidence,
            "date": call.date,
            "duration": call.duration,
            "is_fax": call.is_fax,
            "is_answering_machine": call.is_tam,
        }

    @staticmethod
    def _message_payload(message: TamMessage) -> dict[str, Any]:
        """The fields logbook.py needs to phrase an answering machine message."""
        return {
            "name": message.name,
            "number": message.number,
            "area_name": message.area_name,
            "reverse_name": message.reverse_name,
            "is_spam": message.is_spam,
            "spam_confidence": message.spam_confidence,
            "date": message.date,
            "duration": message.duration,
        }

    def _update(self) -> FritzBoxPhoneData:
        days = self.entry.options.get(CONF_CALL_LIST_DAYS, DEFAULT_CALL_LIST_DAYS)
        max_entries = self.entry.options.get(CONF_CALL_LIST_MAX, DEFAULT_CALL_LIST_MAX)
        calls = self.client.get_call_list(days=days, max_entries=max_entries)
        tams = self.client.get_tams()
        self._enrich_calls_with_area_info(calls)
        self._enrich_tam_messages_with_area_info(tams)
        self._link_calls_to_messages(calls, tams)
        return FritzBoxPhoneData(
            phonebooks=self._get_phonebooks(),
            calls=calls,
            tams=tams,
        )

    @staticmethod
    def _link_calls_to_messages(calls: list[CallEntry], tams: list[Tam]) -> None:
        """Tell each answering-machine call which message holds its recording.

        The call list and the message list share no id, but both point at
        the same recording file, so matching on that path is exact - unlike
        guessing from number and time.
        """
        by_path = {
            key: (tam.index, message.index)
            for tam in tams
            for message in tam.messages
            if (key := path_key(message.path))
        }
        for call in calls:
            if (key := path_key(call.path)) and key in by_path:
                call.tam_index, call.tam_message_index = by_path[key]

    def _get_phonebooks(self) -> list[Phonebook]:
        age = time.monotonic() - self._phonebooks_fetched
        if self._phonebooks is not None and age < PHONEBOOK_REFRESH_INTERVAL:
            return self._phonebooks
        try:
            phonebooks = self.client.get_phonebooks()
        except Exception as err:  # noqa: BLE001
            if self._phonebooks is None:
                raise
            # Contacts are secondary data: keep serving the copy we have
            # rather than failing the whole poll, and retry next time.
            _LOGGER.debug("Telefonbuch-Aktualisierung fehlgeschlagen: %s", err)
            return self._phonebooks
        self._phonebooks = phonebooks
        self._phonebooks_fetched = time.monotonic()
        self._index_contacts(phonebooks)
        return phonebooks

    def _index_contacts(self, phonebooks: list[Phonebook]) -> None:
        by_number: dict[str, tuple[str, bool]] = {}
        by_digits: dict[str, tuple[str, bool]] = {}
        for phonebook in phonebooks:
            for contact in phonebook.contacts:
                for entry_number in contact.numbers:
                    value = (contact.name, contact.vip)
                    if canonical := self.normalize_number(entry_number.number):
                        by_number.setdefault(canonical, value)
                    if digits := normalize_number(entry_number.number):
                        by_digits.setdefault(digits, value)
        self._contacts_by_number = by_number
        self._contacts_by_digits = by_digits

    def _call_counterpart_number(self, call: CallEntry) -> str | None:
        """The "other side" number for a call, direction-aware."""
        if call.type == OUTGOING_CALL_TYPE:
            return call.called_number or call.called
        return call.caller_number or call.caller

    def _enrich_calls_with_area_info(self, calls: list[CallEntry]) -> None:
        # Always on - purely local/offline lookup, no network call and no
        # third-party service involved (unlike the optional PhoneBlock
        # spam-check below), so there's no reason to gate this behind an
        # option.
        region = self._region_code()
        area_code = self._get_own_area_code()
        for call in calls:
            call.area_name = describe_number(
                self._call_counterpart_number(call), region, area_code
            )

    def _enrich_tam_messages_with_area_info(self, tams: list[Tam]) -> None:
        region = self._region_code()
        area_code = self._get_own_area_code()
        for tam in tams:
            for message in tam.messages:
                message.area_name = describe_number(message.number, region, area_code)

    # ------------------------------------------------------------------
    # Online enrichment (PhoneBlock spam check, Tellows reverse lookup)
    # ------------------------------------------------------------------

    def _enrichment_targets(self, data: FritzBoxPhoneData) -> list[tuple[CallEntry | TamMessage, str]]:
        """Entries worth an online lookup, with their canonical number."""
        targets: list[tuple[CallEntry | TamMessage, str]] = []
        for call in data.calls:
            if call.name or call.type == OUTGOING_CALL_TYPE:
                # Already resolved locally, or a number we called ourselves -
                # no point looking up either.
                continue
            if number := self.normalize_number(call.caller_number or call.caller):
                targets.append((call, number))
        for tam in data.tams:
            for message in tam.messages:
                if message.name:
                    continue
                if number := self.normalize_number(message.number):
                    targets.append((message, number))
        return targets

    async def _async_enrich_online(self, data: FritzBoxPhoneData) -> None:
        if self.phoneblock is None and self.tellows is None:
            return
        targets = self._enrichment_targets(data)
        if not targets:
            return
        # The very first refresh blocks Home Assistant's setup of the entry,
        # so it gets a much smaller budget than a regular poll. Lookups that
        # miss the budget keep running in the background and land in the
        # cache, so the next poll picks them up.
        budget = FIRST_ENRICHMENT_BUDGET if self.data is None else ENRICHMENT_BUDGET
        results = await self._async_lookup_many({number for _, number in targets}, budget)
        for target, number in targets:
            phoneblock_info, tellows_info = results.get(number, (None, None))
            if phoneblock_info is not None:
                target.spam_confidence = phoneblock_info.spam_confidence
                target.spam_rating = phoneblock_info.rating
                target.spam_location = phoneblock_info.location
                target.is_spam = phoneblock_info.is_spam
            if tellows_info is not None and tellows_info.name:
                target.reverse_name = tellows_info.name
                target.reverse_category = tellows_info.category

    async def _async_lookup_many(
        self, numbers: set[str], budget: float
    ) -> dict[str, tuple[PhoneBlockInfo | None, TellowsInfo | None]]:
        semaphore = asyncio.Semaphore(MAX_PARALLEL_LOOKUPS)

        async def lookup(number: str):
            async with semaphore:
                return number, (
                    await self.async_check_phoneblock(number),
                    await self.async_identify_caller(number),
                )

        tasks = [
            self.entry.async_create_background_task(
                self.hass, lookup(number), f"{DOMAIN} lookup {number}"
            )
            for number in numbers
        ]
        done, _pending = await asyncio.wait(tasks, timeout=budget)
        results: dict[str, tuple[PhoneBlockInfo | None, TellowsInfo | None]] = {}
        for task in done:
            if task.cancelled() or task.exception() is not None:
                continue
            number, outcome = task.result()
            results[number] = outcome
        return results

    async def async_check_phoneblock(self, number: str | None) -> PhoneBlockInfo | None:
        """Look up a number's PhoneBlock spam rating, if enabled."""
        if self.phoneblock is None or not number:
            return None
        return await self.phoneblock.check(self.normalize_number(number))

    async def async_identify_caller(self, number: str | None) -> TellowsInfo | None:
        """Look up a number via Tellows, if the online reverse-lookup is
        enabled."""
        if self.tellows is None or not number:
            return None
        return await self.tellows.lookup(self.normalize_number(number))


    def get_area_name(self, number: str | None) -> str | None:
        """Offline country/area-code description for a number (e.g. "Berlin").

        Always available, no network access involved (beyond the box's own
        area code, fetched once and cached).
        """
        return describe_number(number, self._region_code(), self._get_own_area_code())

    def get_tam(self, tam_index: int) -> Tam | None:
        return next((t for t in self.data.tams if t.index == tam_index), None)

    def resolve_contact(self, number: str) -> tuple[str | None, bool]:
        """Look up a phone number in the currently loaded phonebooks.

        Returns (name, vip) or (None, False) if unknown. The number is
        compared in canonical (E.164) form, so national, international and
        local-area spellings of the same number all match. The plain-digit
        comparison with the configured `prefixes` (e.g. "+49") stays as a
        fallback for numbers libphonenumber cannot interpret.
        """
        if not normalize_number(number):
            return None, False
        canonical = self.normalize_number(number)
        if canonical and canonical in self._contacts_by_number:
            return self._contacts_by_number[canonical]
        target = normalize_number(number)
        if target in self._contacts_by_digits:
            return self._contacts_by_digits[target]
        for prefix in self._prefixes():
            for candidate in (prefix + target, prefix + target.lstrip("0")):
                if candidate in self._contacts_by_digits:
                    return self._contacts_by_digits[candidate]
        return None, False

    def fetch_recording(self, tam_index: int, message_index: int) -> bytes:
        """The audio of one answering machine message. Blocking.

        The message list is fetched fresh instead of using the last polled
        data: AVM's download URLs embed a session-bound token that can
        expire well within the polling interval, so a URL that was valid at
        the last poll may already 404 by the time somebody presses play.
        """
        messages = self.client.get_tam_messages(tam_index)
        message = next((m for m in messages if m.index == message_index), None)
        if message is None or not message.download_url:
            raise ValueError(
                f"Nachricht {message_index} auf Anrufbeantworter {tam_index} "
                "wurde nicht gefunden oder hat keine Aufnahme"
            )
        return self.client.download(message.download_url)

    def download_message(self, tam_index: int, message_index: int, filename: str) -> str:
        """Download a TAM recording into config/www/fritzbox_tam/<filename>.

        Runs blocking I/O, must be called from an executor thread.
        """
        safe_filename = validate_recording_filename(filename)
        audio = self.fetch_recording(tam_index, message_index)
        dest_dir = Path(self.hass.config.path("www", "fritzbox_tam"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_filename
        dest_path.write_bytes(audio)
        return str(dest_path)


ALLOWED_RECORDING_SUFFIXES = (".wav", ".mp3", ".ogg")


def validate_recording_filename(filename: str) -> str:
    """A bare file name with an audio extension, or ValueError.

    The name arrives from a service call and ends up in a folder that Home
    Assistant serves without authentication, so anything that is not
    plainly an audio file name is refused.
    """
    name = Path(str(filename)).name
    if name != filename or name in ("", ".", "..") or name.startswith("."):
        raise ValueError(f"Ungültiger Dateiname: {filename!r}")
    if Path(name).suffix.lower() not in ALLOWED_RECORDING_SUFFIXES:
        raise ValueError(
            "Dateiname muss auf " + ", ".join(ALLOWED_RECORDING_SUFFIXES) + " enden"
        )
    return name
