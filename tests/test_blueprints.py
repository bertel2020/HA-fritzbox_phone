"""The shipped blueprints load and do what they say."""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_capture_events

BLUEPRINTS = Path(__file__).parent.parent / "blueprints" / "automation" / "fritzbox_phone"


@pytest.fixture
def installed(hass: HomeAssistant):
    target = Path(hass.config.path("blueprints", "automation", "fritzbox_phone"))
    target.mkdir(parents=True, exist_ok=True)
    for blueprint in BLUEPRINTS.glob("*.yaml"):
        shutil.copy(blueprint, target / blueprint.name)


async def _automation(hass: HomeAssistant, name: str, inputs: dict) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {"path": f"fritzbox_phone/{name}.yaml", "input": inputs}
            }
        },
    )
    await hass.async_block_till_done()


async def test_missed_call_blueprint(hass: HomeAssistant, installed) -> None:
    await _automation(
        hass,
        "notify_missed_call",
        {
            "notify": [
                {
                    "event": "test_missed",
                    "event_data": {"text": "{{ caller }} {{ place }} spam={{ is_spam }}"},
                }
            ]
        },
    )
    seen = async_capture_events(hass, "test_missed")

    hass.bus.async_fire(
        "fritzbox_phone_missed_call",
        {
            "added": [
                {"name": "Anna", "number": "030", "area_name": "Berlin", "is_spam": False},
                {"name": None, "number": "0900", "area_name": None, "is_spam": True},
            ],
            "added_count": 2,
            "removed": 0,
        },
    )
    await hass.async_block_till_done()

    # The spam call is skipped by default.
    assert [event.data["text"] for event in seen] == ["Anna (Berlin) spam=False"]


async def test_missed_call_blueprint_ignores_pure_removals(hass: HomeAssistant, installed) -> None:
    await _automation(
        hass, "notify_missed_call", {"notify": [{"event": "test_missed"}]}
    )
    seen = async_capture_events(hass, "test_missed")
    hass.bus.async_fire("fritzbox_phone_missed_call", {"added": [], "added_count": 0, "removed": 1})
    await hass.async_block_till_done()
    assert seen == []


async def test_spam_alert_blueprint(hass: HomeAssistant, installed) -> None:
    await _automation(
        hass,
        "spam_call_alert",
        {
            "action_on_spam": [
                {
                    "event": "test_spam",
                    "event_data": {"text": "{{ number }}|{{ name }}|{{ confidence }}"},
                }
            ],
            "min_confidence": 60,
        },
    )
    seen = async_capture_events(hass, "test_spam")

    def ring(**data):
        hass.bus.async_fire(
            "fritzbox_phone_call", {"call_state": "ringing", "is_spam": True, **data}
        )

    ring(number="0900", name=None, reverse_name="Teleshop", spam_confidence=90)
    ring(number="0901", name=None, spam_confidence=40)  # below the threshold
    hass.bus.async_fire("fritzbox_phone_call", {"call_state": "ringing", "is_spam": False})
    await hass.async_block_till_done()

    assert [event.data["text"] for event in seen] == ["0900|Teleshop|90"]
