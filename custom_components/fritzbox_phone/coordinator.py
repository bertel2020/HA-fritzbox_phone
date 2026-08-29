"""DataUpdateCoordinator for the FRITZ!Box phone integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from pathlib import Path

from fritzconnection.core.exceptions import FritzConnectionException
import phonenumbers
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CallEntry, FritzBoxPhoneClient, Phonebook, Tam, TamMessage
from .callmonitor import normalize_number
from .geocoding import describe_number
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
    DEFAULT_CALL_LIST_DAYS,
    DEFAULT_CALL_LIST_MAX,
    DEFAULT_COUNTRY_PREFIX,
    DEFAULT_PHONEBLOCK_ENABLED,
    DEFAULT_PHONEBLOCK_THRESHOLD,
    DEFAULT_REVERSE_LOOKUP_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OUTGOING_CALL_TYPE,
)
from .phoneblock import PhoneBlockClient, PhoneBlockInfo
from .tellows import TellowsClient, TellowsInfo

_LOGGER = logging.getLogger(__name__)


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
        self.phoneblock = self._build_phoneblock_client()
        self.tellows = self._build_tellows_client()
        self._own_area_code: str | None = None
        self._own_area_code_fetched = False
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def _country_prefix(self) -> str:
        prefixes_raw = self.entry.options.get(CONF_PREFIXES, "")
        prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
        return prefixes[0] if prefixes else DEFAULT_COUNTRY_PREFIX

    def _region_code(self) -> str:
        """ISO region code (e.g. "DE") derived from the configured country
        prefix, for offline number geocoding."""
        digits = self._country_prefix().lstrip("+")
        try:
            return phonenumbers.region_code_for_country_code(int(digits)) or "DE"
        except (ValueError, TypeError):
            return "DE"

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
        return TellowsClient()

    async def _async_update_data(self) -> FritzBoxPhoneData:
        try:
            return await self.hass.async_add_executor_job(self._update)
        except FritzConnectionException as err:
            raise UpdateFailed(str(err)) from err

    def _update(self) -> FritzBoxPhoneData:
        days = self.entry.options.get(CONF_CALL_LIST_DAYS, DEFAULT_CALL_LIST_DAYS)
        max_entries = self.entry.options.get(CONF_CALL_LIST_MAX, DEFAULT_CALL_LIST_MAX)
        calls = self.client.get_call_list(days=days, max_entries=max_entries)
        tams = self.client.get_tams()
        self._enrich_calls_with_area_info(calls)
        self._enrich_tam_messages_with_area_info(tams)
        if self.phoneblock is not None:
            self._enrich_calls_with_phoneblock(calls)
            self._enrich_tam_messages_with_phoneblock(tams)
        if self.tellows is not None:
            self._enrich_calls_with_tellows(calls)
            self._enrich_tam_messages_with_tellows(tams)
        return FritzBoxPhoneData(
            phonebooks=self.client.get_phonebooks(),
            calls=calls,
            tams=tams,
        )

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

    def _enrich_calls_with_phoneblock(self, calls: list[CallEntry]) -> None:
        for call in calls:
            if call.name or call.type == OUTGOING_CALL_TYPE:
                # Already resolved locally, or a number we called ourselves -
                # no point spam-checking either.
                continue
            self._apply_phoneblock_info(call, call.caller_number or call.caller)

    def _enrich_tam_messages_with_phoneblock(self, tams: list[Tam]) -> None:
        for tam in tams:
            for message in tam.messages:
                if message.name:
                    continue
                self._apply_phoneblock_info(message, message.number)

    def _apply_phoneblock_info(self, target: CallEntry | TamMessage, number: str | None) -> None:
        if not number:
            return
        info = self.phoneblock.check(number)
        if info is None:
            return
        target.spam_confidence = info.spam_confidence
        target.spam_rating = info.rating
        target.spam_location = info.location
        target.is_spam = info.is_spam

    def check_phoneblock(self, number: str | None) -> PhoneBlockInfo | None:
        """Look up a number's PhoneBlock spam rating, if enabled. Blocking."""
        if self.phoneblock is None or not number:
            return None
        return self.phoneblock.check(number)

    def _enrich_calls_with_tellows(self, calls: list[CallEntry]) -> None:
        for call in calls:
            if call.name or call.type == OUTGOING_CALL_TYPE:
                continue
            self._apply_tellows_info(call, call.caller_number or call.caller)

    def _enrich_tam_messages_with_tellows(self, tams: list[Tam]) -> None:
        for tam in tams:
            for message in tam.messages:
                if message.name:
                    continue
                self._apply_tellows_info(message, message.number)

    def _apply_tellows_info(self, target: CallEntry | TamMessage, number: str | None) -> None:
        if not number:
            return
        info = self.tellows.lookup(number)
        if info is None or not info.name:
            return
        target.reverse_name = info.name
        target.reverse_category = info.category

    def identify_caller(self, number: str | None) -> TellowsInfo | None:
        """Look up a number via Tellows, if the online reverse-lookup is
        enabled. Blocking."""
        if self.tellows is None or not number:
            return None
        return self.tellows.lookup(number)

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

        Returns (name, vip) or (None, False) if unknown. Also tries the
        configured `prefixes` (e.g. "+49") to bridge local vs.
        internationalized number formats, same as HA core's
        fritzbox_callmonitor integration.
        """
        target = normalize_number(number)
        if not target:
            return None, False
        candidates: dict[str, tuple[str, bool]] = {}
        for phonebook in self.data.phonebooks:
            for contact in phonebook.contacts:
                for pb_number in contact.numbers:
                    candidates[normalize_number(pb_number.number)] = (
                        contact.name,
                        contact.vip,
                    )
        if target in candidates:
            return candidates[target]
        prefixes_raw = self.entry.options.get(CONF_PREFIXES, "")
        prefixes = [p.strip() for p in prefixes_raw.split(",") if p.strip()]
        for prefix in prefixes:
            if prefix + target in candidates:
                return candidates[prefix + target]
            if prefix + target.lstrip("0") in candidates:
                return candidates[prefix + target.lstrip("0")]
        return None, False

    def download_message(self, tam_index: int, message_index: int, filename: str) -> str:
        """Download a TAM recording into config/www/fritzbox_tam/<filename>.

        Runs blocking I/O, must be called from an executor thread.
        """
        # Fetch the message list fresh instead of using the coordinator's
        # last-polled data: AVM's download URLs embed a session-bound token
        # that can expire well within the polling interval, so a URL that
        # was valid at the last poll may already 404 by the time the user
        # clicks play.
        messages = self.client.get_tam_messages(tam_index)
        message = next((m for m in messages if m.index == message_index), None)
        if message is None or not message.download_url:
            raise ValueError(
                f"Nachricht {message_index} auf Anrufbeantworter {tam_index} "
                "wurde nicht gefunden oder hat keine Aufnahme"
            )
        # Prevent path traversal via a maliciously crafted service call.
        safe_filename = Path(filename).name
        dest_dir = Path(self.hass.config.path("www", "fritzbox_tam"))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_filename
        dest_path.write_bytes(self.client.download(message.download_url))
        return str(dest_path)
