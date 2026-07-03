"""Tests for setup and unload of the integration."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import CONF_MEMBER_ID, CONF_REFRESH_TOKEN, DOMAIN

from .const import KOOPZEGELS_DATA, MEMBER_ID, REFRESH_TOKEN


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Albert Heijn",
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
    )


def _patch_client():
    client = AsyncMock()
    client.async_get_koopzegels.return_value = KOOPZEGELS_DATA
    return patch("custom_components.albert_heijn.AhApiClient", return_value=client), client


async def test_setup_and_unload(hass: HomeAssistant):
    entry = _make_entry()
    entry.add_to_hass(hass)
    patcher, _ = _patch_client()
    with patcher:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{MEMBER_ID}_koopzegels")
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_api_error_sets_retry(hass: HomeAssistant):
    entry = _make_entry()
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    client.async_get_koopzegels.side_effect = AhApiError("down")
    with patcher:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_error_starts_reauth(hass: HomeAssistant):
    entry = _make_entry()
    entry.add_to_hass(hass)
    patcher, client = _patch_client()
    client.async_get_koopzegels.side_effect = AhAuthError("expired")
    with patcher:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_rotated_refresh_token_is_persisted(hass: HomeAssistant):
    entry = _make_entry()
    entry.add_to_hass(hass)
    patcher, _ = _patch_client()
    with patcher as client_cls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        save_callback = client_cls.call_args.kwargs["token_updated_callback"]
        save_callback("rotated-refresh-token")
        await hass.async_block_till_done()
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated-refresh-token"
