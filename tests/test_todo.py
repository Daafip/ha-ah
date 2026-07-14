"""Tests for the shopping list todo entity."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError
from custom_components.albert_heijn.const import (
    CONF_LIST_ENABLED,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

from .const import LIST_ITEMS, MEMBER_ID, REFRESH_TOKEN, make_client


async def _setup(hass: HomeAssistant, options=None, client=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options=options or {},
    )
    entry.add_to_hass(hass)
    client = client or make_client()
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


def _entity_id(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("todo", DOMAIN, f"{MEMBER_ID}_shopping_list")


async def test_disabled_by_default_no_entity_no_calls(hass: HomeAssistant):
    entry, client = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert _entity_id(hass) is None
    assert client.async_get_list_items.await_count == 0


async def test_entity_state_and_items(hass: HomeAssistant):
    await _setup(hass, options={CONF_LIST_ENABLED: True})
    entity_id = _entity_id(hass)
    assert entity_id is not None

    # State is the number of items still needing action.
    assert hass.states.get(entity_id).state == "1"

    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    items = response[entity_id]["items"]
    assert [(item["summary"], item["status"]) for item in items] == [
        ("luiers", "needs_action"),
        ("melk", "completed"),
    ]
    # The description doubles as the uid (the API merges by description).
    assert items[0]["uid"] == "luiers"


async def test_first_refresh_failure_keeps_entry_loaded(hass: HomeAssistant):
    client = make_client()
    client.async_get_list_items.side_effect = AhApiError("down")
    entry, _ = await _setup(hass, options={CONF_LIST_ENABLED: True}, client=client)

    assert entry.state is ConfigEntryState.LOADED
    entity_id = _entity_id(hass)
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "unavailable"


async def test_add_item_creates_free_text_and_refreshes(hass: HomeAssistant):
    _, client = await _setup(hass, options={CONF_LIST_ENABLED: True})
    entity_id = _entity_id(hass)
    fetches_before = client.async_get_list_items.await_count

    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": entity_id, "item": "kaas"},
        blocking=True,
    )
    await hass.async_block_till_done()

    client.async_add_free_text_item.assert_awaited_once_with("kaas")
    assert client.async_get_list_items.await_count > fetches_before


async def test_complete_item_checks_it(hass: HomeAssistant):
    _, client = await _setup(hass, options={CONF_LIST_ENABLED: True})

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": _entity_id(hass), "item": "luiers", "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()

    client.async_set_item_checked.assert_awaited_once_with(LIST_ITEMS[0], True)


async def test_uncomplete_item_unchecks_it(hass: HomeAssistant):
    _, client = await _setup(hass, options={CONF_LIST_ENABLED: True})

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": _entity_id(hass), "item": "melk", "status": "needs_action"},
        blocking=True,
    )
    await hass.async_block_till_done()

    client.async_set_item_checked.assert_awaited_once_with(LIST_ITEMS[1], False)


async def test_rename_raises(hass: HomeAssistant):
    _, client = await _setup(hass, options={CONF_LIST_ENABLED: True})

    with pytest.raises(HomeAssistantError, match="not supported"):
        await hass.services.async_call(
            "todo",
            "update_item",
            {"entity_id": _entity_id(hass), "item": "luiers", "rename": "pampers"},
            blocking=True,
        )
    client.async_set_item_checked.assert_not_awaited()


async def test_remove_item_deletes_from_list(hass: HomeAssistant):
    _, client = await _setup(hass, options={CONF_LIST_ENABLED: True})

    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": _entity_id(hass), "item": ["luiers"]},
        blocking=True,
    )
    await hass.async_block_till_done()

    client.async_delete_list_items.assert_awaited_once_with([LIST_ITEMS[0]])


async def test_service_error_maps_to_homeassistant_error(hass: HomeAssistant):
    client = make_client()
    client.async_add_free_text_item.side_effect = AhApiError("nope")
    _, _ = await _setup(hass, options={CONF_LIST_ENABLED: True}, client=client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo",
            "add_item",
            {"entity_id": _entity_id(hass), "item": "kaas"},
            blocking=True,
        )
