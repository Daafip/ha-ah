"""Tests for the config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import (
    CONF_CODE,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

from .const import MEMBER_ID, REFRESH_TOKEN


def _patch_client(exchange_side_effect=None, member_id=MEMBER_ID):
    client = AsyncMock()
    client.async_exchange_code.return_value = REFRESH_TOKEN
    client.async_exchange_code.side_effect = exchange_side_effect
    client.async_get_member_id.return_value = member_id
    return patch("custom_components.albert_heijn.config_flow.AhApiClient", return_value=client), client


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_user_flow_happy_path(hass: HomeAssistant):
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    patcher, client = _patch_client()
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "RAWCODE"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Albert Heijn"
    assert result["data"] == {CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID}
    assert result["result"].unique_id == MEMBER_ID
    client.async_exchange_code.assert_awaited_once_with("RAWCODE")


async def test_user_flow_accepts_full_url(hass: HomeAssistant):
    result = await _start_user_flow(hass)
    patcher, client = _patch_client()
    with patcher:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CODE: "appie://login-exit?code=ABC123&state=xyz"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    client.async_exchange_code.assert_awaited_once_with("ABC123")


async def test_user_flow_invalid_code(hass: HomeAssistant):
    result = await _start_user_flow(hass)
    patcher, _ = _patch_client(exchange_side_effect=AhAuthError("rejected"))
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "EXPIRED"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant):
    result = await _start_user_flow(hass)
    patcher, _ = _patch_client(exchange_side_effect=AhApiError("down"))
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "CODE"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass: HomeAssistant):
    result = await _start_user_flow(hass)
    patcher, _ = _patch_client(exchange_side_effect=RuntimeError("boom"))
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "CODE"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_duplicate_account_aborts(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, unique_id=MEMBER_ID).add_to_hass(hass)
    result = await _start_user_flow(hass)
    patcher, _ = _patch_client()
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "CODE"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_token(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: "stale-token", CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    patcher, _ = _patch_client()
    with patcher, patch("custom_components.albert_heijn.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "NEWCODE"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == REFRESH_TOKEN


async def test_reauth_wrong_account_aborts(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: "stale-token", CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    patcher, _ = _patch_client(member_id="7654321")
    with patcher:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CODE: "NEWCODE"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_REFRESH_TOKEN] == "stale-token"
