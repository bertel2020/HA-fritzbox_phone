"""Real-time FRITZ!Box call monitor (CallMonitor protocol, port 1012).

The CallMonitor service has to be activated once per box by dialing
`#96*5*` from any phone connected to it (`#96*4*` deactivates it again).
Once active, the box pushes semicolon-separated event lines for every
RING / CALL / CONNECT / DISCONNECT over a plain TCP socket:

    date;RING;id;caller;called;line
    date;CALL;id;extension;caller;called;line
    date;CONNECT;id;extension;number
    date;DISCONNECT;id;seconds

This wraps `fritzconnection.core.fritzmonitor.FritzMonitor` (the same
building block used by Home Assistant core's own `fritzbox_callmonitor`
integration). A background thread only reads and parses lines; everything
else - the per-call state, the lookups, the entities - lives on the event
loop, so there is no state shared between threads.

A line is published to the entities immediately. Spam check and reverse
lookup are online services that can take seconds, so they run afterwards
and are announced with a follow-up event (`enriched`), instead of holding
back the "ringing" state.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import queue
import re
from threading import Event as ThreadingEvent, RLock, Thread, current_thread
from typing import TYPE_CHECKING, Any

from fritzconnection.core.fritzmonitor import FritzMonitor

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CALLMONITOR_STATE_DIALING,
    CALLMONITOR_STATE_IDLE,
    CALLMONITOR_STATE_RINGING,
    CALLMONITOR_STATE_TALKING,
    DOMAIN,
    EVENT_CALL,
)

if TYPE_CHECKING:
    from .coordinator import FritzBoxPhoneCoordinator

_LOGGER = logging.getLogger(__name__)

NUMBER_STRIP_RE = re.compile(r"[^\d+]")
_DATE_FORMAT_IN = "%d.%m.%y %H:%M:%S"

# Seconds between attempts to open the socket while the box refuses it
# (CallMonitor not activated, box rebooting); the last value repeats.
RETRY_DELAYS = (30, 60, 120, 300)
# FritzMonitor's own reconnect behaviour once a connection existed.
MONITOR_RECONNECT_TRIES = 10
MONITOR_RECONNECT_DELAY = 120
# How often the reader thread wakes up to see whether it should stop or
# whether FritzMonitor has given up for good.
READER_POLL_SECONDS = 1

# Which of several simultaneous calls the entity shows.
_PHASE_PRIORITY = {
    CALLMONITOR_STATE_TALKING: 3,
    CALLMONITOR_STATE_RINGING: 2,
    CALLMONITOR_STATE_DIALING: 1,
}


def normalize_number(number: str | None) -> str:
    """Strip everything but digits and a leading '+' for number comparison."""
    return NUMBER_STRIP_RE.sub("", number or "")


@dataclass
class MonitorLine:
    """One parsed line of the CallMonitor protocol."""

    kind: str  # RING, CALL, CONNECT or DISCONNECT
    connection_id: str
    timestamp: str | None
    fields: dict[str, Any]


def parse_line(line: str) -> MonitorLine | None:
    """Parse one CallMonitor line; None if it is not one we understand."""
    parts = line.strip().split(";")
    if len(parts) < 3:
        return None
    try:
        timestamp = datetime.strptime(parts[0], _DATE_FORMAT_IN).isoformat()
    except ValueError:
        timestamp = None
    kind, connection_id = parts[1], parts[2]
    try:
        if kind == "RING":
            fields = {"from": parts[3], "to": parts[4], "device": parts[5]}
        elif kind == "CALL":
            fields = {"from": parts[4], "to": parts[5], "device": parts[6]}
        elif kind == "CONNECT":
            fields = {"with": parts[4], "device": parts[3]}
        elif kind == "DISCONNECT":
            fields = {"duration": parts[3]}
        else:
            return None
    except IndexError:
        _LOGGER.debug("Unerwartetes CallMonitor-Event: %s", line)
        return None
    return MonitorLine(kind, connection_id, timestamp, fields)


def format_call_duration(raw: str | None) -> str | None:
    """Format the CallMonitor protocol's DISCONNECT duration (whole
    seconds, exact - unlike the polled call list's rounded "hh:mm") as
    "m:ss" or "h:mm:ss"."""
    if raw is None:
        return None
    try:
        total_seconds = int(raw)
    except ValueError:
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def compute_call_start(closed: str | None, duration: str | None) -> str | None:
    """Start of the connected call (ISO timestamp), derived as
    closed - duration - CallMonitor's DISCONNECT line gives the end time
    and the exact duration, but not the start time directly."""
    if not closed or duration is None:
        return None
    try:
        closed_dt = datetime.fromisoformat(closed)
        seconds = int(duration)
    except ValueError:
        return None
    return (closed_dt - timedelta(seconds=seconds)).isoformat()


def seconds_between(earlier: str, later: str) -> int | None:
    try:
        delta = datetime.fromisoformat(later) - datetime.fromisoformat(earlier)
    except ValueError:
        return None
    return max(0, round(delta.total_seconds()))


@dataclass
class ActiveCall:
    """A call the box has announced and not yet ended."""

    connection_id: str
    phase: str
    attributes: dict[str, Any] = field(default_factory=dict)


class FritzCallMonitor:
    """Keeps the CallMonitor connection alive and turns lines into call state."""

    def __init__(
        self, hass: HomeAssistant, host: str, port: int, coordinator: FritzBoxPhoneCoordinator
    ) -> None:
        self.hass = hass
        self._host = host
        self._port = port
        self._coordinator = coordinator

        self.state = CALLMONITOR_STATE_IDLE
        self.attributes: dict[str, Any] = {}
        self.connected = False

        self._active: dict[str, ActiveCall] = {}
        self._last_summary: dict[str, Any] = {}
        self._listeners: list[Callable[[Context | None], None]] = []
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []

        self._monitor: FritzMonitor | None = None
        self._reader: Thread | None = None
        self._stopped = ThreadingEvent()
        self._conn_lock = RLock()
        self._retry_cancel: Callable[[], None] | None = None
        self._failures = 0
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @callback
    def async_add_listener(self, listener: Callable[[Context | None], None]) -> Callable[[], None]:
        """Be told (with the Context of the event behind it) whenever
        `state`, `attributes` or `connected` changed."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_add_event_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Be told about every call event (event type, payload)."""
        self._event_listeners.append(listener)
        return lambda: self._event_listeners.remove(listener)

    @callback
    def _notify(self, context: Context | None = None) -> None:
        for listener in list(self._listeners):
            listener(context)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Open the connection (retrying in the background if refused)."""
        self._stopped.clear()
        await self._async_connect()

    async def async_stop(self) -> None:
        """Close the connection and stop retrying."""
        self._stopped.set()
        if self._retry_cancel is not None:
            self._retry_cancel()
            self._retry_cancel = None
        for task in list(self._tasks):
            task.cancel()
        await self.hass.async_add_executor_job(self._disconnect)
        if self.connected:
            self.connected = False
            self._notify()

    async def _async_connect(self) -> None:
        if self._stopped.is_set():
            return
        try:
            await self.hass.async_add_executor_job(self._connect)
        except OSError as err:
            self._failures += 1
            delay = RETRY_DELAYS[min(self._failures - 1, len(RETRY_DELAYS) - 1)]
            # Say it loudly once; every later retry is routine.
            log = _LOGGER.warning if self._failures == 1 else _LOGGER.debug
            log(
                "Anrufmonitor: Verbindung zu %s:%s fehlgeschlagen. Ist der "
                "CallMonitor per #96*5* an einem angeschlossenen Telefon "
                "aktiviert? Neuer Versuch in %s s. (%s)",
                self._host,
                self._port,
                delay,
                err,
            )
            if self.connected:
                self.connected = False
                self._notify()
            if not self._stopped.is_set():
                self._retry_cancel = async_call_later(self.hass, delay, self._async_retry)
            return
        if self._stopped.is_set():
            # _connect already dropped the socket; nothing is connected.
            return
        if self._failures:
            _LOGGER.info("Anrufmonitor: Verbindung zu %s:%s hergestellt", self._host, self._port)
        self._failures = 0
        self.connected = True
        self._forget_calls()
        self._notify()

    async def _async_retry(self, _now: datetime) -> None:
        self._retry_cancel = None
        await self._async_connect()

    def _connect(self) -> None:
        """Blocking: open the socket and start the reader thread."""
        with self._conn_lock:
            self._disconnect()
            monitor = FritzMonitor(address=self._host, port=self._port)
            event_queue = monitor.start(
                reconnect_tries=MONITOR_RECONNECT_TRIES, reconnect_delay=MONITOR_RECONNECT_DELAY
            )
            if self._stopped.is_set():
                # Stopped while the socket was being opened (the stop request
                # waited for this lock): do not leave a thread behind.
                monitor.stop()
                return
            self._monitor = monitor
            self._reader = Thread(
                target=self._read_events,
                args=(monitor, event_queue),
                name="fritzbox_phone call monitor",
                daemon=True,
            )
            self._reader.start()

    def _disconnect(self) -> None:
        """Blocking: stop the reader and close the socket."""
        with self._conn_lock:
            monitor, self._monitor = self._monitor, None
            reader, self._reader = self._reader, None
            if monitor is not None:
                monitor.stop()
            if reader is not None and reader is not current_thread():
                reader.join(timeout=READER_POLL_SECONDS * 3)

    # ------------------------------------------------------------------
    # Reader thread: read and parse only
    # ------------------------------------------------------------------

    def _read_events(self, monitor: FritzMonitor, event_queue: queue.Queue[str]) -> None:
        while not self._stopped.is_set() and monitor is self._monitor:
            try:
                raw = event_queue.get(timeout=READER_POLL_SECONDS)
            except queue.Empty:
                if not monitor.is_alive:
                    # FritzMonitor used up its reconnect attempts.
                    self.hass.loop.call_soon_threadsafe(self._on_connection_lost, monitor)
                    return
                continue
            if (parsed := parse_line(raw)) is not None:
                self.hass.loop.call_soon_threadsafe(self.async_handle_line, parsed)

    @callback
    def _on_connection_lost(self, monitor: FritzMonitor) -> None:
        if monitor is not self._monitor or self._stopped.is_set():
            return
        _LOGGER.warning("Anrufmonitor: Verbindung zur FRITZ!Box %s verloren", self._host)
        self.connected = False
        self._forget_calls()
        self._notify()
        self._failures = 1
        self._retry_cancel = async_call_later(self.hass, RETRY_DELAYS[0], self._async_retry)

    # ------------------------------------------------------------------
    # Call state (event loop only)
    # ------------------------------------------------------------------

    @callback
    def async_handle_line(self, line: MonitorLine) -> None:
        """Apply one protocol line: update the call, publish, enrich."""
        call = self._active.get(line.connection_id)
        event_state: str
        if line.kind == "RING":
            event_state = CALLMONITOR_STATE_RINGING
            call = self._start_call(line, CALLMONITOR_STATE_RINGING, "incoming", "from")
        elif line.kind == "CALL":
            event_state = CALLMONITOR_STATE_DIALING
            call = self._start_call(line, CALLMONITOR_STATE_DIALING, "outgoing", "to")
        elif line.kind == "CONNECT":
            event_state = CALLMONITOR_STATE_TALKING
            call = self._connect_call(line, call)
        else:
            event_state = CALLMONITOR_STATE_IDLE
            call = self._end_call(line, call)

        context = Context()
        self._publish(event_state, call, context)
        if line.kind in ("RING", "CALL") and self._worth_online_lookup(call):
            self._spawn(self._async_enrich(call.connection_id, call.attributes["from"]))

    def _start_call(
        self, line: MonitorLine, phase: str, direction: str, other: str
    ) -> ActiveCall:
        """`other` names the leg that is the far end of the call."""
        attributes: dict[str, Any] = {
            "type": direction,
            "from": line.fields["from"],
            "to": line.fields["to"],
            "device": line.fields["device"],
            "initiated": line.timestamp,
        }
        number = attributes[other]
        name, vip = self._coordinator.resolve_contact(number)
        attributes[f"{other}_name"] = name
        attributes["vip"] = vip
        attributes["area_name"] = self._coordinator.get_area_name(number)
        call = ActiveCall(line.connection_id, phase, attributes)
        self._active[line.connection_id] = call
        return call

    def _connect_call(self, line: MonitorLine, call: ActiveCall | None) -> ActiveCall:
        if call is None:
            # Home Assistant started in the middle of the call.
            call = ActiveCall(line.connection_id, CALLMONITOR_STATE_TALKING, {})
            self._active[line.connection_id] = call
        call.phase = CALLMONITOR_STATE_TALKING
        number = line.fields["with"]
        call.attributes.update(
            {
                "with": number,
                "device": line.fields["device"],
                "accepted": line.timestamp,
            }
        )
        # CONNECT doesn't repeat RING/CALL's `initiated` timestamp - it stays
        # in the attributes, so the summary can show how long it rang.
        name, vip = self._coordinator.resolve_contact(number)
        call.attributes["with_name"] = name
        call.attributes["vip"] = vip
        call.attributes["area_name"] = self._coordinator.get_area_name(number)
        return call

    def _end_call(self, line: MonitorLine, call: ActiveCall | None) -> ActiveCall:
        """DISCONNECT carries only `duration` (exact seconds): keep whoever
        the call resolved to so the final state is a full call summary."""
        attributes = dict(call.attributes) if call else {}
        attributes["duration"] = line.fields["duration"]
        attributes["closed"] = line.timestamp
        attributes["duration_formatted"] = format_call_duration(attributes["duration"])
        # `accepted` (if the call was answered) is the direct start of the
        # talking window; otherwise derive it from closed - duration.
        attributes["started"] = attributes.get("accepted") or compute_call_start(
            attributes["closed"], attributes["duration"]
        )
        if attributes.get("initiated") and attributes.get("accepted"):
            ring_seconds = seconds_between(attributes["initiated"], attributes["accepted"])
            attributes["ring_duration_formatted"] = format_call_duration(
                str(ring_seconds) if ring_seconds is not None else None
            )
        self._active.pop(line.connection_id, None)
        self._last_summary = attributes
        return ActiveCall(line.connection_id, CALLMONITOR_STATE_IDLE, attributes)

    def _worth_online_lookup(self, call: ActiveCall) -> bool:
        return (
            call.attributes.get("type") == "incoming"
            and bool(call.attributes.get("from"))
            and not call.attributes.get("from_name")
        )

    async def _async_enrich(self, connection_id: str, number: str) -> None:
        """Spam check and reverse lookup, once the call is already shown."""
        phoneblock, reverse = await asyncio.gather(
            self._coordinator.async_check_phoneblock(number),
            self._coordinator.async_identify_caller(number),
        )
        found: dict[str, Any] = {}
        if phoneblock is not None:
            found.update(
                is_spam=phoneblock.is_spam,
                spam_confidence=phoneblock.spam_confidence,
                spam_rating=phoneblock.rating,
                spam_location=phoneblock.location,
            )
        if reverse is not None and reverse.name:
            found.update(reverse_name=reverse.name, reverse_category=reverse.category)
        if not found:
            return

        call = self._active.get(connection_id)
        # The box reuses connection ids: a different call may hold this one now.
        if call is not None and call.attributes.get("from") != number:
            return
        if call is not None:
            call.attributes.update(found)
            self._publish(call.phase, call, Context(), enriched=True)
        elif self._last_summary.get("from") == number:
            # The call ended while the lookup was running; the summary the
            # idle state shows can still learn the verdict.
            self._last_summary.update(found)
            if not self._active:
                self.attributes = dict(self._last_summary)
                self._notify()

    def _publish(
        self, event_state: str, call: ActiveCall, context: Context, *, enriched: bool = False
    ) -> None:
        """Recompute the entity state, fire the call event, tell the entities."""
        self._recompute()
        payload = self._event_payload(event_state, call.attributes, enriched)
        self.hass.bus.async_fire(EVENT_CALL, payload, context=context)
        for listener in list(self._event_listeners):
            listener("updated" if enriched else _EVENT_TYPE.get(event_state, event_state), payload)
        self._notify(context)

    def _forget_calls(self) -> None:
        """Calls seen before a connection loss may have ended unseen (their
        DISCONNECT was lost); keeping them would pin the state forever."""
        if self._active:
            self._active.clear()
            self._recompute()

    def _recompute(self) -> None:
        """The entity shows the most important of the calls still going on -
        or the last call's summary once none is."""
        if not self._active:
            self.state = CALLMONITOR_STATE_IDLE
            self.attributes = dict(self._last_summary)
            return
        best = max(
            self._active.values(),
            key=lambda call: _PHASE_PRIORITY.get(call.phase, 0),
        )
        self.state = best.phase
        self.attributes = dict(best.attributes)

    def _event_payload(
        self, state: str, attributes: dict[str, Any], enriched: bool
    ) -> dict[str, Any]:
        """Flatten the call attributes into the event payload that
        logbook.py phrases its message from."""
        direction = attributes.get("type")
        # CONNECT/DISCONNECT name the other party as `with`; RING and CALL
        # only ever fill the leg matching their direction.
        other = "to" if direction == "outgoing" else "from"
        entry = self._coordinator.entry
        return {
            "config_entry_id": entry.entry_id,
            "host": self._host,
            "call_state": state,
            "direction": direction,
            "number": attributes.get("with") or attributes.get(other),
            "name": attributes.get("with_name") or attributes.get(f"{other}_name"),
            "reverse_name": attributes.get("reverse_name"),
            "area_name": attributes.get("area_name"),
            "device": attributes.get("device"),
            "vip": bool(attributes.get("vip")),
            "is_spam": bool(attributes.get("is_spam")),
            "spam_confidence": attributes.get("spam_confidence"),
            "duration_formatted": attributes.get("duration_formatted"),
            "ring_duration_formatted": attributes.get("ring_duration_formatted"),
            "answered": bool(attributes.get("accepted")),
            "enriched": enriched,
        }

    def _spawn(self, coro) -> None:
        task = self.hass.async_create_background_task(coro, f"{DOMAIN} call lookup")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


# Event entity vocabulary for the raw call states.
_EVENT_TYPE = {
    CALLMONITOR_STATE_RINGING: "ringing",
    CALLMONITOR_STATE_DIALING: "dialing",
    CALLMONITOR_STATE_TALKING: "talking",
    CALLMONITOR_STATE_IDLE: "ended",
}

