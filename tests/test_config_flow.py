"""Config flow: credential validation and PhoneBlock option handling."""
from __future__ import annotations

from unittest.mock import patch

from fritzconnection.core.exceptions import (
    FritzAuthorizationError,
    FritzConnectionException,
)
import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fritzbox_phone.const import (
    CONF_PHONEBLOCK_ENABLED,
    CONF_PHONEBLOCK_PASSWORD,
    CONF_PHONEBLOCK_USERNAME,
    DOMAIN,
)

USER_INPUT = {CONF_HOST: "fritz.box", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}
CLIENT = "custom_components.fritzbox_phone.config_flow.FritzBoxPhoneClient"


def _client(serial="ABC123", connect_error=None):
    class _Client:
        serial_number = serial

        def __init__(self, **kwargs):
            pass

        def connect(self):
            if connect_error is not None:
                raise connect_error

    return _Client


@pytest.fixture(autouse=True)
def no_setup():
    with patch(
        "custom_components.fritzbox_phone.async_setup_entry", return_value=True
    ):
        yield


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(CLIENT, _client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "fritz.box"
    assert result["result"].unique_id == "ABC123"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FritzAuthorizationError("nope"), "invalid_auth"),
        (FritzConnectionException("down"), "cannot_connect"),
        (OSError("unreachable"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, error, expected) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(CLIENT, _client(connect_error=error)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_duplicate_box_is_aborted(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="ABC123", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(CLIENT, _client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_keep_stored_phoneblock_password(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABC123",
        data=USER_INPUT,
        options={
            CONF_PHONEBLOCK_ENABLED: True,
            CONF_PHONEBLOCK_USERNAME: "pb",
            CONF_PHONEBLOCK_PASSWORD: "stored",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # The stored password must not be pre-filled into the form.
    password_key = next(
        key for key in result["data_schema"].schema if str(key) == CONF_PHONEBLOCK_PASSWORD
    )
    assert password_key.default is vol.UNDEFINED

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PHONEBLOCK_ENABLED: True, CONF_PHONEBLOCK_USERNAME: "pb"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PHONEBLOCK_PASSWORD] == "stored"


async def test_options_require_phoneblock_credentials(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ABC123", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PHONEBLOCK_ENABLED: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "phoneblock_credentials_required"}


async def test_reauth_updates_credentials(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ABC123", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(CLIENT, _client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"


async def test_reauth_rejects_other_box(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ABC123", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(CLIENT, _client(serial="OTHER")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "user", CONF_PASSWORD: "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_PASSWORD] == "secret"


async def test_reconfigure_changes_host(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ABC123", data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with patch(CLIENT, _client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.178.1", CONF_USERNAME: "user", CONF_PASSWORD: "secret"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.178.1"
