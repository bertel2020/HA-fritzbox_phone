"""Real-time FRITZ!Box call monitor (CallMonitor protocol, port 1012).

The CallMonitor service has to be activated once per box by dialing
`#96*5*` from any phone connected to it (`#96*4*` deactivates it again).
Once active, the box pushes semicolon-separated event lines for every
RING / CALL / CONNECT / DISCONNECT over a plain TCP socket.

This wraps `fritzconnection.core.fritzmonitor.FritzMonitor` (the same
building block used by Home Assistant core's own `fritzbox_callmonitor`
integration) and mirrors its event field layout and reconnect behaviour,
so this sensor behaves the same way the built-in one does.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging
import queue
import re
from threading import Event as ThreadingEvent, Thread
from typing import Any

from fritzconnection.core.fritzmonitor import FritzMonitor

from .const import (
    CALLMONITOR_STATE_DIALING,
    CALLMONITOR_STATE_IDLE,
    CALLMONITOR_STATE_RINGING,
    CALLMONITOR_STATE_TALKING,
)

_LOGGER = logging.getLogger(__name__)

NUMBER_STRIP_RE = re.compile(r"[^\d+]")
_DATE_FORMAT_IN = "%d.%m.%y %H:%M:%S"


def normalize_number(number: str | None) -> str:
    """Strip everything but digits and a leading '+' for number comparison."""
    return NUMBER_STRIP_RE.sub("", number or "")


class FritzCallMonitor:
    """Connects to the CallMonitor socket and reports call state changes."""

    def __init__(
        self,
        host: str,
        port: int,
        on_update: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._host = host
        self._port = port
        self._on_update = on_update
        self._monitor: FritzMonitor | None = None
        self._stopped = ThreadingEvent()
        self._reader_thread: Thread | None = None

    def connect(self) -> None:
        """Open the CallMonitor connection. Blocking, run in an executor."""
        self._stopped.clear()
        monitor = FritzMonitor(address=self._host, port=self._port)
        try:
            event_queue = monitor.start(reconnect_tries=50, reconnect_delay=120)
        except OSError as err:
            _LOGGER.warning(
                "Anrufmonitor: Verbindung zu %s:%s fehlgeschlagen. Ist der "
                "CallMonitor per #96*5* an einem angeschlossenen Telefon "
                "aktiviert? (%s)",
                self._host,
                self._port,
                err,
            )
            return
        self._monitor = monitor
        self._reader_thread = Thread(
            target=self._read_events, args=(event_queue,), daemon=True
        )
        self._reader_thread.start()

    def disconnect(self) -> None:
        """Close the CallMonitor connection. Blocking, run in an executor."""
        self._stopped.set()
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _read_events(self, event_queue: "queue.Queue[str]") -> None:
        while not self._stopped.is_set():
            try:
                event = event_queue.get(timeout=10)
            except queue.Empty:
                continue
            self._parse(event)

    def _parse(self, event: str) -> None:
        """Parse one CallMonitor line and forward (state, attributes)."""
        parts = event.split(";")
        if len(parts) < 2:
            return
        try:
            timestamp = datetime.strptime(parts[0], _DATE_FORMAT_IN).isoformat()
        except ValueError:
            timestamp = None
        line_type = parts[1]
        try:
            if line_type == "RING":
                self._on_update(
                    CALLMONITOR_STATE_RINGING,
                    {
                        "type": "incoming",
                        "from": parts[3],
                        "to": parts[4],
                        "device": parts[5],
                        "initiated": timestamp,
                    },
                )
            elif line_type == "CALL":
                self._on_update(
                    CALLMONITOR_STATE_DIALING,
                    {
                        "type": "outgoing",
                        "from": parts[4],
                        "to": parts[5],
                        "device": parts[6],
                        "initiated": timestamp,
                    },
                )
            elif line_type == "CONNECT":
                self._on_update(
                    CALLMONITOR_STATE_TALKING,
                    {
                        "with": parts[4],
                        "device": parts[3],
                        "accepted": timestamp,
                    },
                )
            elif line_type == "DISCONNECT":
                self._on_update(
                    CALLMONITOR_STATE_IDLE,
                    {"duration": parts[3], "closed": timestamp},
                )
        except IndexError:
            _LOGGER.debug("Unerwartetes CallMonitor-Event: %s", event)
