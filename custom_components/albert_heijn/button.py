"""A button that pushes the configured todo list to the AH shopping list."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry
from .sync import AhListSyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the sync button, when a todo list to sync from is configured.

    Without a sync target there is nothing to push (the dedicated AH todo
    entity writes to the API directly), so no button is created.
    """
    sync_manager = entry.runtime_data.list_sync_manager
    if sync_manager is None:
        return
    member_id = entry.data.get(CONF_MEMBER_ID, entry.entry_id)
    async_add_entities([AhSyncShoppingListButton(sync_manager, member_id)])


class AhSyncShoppingListButton(ButtonEntity):
    """Runs the same push as the ``albert_heijn.sync_shopping_list`` service."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_shopping_list"

    def __init__(self, sync_manager: AhListSyncManager, member_id: str) -> None:
        self._sync_manager = sync_manager
        self._attr_unique_id = f"{member_id}_sync_shopping_list"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, member_id)},
            name="Albert Heijn",
            manufacturer="Albert Heijn",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Push the configured list; errors surface in the UI."""
        await self._sync_manager.async_push()
