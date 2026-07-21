"""Tests for syncing directly into an existing todo entity (e.g. todo.shopping_list)."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhListItem
from custom_components.albert_heijn.const import (
    CONF_LIST_ENABLED,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    CONF_SYNC_TARGET_ENTITY,
    DOMAIN,
)

from .const import MEMBER_ID, REFRESH_TOKEN, make_client

TARGET = "todo.shopping_list"


class FakeAhList:
    """A stand-in for the list side of the real API's merge-by-description semantics.

    Built on top of make_client() (which already stubs the unrelated koopzegels
    /receipts/etc. endpoints the main coordinator also needs), overriding only
    the list methods to actually mutate state on add/check/delete. That lets
    push -> forced refresh -> pull convergence be tested for real instead of
    assuming a fixed snapshot.
    """

    def __init__(self, items: list[AhListItem]) -> None:
        self.items: dict[str, AhListItem] = {item.description: item for item in items}

    def client(self) -> AsyncMock:
        client = make_client()
        client.async_get_list_items.side_effect = self._get_items
        client.async_add_free_text_item.side_effect = self._add_free_text_item
        client.async_set_item_checked.side_effect = self._set_item_checked
        client.async_delete_list_items.side_effect = self._delete_list_items
        return client

    async def _get_items(self) -> list[AhListItem]:
        return list(self.items.values())

    async def _add_free_text_item(self, description: str, quantity: int = 1) -> None:
        if description not in self.items:  # the real API merges, so a repeat add is a no-op
            self.items[description] = AhListItem(description=description, checked=False, quantity=quantity)

    async def _set_item_checked(self, item: AhListItem, checked: bool) -> None:
        current = self.items.get(item.description, item)
        self.items[item.description] = replace(current, checked=checked)

    async def _delete_list_items(self, items: list[AhListItem]) -> None:
        for item in items:
            self.items.pop(item.description, None)


@pytest.fixture(autouse=True)
def _clean_shopping_list_file(hass: HomeAssistant):
    """The core shopping_list integration persists to a flat file in the test
    config dir, which pytest-homeassistant-custom-component does not reset
    between runs (only its .storage/ mocks are isolated per test). Without
    this, items from earlier runs bleed into later ones.
    """
    Path(hass.config.path(".shopping_list.json")).unlink(missing_ok=True)
    yield
    Path(hass.config.path(".shopping_list.json")).unlink(missing_ok=True)


async def _setup_shopping_list(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="shopping_list")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _setup_ah(hass: HomeAssistant, client: AsyncMock):
    await _setup_shopping_list(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options={CONF_LIST_ENABLED: True, CONF_SYNC_TARGET_ENTITY: TARGET},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _target_items(hass: HomeAssistant) -> list[dict]:
    response = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TARGET}, blocking=True, return_response=True
    )
    return response[TARGET]["items"]


async def _target_item(hass: HomeAssistant, summary: str) -> dict:
    return next(i for i in await _target_items(hass) if i["summary"] == summary)


async def _add_to_target(hass: HomeAssistant, item: str) -> None:
    await hass.services.async_call("todo", "add_item", {"entity_id": TARGET, "item": item}, blocking=True)
    await hass.async_block_till_done()


async def _complete_in_target(hass: HomeAssistant, uid: str) -> None:
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": TARGET, "item": uid, "status": "completed"}, blocking=True
    )
    await hass.async_block_till_done()


def _list_coordinator(hass: HomeAssistant):
    """The AH config entry's list coordinator (there is only one entry in these tests)."""
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    return entry.runtime_data.list_coordinator


async def test_no_dedicated_entity_when_target_configured(hass: HomeAssistant):
    fake = FakeAhList([])
    entry = await _setup_ah(hass, fake.client())
    assert entry.runtime_data.sync_target_entity_id == TARGET
    assert entry.runtime_data.list_sync_manager is not None
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("todo", DOMAIN, f"{MEMBER_ID}_shopping_list") is None
    # No extra AH-owned todo entity: only the pre-existing shopping_list one.
    assert hass.states.async_entity_ids("todo") == [TARGET]


async def test_new_ha_item_is_pushed_to_ah(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())

    await _add_to_target(hass, "kaas")

    assert "kaas" in fake.items
    assert fake.items["kaas"].checked is False


async def test_completed_ha_item_is_checked_on_ah(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="luiers", checked=False)])
    await _setup_ah(hass, fake.client())

    await _add_to_target(hass, "luiers")
    assert fake.items["luiers"].checked is False  # merge: adding an existing item is a no-op

    item = await _target_item(hass, "luiers")
    await _complete_in_target(hass, item["uid"])

    assert fake.items["luiers"].checked is True


async def test_case_and_whitespace_insensitive_matching(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="luiers", checked=False)])
    await _setup_ah(hass, fake.client())

    # HA trims on add, so this is stored as "Luiers"; matching against the AH
    # side's lowercase "luiers" must still work.
    await _add_to_target(hass, "  Luiers ")
    item = await _target_item(hass, "Luiers")
    await _complete_in_target(hass, item["uid"])

    assert fake.items["luiers"].checked is True


async def test_ah_checked_item_converges_immediately_via_push(hass: HomeAssistant):
    """Adding an already-checked AH item to HA converges without a separate poll.

    The push handler always forces an immediate coordinator refresh, whose
    listener runs the pull step straight away — no need to wait for the next
    scheduled poll for this case.
    """
    fake = FakeAhList([AhListItem(description="melk", checked=True, product_id=12345, quantity=2)])
    await _setup_ah(hass, fake.client())

    await _add_to_target(hass, "melk")

    item = await _target_item(hass, "melk")
    assert item["status"] == "completed"


async def test_ah_open_item_is_not_touched_in_ha(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="luiers", checked=False)])
    await _setup_ah(hass, fake.client())

    await _add_to_target(hass, "luiers")

    item = await _target_item(hass, "luiers")
    assert item["status"] == "needs_action"


async def test_ah_side_deletion_is_completed_in_ha_on_next_poll(hass: HomeAssistant):
    """An item checked-in-HA-terms as open, then removed on the AH side between
    polls (e.g. the user deleted it in the app), is completed on the next poll —
    without ever being resurrected on the AH side.
    """
    fake = FakeAhList([AhListItem(description="weg", checked=False)])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "weg")
    assert (await _target_item(hass, "weg"))["status"] == "needs_action"

    # Simulate the user deleting it in the AH app between polls: mutate the AH
    # side directly, bypassing our own delete method.
    del fake.items["weg"]

    await _list_coordinator(hass).async_refresh()
    await hass.async_block_till_done()

    item = await _target_item(hass, "weg")
    assert item["status"] == "completed"
    assert "weg" not in fake.items  # never resurrected on the AH side


async def test_unload_stops_sync(hass: HomeAssistant):
    fake = FakeAhList([])
    entry = await _setup_ah(hass, fake.client())

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await _add_to_target(hass, "na-unload")

    assert fake.items == {}
