"""Shared fixtures for the FRITZ!Box phone tests."""
from __future__ import annotations

import queue

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/ from this repository."""
    yield


class FakeMonitor:
    """Stands in for fritzconnection's FritzMonitor (no sockets in tests)."""

    instances: list[FakeMonitor] = []
    fail_times = 0

    def __init__(self, address: str, port: int) -> None:
        self.address = address
        self.port = port
        self.alive = False
        self.queue: queue.Queue[str] = queue.Queue()
        FakeMonitor.instances.append(self)

    def start(self, reconnect_tries: int = 0, reconnect_delay: float = 0) -> queue.Queue[str]:
        if FakeMonitor.fail_times > 0:
            FakeMonitor.fail_times -= 1
            raise OSError("connection refused")
        self.alive = True
        return self.queue

    @property
    def is_alive(self) -> bool:
        return self.alive

    def stop(self) -> None:
        self.alive = False


@pytest.fixture
def fake_monitor(monkeypatch):
    FakeMonitor.instances = []
    FakeMonitor.fail_times = 0
    monkeypatch.setattr("custom_components.fritzbox_phone.callmonitor.FritzMonitor", FakeMonitor)
    monkeypatch.setattr("custom_components.fritzbox_phone.callmonitor.READER_POLL_SECONDS", 0.05)
    return FakeMonitor
