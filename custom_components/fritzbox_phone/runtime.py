"""Typed runtime data of a config entry."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import FritzBoxPhoneCoordinator


@dataclass
class FritzBoxPhoneRuntimeData:
    """What a loaded entry keeps alive."""

    coordinator: FritzBoxPhoneCoordinator


type FritzBoxPhoneConfigEntry = ConfigEntry[FritzBoxPhoneRuntimeData]
