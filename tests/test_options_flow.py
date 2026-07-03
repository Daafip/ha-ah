"""Tests for the options flow and applying the poll interval."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.const import (
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

from .const import MEMBER_ID, REFRESH_TOKEN, make_client


async def _setup(hass: HomeAssistant, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options=options or {},
    )
    entry.add_to_hass(hass)
    client = make_client()
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client) as client_cls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client_cls


async def test_interval_option_read_at_setup(hass: HomeAssistant):
    entry, _ = await _setup(hass, options={CONF_UPDATE_INTERVAL: 2})
    assert entry.runtime_data.update_interval == timedelta(hours=2)


async def test_options_flow_updates_interval_without_reload(hass: HomeAssistant):
    entry, client_cls = await _setup(hass)
    assert entry.runtime_data.update_interval == timedelta(hours=6)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={CONF_UPDATE_INTERVAL: 12})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_UPDATE_INTERVAL: 12}
    assert entry.runtime_data.update_interval == timedelta(hours=12)
    assert entry.state is ConfigEntryState.LOADED
    # Applied in place: the integration must not have been re-set-up.
    assert client_cls.call_count == 1


async def test_token_rotation_does_not_reload(hass: HomeAssistant):
    entry, client_cls = await _setup(hass)
    save_callback = client_cls.call_args.kwargs["token_updated_callback"]
    save_callback("rotated-token")
    await hass.async_block_till_done()

    assert entry.data[CONF_REFRESH_TOKEN] == "rotated-token"
    assert entry.state is ConfigEntryState.LOADED
    assert client_cls.call_count == 1
