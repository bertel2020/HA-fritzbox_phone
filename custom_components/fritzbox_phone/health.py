"""Health of an online lookup service (PhoneBlock, Tellows).

The lookups are best-effort side enrichment, so a failure is swallowed
instead of breaking a poll. That makes a dead service invisible: a wrong
PhoneBlock password simply means "no spam is ever found". This keeps count
so the integration can say so - in the log once, and as a diagnostic
sensor. Only the kind of error is kept, never a number or a URL.
"""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# One lost request is a hiccup; this many in a row is an outage.
FAILURES_FOR_ERROR = 3
_AUTH_STATUSES = (401, 403)

STATUS_UNKNOWN = "unknown"
STATUS_OK = "ok"
STATUS_ERROR = "error"


def describe_error(err: BaseException) -> str:
    """Exception type and, for an HTTP error, its status code."""
    status = getattr(err, "status", None)
    name = type(err).__name__
    return f"{name} {status}" if isinstance(status, int) else name


class LookupHealth:
    """Consecutive failures and the last success of one lookup service."""

    def __init__(self, service: str) -> None:
        self.service = service
        self.consecutive_failures = 0
        self.last_success: datetime | None = None
        self.last_error: str | None = None

    @property
    def status(self) -> str:
        if self.consecutive_failures >= FAILURES_FOR_ERROR:
            return STATUS_ERROR
        return STATUS_OK if self.last_success else STATUS_UNKNOWN

    def record_success(self) -> None:
        if self.consecutive_failures >= FAILURES_FOR_ERROR:
            _LOGGER.info("%s antwortet wieder", self.service)
        self.consecutive_failures = 0
        self.last_success = dt_util.utcnow()

    def record_failure(self, err: BaseException) -> None:
        self.consecutive_failures += 1
        self.last_error = describe_error(err)
        if self.consecutive_failures == FAILURES_FOR_ERROR:
            # Said once per outage; the details stay on debug level.
            hint = (
                " Zugangsdaten in den Optionen prüfen."
                if getattr(err, "status", None) in _AUTH_STATUSES
                else ""
            )
            _LOGGER.warning(
                "%s: %s Abfragen in Folge fehlgeschlagen (%s) - Spam- und "
                "Namensauflösung sind derzeit nicht verfügbar.%s",
                self.service,
                self.consecutive_failures,
                self.last_error,
                hint,
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
        }
