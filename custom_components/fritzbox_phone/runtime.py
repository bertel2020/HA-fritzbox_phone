"""Typed runtime data of a config entry."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .callmonitor import FritzCallMonitor
from .coordinator import FritzBoxPhoneCoordinator


@dataclass
class FritzBoxPhoneRuntimeData:
    """What a loaded entry keeps alive."""

    coordinator: FritzBoxPhoneCoordinator
    # None when the call monitor is switched off in the options.
    call_monitor: FritzCallMonitor | None = None


type FritzBoxPhoneConfigEntry = ConfigEntry[FritzBoxPhoneRuntimeData]
