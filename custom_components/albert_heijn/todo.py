"""Shopping list ("Mijn lijst") as a todo entity."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AhApiError, AhListItem
from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry, AhListCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the shopping list from a config entry, when the option is enabled.

    Skipped when an existing todo entity was picked to sync with instead
    (options flow "sync_target_entity"): that entity is driven by
    AhListSyncManager via services, not by an entity this integration owns.
    """
    list_coordinator = entry.runtime_data.list_coordinator
    if list_coordinator is None or entry.runtime_data.sync_target_entity_id:
        return
    member_id = entry.data.get(CONF_MEMBER_ID, entry.entry_id)
    async_add_entities([AhShoppingListTodoEntity(list_coordinator, member_id)])


class AhShoppingListTodoEntity(CoordinatorEntity[AhListCoordinator], TodoListEntity):
    """The AH shopping list; checked items map to completed todos."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_attribution = "Data from the unofficial Albert Heijn API"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, coordinator: AhListCoordinator, member_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{member_id}_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, member_id)},
            name="Albert Heijn",
            manufacturer="Albert Heijn",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _find_item(self, uid: str | None) -> AhListItem:
        """The coordinator's item for a uid (= description), or a bare stand-in.

        The API merges writes by description, so a stand-in with only the
        description still addresses the right item when the snapshot is stale.
        """
        for item in self.coordinator.data or []:
            if item.description == uid:
                return item
        return AhListItem(description=uid or "", checked=False)

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """The current list items, None before the first successful refresh."""
        if self.coordinator.data is None:
            return None
        return [
            TodoItem(
                # The API keeps descriptions unique and merges writes by
                # description, so it doubles as the uid.
                uid=item.description,
                summary=item.description,
                status=TodoItemStatus.COMPLETED if item.checked else TodoItemStatus.NEEDS_ACTION,
            )
            for item in self.coordinator.data
            if item.description
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a free-text item to the AH list."""
        try:
            await self.coordinator.client.async_add_free_text_item(item.summary or "")
        except AhApiError as err:
            raise HomeAssistantError(f"Adding item to the AH shopping list failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Check or uncheck an item; renaming is not supported by the AH API."""
        if item.summary is not None and item.summary != item.uid:
            raise HomeAssistantError("Renaming Albert Heijn list items is not supported")
        try:
            await self.coordinator.client.async_set_item_checked(
                self._find_item(item.uid), item.status == TodoItemStatus.COMPLETED
            )
        except AhApiError as err:
            raise HomeAssistantError(f"Updating the AH shopping list item failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the AH list (one call, quantity-0 merge)."""
        try:
            await self.coordinator.client.async_delete_list_items([self._find_item(uid) for uid in uids])
        except AhApiError as err:
            raise HomeAssistantError(f"Deleting AH shopping list items failed: {err}") from err
        await self.coordinator.async_request_refresh()
