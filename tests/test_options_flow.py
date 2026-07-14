"""Tests for the options flow and applying the poll interval."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.const import (
    CONF_LIST_ENABLED,
    CONF_LIST_SCAN_INTERVAL,
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
    # The untouched list options are stored with their defaults.
    assert entry.options == {CONF_UPDATE_INTERVAL: 12, CONF_LIST_ENABLED: False, CONF_LIST_SCAN_INTERVAL: 120}
    assert entry.runtime_data.update_interval == timedelta(hours=12)
    assert entry.state is ConfigEntryState.LOADED
    # Applied in place: the integration must not have been re-set-up.
    assert client_cls.call_count == 1


async def test_enabling_list_reloads_and_adds_entity(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)
    client = make_client()
    # The patch stays active across the options change: enabling the list
    # reloads the entry, which constructs a new client.
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client) as client_cls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert client.async_get_list_items.await_count == 0
        assert hass.states.async_entity_ids("todo") == []

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_LIST_ENABLED: True, CONF_LIST_SCAN_INTERVAL: 120},
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.state is ConfigEntryState.LOADED
        assert client_cls.call_count == 2  # reloaded
        assert entry.runtime_data.list_coordinator is not None
        assert client.async_get_list_items.await_count > 0
        (entity_id,) = hass.states.async_entity_ids("todo")
        assert hass.states.get(entity_id).state == "1"

        # Turning it off again removes the entity; the registry keeps it as a
        # restored, unavailable placeholder for when it is re-enabled.
        fetches = client.async_get_list_items.await_count
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_LIST_ENABLED: False, CONF_LIST_SCAN_INTERVAL: 120},
        )
        await hass.async_block_till_done()

        assert entry.runtime_data.list_coordinator is None
        assert hass.states.get(entity_id).state == "unavailable"
        assert client.async_get_list_items.await_count == fetches  # polling stopped


async def test_list_interval_change_applies_without_reload(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options={CONF_UPDATE_INTERVAL: 6, CONF_LIST_ENABLED: True, CONF_LIST_SCAN_INTERVAL: 120},
    )
    entry.add_to_hass(hass)
    client = make_client()
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client) as client_cls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.list_coordinator.update_interval == timedelta(seconds=120)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_UPDATE_INTERVAL: 6, CONF_LIST_ENABLED: True, CONF_LIST_SCAN_INTERVAL: 300},
        )
        await hass.async_block_till_done()

    assert entry.runtime_data.list_coordinator.update_interval == timedelta(seconds=300)
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
