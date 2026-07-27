"""Tests for the one-way, on-demand push into the AH shopping list."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.todo import TodoItem, TodoListEntity, TodoListEntityFeature
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.albert_heijn.api import AhApiError, AhListItem
from custom_components.albert_heijn.const import (
    CONF_LIST_ENABLED,
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    CONF_SYNC_TARGET_ENTITY,
    DOMAIN,
    LIST_WRITE_BATCH_SIZE,
    SERVICE_SYNC_SHOPPING_LIST,
)
from custom_components.albert_heijn.sync import AhListSyncManager

from .const import MEMBER_ID, REFRESH_TOKEN, make_client

TARGET = "todo.shopping_list"
BUTTON = "button.albert_heijn_sync_shopping_list"


class FakeAhList:
    """A stand-in for the list side of the real API's merge-by-description semantics.

    Built on top of make_client() (which already stubs the unrelated koopzegels
    /receipts/etc. endpoints the main coordinator also needs), overriding only
    the list methods to actually mutate state. That lets a push be checked
    against what the AH side ends up holding, instead of against the calls we
    happened to make.
    """

    def __init__(self, items: list[AhListItem]) -> None:
        self.items: dict[str, AhListItem] = {item.description: item for item in items}
        self.write_calls: list[list[AhListItem]] = []

    def client(self) -> AsyncMock:
        client = make_client()
        client.async_get_list_items.side_effect = self._get_items
        client.async_write_list_items.side_effect = self._write_items
        return client

    async def _get_items(self) -> list[AhListItem]:
        return list(self.items.values())

    async def _write_items(self, items: list[AhListItem]) -> None:
        # The real client batches; mirror that so tests can count requests.
        for start in range(0, len(items), LIST_WRITE_BATCH_SIZE):
            batch = items[start : start + LIST_WRITE_BATCH_SIZE]
            self.write_calls.append(batch)
            for item in batch:
                current = self.items.get(item.description)
                self.items[item.description] = item if current is None else replace(current, checked=item.checked)


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


class _MemoryTodoList(TodoListEntity):
    """A second, unrelated todo list: in-memory, add-only, no dependencies."""

    _attr_name = "Weekend"
    _attr_should_poll = False
    _attr_supported_features = TodoListEntityFeature.CREATE_TODO_ITEM

    def __init__(self) -> None:
        self._items: list[TodoItem] = []

    @property
    def todo_items(self) -> list[TodoItem]:
        return self._items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        item.uid = str(len(self._items) + 1)
        self._items.append(item)
        self.async_write_ha_state()


@pytest.fixture
async def other_todo_list(hass: HomeAssistant):
    """Set up ``todo.weekend`` through a throwaway mock integration."""

    async def _setup_entry(hass_: HomeAssistant, entry: MockConfigEntry) -> bool:
        await hass_.config_entries.async_forward_entry_setups(entry, [Platform.TODO])
        return True

    async def _setup_todo_platform(hass_, entry, async_add_entities) -> None:
        async_add_entities([_MemoryTodoList()])

    mock_integration(hass, MockModule("other_todo", async_setup_entry=_setup_entry))
    mock_platform(hass, "other_todo.todo", MockPlatform(async_setup_entry=_setup_todo_platform))
    mock_platform(hass, "other_todo.config_flow", MockPlatform())  # only imported, never used
    entry = MockConfigEntry(domain="other_todo")
    entry.add_to_hass(hass)
    with mock_config_flow("other_todo", ConfigFlow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield "todo.weekend"


async def _setup_shopping_list(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="shopping_list")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _setup_ah(hass: HomeAssistant, client: AsyncMock, target: str | None = TARGET):
    await _setup_shopping_list(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options={CONF_LIST_ENABLED: True, CONF_SYNC_TARGET_ENTITY: target or ""},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _target_items(hass: HomeAssistant, entity_id: str = TARGET) -> list[dict]:
    response = await hass.services.async_call(
        "todo", "get_items", {"entity_id": entity_id}, blocking=True, return_response=True
    )
    return response[entity_id]["items"]


async def _target_item(hass: HomeAssistant, summary: str) -> dict:
    return next(i for i in await _target_items(hass) if i["summary"] == summary)


async def _add_to_target(hass: HomeAssistant, item: str, entity_id: str = TARGET) -> None:
    await hass.services.async_call("todo", "add_item", {"entity_id": entity_id, "item": item}, blocking=True)
    await hass.async_block_till_done()


async def _complete_in_target(hass: HomeAssistant, uid: str) -> None:
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": TARGET, "item": uid, "status": "completed"}, blocking=True
    )
    await hass.async_block_till_done()


async def _sync(hass: HomeAssistant, **data) -> dict:
    response = await hass.services.async_call(
        DOMAIN, SERVICE_SYNC_SHOPPING_LIST, data, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return response


async def test_no_dedicated_entity_when_target_configured(hass: HomeAssistant):
    fake = FakeAhList([])
    entry = await _setup_ah(hass, fake.client())
    assert entry.runtime_data.sync_target_entity_id == TARGET
    assert entry.runtime_data.list_sync_manager is not None
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("todo", DOMAIN, f"{MEMBER_ID}_shopping_list") is None
    # No extra AH-owned todo entity: only the pre-existing shopping_list one.
    assert hass.states.async_entity_ids("todo") == [TARGET]


async def test_no_polling_and_no_push_without_the_service(hass: HomeAssistant):
    """Nothing happens on its own: not on an HA change, not on a timer."""
    fake = FakeAhList([])
    entry = await _setup_ah(hass, fake.client())
    assert entry.runtime_data.list_coordinator.update_interval is None

    await _add_to_target(hass, "kaas")

    assert fake.items == {}
    assert fake.write_calls == []


async def test_service_adds_open_ha_items(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "kaas")
    await _add_to_target(hass, "brood")

    response = await _sync(hass)

    assert set(fake.items) == {"kaas", "brood"}
    assert all(item.checked is False for item in fake.items.values())
    assert sorted(response["added"]) == ["brood", "kaas"]
    assert response["checked"] == []
    assert response["source_entity_id"] == TARGET


async def test_service_checks_off_completed_ha_items(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="luiers", checked=False)])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "luiers")
    await _complete_in_target(hass, (await _target_item(hass, "luiers"))["uid"])

    response = await _sync(hass)

    assert fake.items["luiers"].checked is True
    assert response["checked"] == ["luiers"]
    assert response["added"] == []


async def test_case_and_whitespace_insensitive_matching(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="luiers", checked=False)])
    await _setup_ah(hass, fake.client())

    # HA trims on add, so this is stored as "Luiers"; matching against the AH
    # side's lowercase "luiers" must still work — no duplicate, and the check
    # lands on the existing item.
    await _add_to_target(hass, "  Luiers ")
    await _complete_in_target(hass, (await _target_item(hass, "Luiers"))["uid"])
    await _sync(hass)

    assert list(fake.items) == ["luiers"]
    assert fake.items["luiers"].checked is True


async def test_item_checked_in_the_app_is_left_alone(hass: HomeAssistant):
    """You checked it off while shopping; an open HA item must not re-open it."""
    fake = FakeAhList([AhListItem(description="melk", checked=True, product_id=12345, quantity=2)])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "melk")

    response = await _sync(hass)

    assert fake.items["melk"].checked is True
    assert fake.write_calls == []  # nothing to do at all
    assert response == {"source_entity_id": TARGET, "added": [], "checked": [], "unchanged": 1}


async def test_ah_only_items_are_left_alone(hass: HomeAssistant):
    fake = FakeAhList([AhListItem(description="bloemen", checked=False)])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "kaas")

    await _sync(hass)

    assert set(fake.items) == {"bloemen", "kaas"}
    assert fake.items["bloemen"].checked is False


async def test_nothing_is_written_back_into_home_assistant(hass: HomeAssistant):
    """The push is one-way: an item gone from the AH app stays open in HA."""
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "weg")
    await _sync(hass)

    del fake.items["weg"]  # as if deleted in the app
    await _sync(hass)  # re-adds it, because HA still wants it

    assert (await _target_item(hass, "weg"))["status"] == "needs_action"
    assert "weg" in fake.items


async def test_repeated_sync_is_a_no_op(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "kaas")

    await _sync(hass)
    writes_after_first = len(fake.write_calls)
    response = await _sync(hass)

    assert len(fake.write_calls) == writes_after_first
    assert response == {"source_entity_id": TARGET, "added": [], "checked": [], "unchanged": 1}


async def test_long_list_is_written_in_batches(hass: HomeAssistant):
    """The whole push travels in a handful of requests, not one per item."""
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    count = LIST_WRITE_BATCH_SIZE * 2 + 3
    for index in range(count):
        await _add_to_target(hass, f"item {index}")

    await _sync(hass)

    assert len(fake.items) == count
    assert len(fake.write_calls) == 3
    assert [len(batch) for batch in fake.write_calls] == [LIST_WRITE_BATCH_SIZE, LIST_WRITE_BATCH_SIZE, 3]


async def test_service_accepts_another_source_list(hass: HomeAssistant, other_todo_list: str):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "wijn", entity_id=other_todo_list)
    await _add_to_target(hass, "kaas")

    response = await _sync(hass, entity_id=other_todo_list)

    assert set(fake.items) == {"wijn"}  # only the list that was asked for
    assert response["source_entity_id"] == other_todo_list


async def test_unknown_source_list_raises(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())

    with pytest.raises(HomeAssistantError):
        await _sync(hass, entity_id="todo.does_not_exist")


def test_plan_handles_odd_source_items():
    """The diff itself, on input the todo services will not easily produce."""
    ah_items = [
        AhListItem(description="melk", checked=True),
        AhListItem(description="luiers", checked=False),
    ]
    source = [
        {"summary": "  ", "status": "needs_action"},  # blank: ignored
        {"summary": "melk", "status": "completed"},  # already checked on AH
        {"summary": "vla", "status": "completed"},  # completed, unknown to AH
        {"summary": "luiers", "status": "completed"},  # -> check off
        {"summary": "Luiers", "status": "needs_action"},  # ...but re-added, so: leave
        {"summary": "kaas", "status": "needs_action"},  # -> add
    ]

    result, writes = AhListSyncManager._plan(TARGET, source, ah_items)

    assert result.added == ["kaas"]
    assert result.checked == []
    assert result.unchanged == 1  # "Luiers", matched case-insensitively
    assert writes == [AhListItem(description="kaas", checked=False)]


async def test_button_runs_the_same_push(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())
    await _add_to_target(hass, "kaas")

    await hass.services.async_call("button", "press", {"entity_id": BUTTON}, blocking=True)
    await hass.async_block_till_done()

    assert set(fake.items) == {"kaas"}


async def test_no_button_without_a_sync_target(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client(), target=None)

    assert hass.states.get(BUTTON) is None


async def test_service_without_a_configured_target_raises(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client(), target=None)

    with pytest.raises(ServiceValidationError):
        await _sync(hass)


async def test_two_synced_accounts_need_disambiguation(hass: HomeAssistant):
    fake = FakeAhList([])
    first = await _setup_ah(hass, fake.client())
    second_fake = FakeAhList([])
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="7654321",
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: "7654321"},
        options={CONF_LIST_ENABLED: True, CONF_SYNC_TARGET_ENTITY: TARGET},
    )
    second.add_to_hass(hass)
    with patch("custom_components.albert_heijn.AhApiClient", return_value=second_fake.client()):
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()
    await _add_to_target(hass, "kaas")

    with pytest.raises(ServiceValidationError):
        await _sync(hass)

    # Naming one of them works, and only that account is written to.
    await _sync(hass, config_entry_id=first.entry_id)
    assert set(fake.items) == {"kaas"}
    assert second_fake.items == {}


async def test_unknown_config_entry_raises(hass: HomeAssistant):
    fake = FakeAhList([])
    await _setup_ah(hass, fake.client())

    with pytest.raises(ServiceValidationError):
        await _sync(hass, config_entry_id="does-not-exist")


async def test_ah_read_failure_surfaces(hass: HomeAssistant):
    fake = FakeAhList([])
    client = fake.client()
    await _setup_ah(hass, client)
    await _add_to_target(hass, "kaas")
    client.async_get_list_items.side_effect = AhApiError("boom")

    with pytest.raises(HomeAssistantError):
        await _sync(hass)

    assert fake.items == {}  # nothing written on a half-read state


async def test_ah_write_failure_surfaces(hass: HomeAssistant):
    fake = FakeAhList([])
    client = fake.client()
    await _setup_ah(hass, client)
    await _add_to_target(hass, "kaas")
    client.async_write_list_items.side_effect = AhApiError("boom")

    with pytest.raises(HomeAssistantError):
        await _sync(hass)


async def test_unload_removes_the_button_and_the_sync(hass: HomeAssistant):
    fake = FakeAhList([])
    entry = await _setup_ah(hass, fake.client())

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await _add_to_target(hass, "na-unload")
    assert hass.states.get(BUTTON).state == "unavailable"
    with pytest.raises(ServiceValidationError):
        await _sync(hass)
    assert fake.items == {}
