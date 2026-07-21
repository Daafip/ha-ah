"""The Albert Heijn integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AhApiClient
from .const import CONF_LIST_ENABLED, CONF_REFRESH_TOKEN, CONF_SYNC_TARGET_ENTITY
from .coordinator import (
    AhConfigEntry,
    AhCoordinator,
    AhListCoordinator,
    list_interval_from_options,
    update_interval_from_options,
)
from .sync import AhListSyncManager

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR, Platform.TODO]


async def _async_apply_options(hass: HomeAssistant, entry: AhConfigEntry) -> None:
    coordinator = entry.runtime_data

    # The list coordinator (and either the dedicated todo entity or the sync
    # manager for an existing one) only exist while the option is on and for
    # the currently chosen target, so flipping either needs a reload.
    # Comparing desired vs actual state keeps token-rotation entry updates
    # from looping a reload.
    list_enabled = entry.options.get(CONF_LIST_ENABLED, False)
    target_entity_id = entry.options.get(CONF_SYNC_TARGET_ENTITY) or None
    list_active = coordinator.list_coordinator is not None
    if list_enabled != list_active or (list_enabled and target_entity_id != coordinator.sync_target_entity_id):
        await hass.config_entries.async_reload(entry.entry_id)
        return

    # Interval changes are applied in place instead of reloading: the
    # token-rotation callback also updates the entry, and a reload-on-update
    # listener would loop on it.
    new_interval = update_interval_from_options(entry)
    if coordinator.update_interval != new_interval:
        coordinator.update_interval = new_interval
        await coordinator.async_request_refresh()

    if (list_coordinator := coordinator.list_coordinator) is not None:
        new_list_interval = list_interval_from_options(entry)
        if list_coordinator.update_interval != new_list_interval:
            list_coordinator.update_interval = new_list_interval
            await list_coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: AhConfigEntry) -> bool:
    """Set up Albert Heijn from a config entry."""

    @callback
    def _save_refresh_token(new_token: str) -> None:
        # AH rotates the refresh token; persist it so restarts keep working.
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_REFRESH_TOKEN: new_token})

    client = AhApiClient(
        async_get_clientsession(hass),
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        token_updated_callback=_save_refresh_token,
    )
    coordinator = AhCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    if entry.options.get(CONF_LIST_ENABLED, False):
        list_coordinator = AhListCoordinator(hass, entry, client)
        # A failed first fetch leaves the todo entity unavailable until a
        # later poll succeeds, instead of failing the whole entry: the list
        # feature is opt-in and secondary to the sensors.
        await list_coordinator.async_refresh()
        coordinator.list_coordinator = list_coordinator

        target_entity_id = entry.options.get(CONF_SYNC_TARGET_ENTITY) or None
        coordinator.sync_target_entity_id = target_entity_id
        if target_entity_id:
            # An existing entity (e.g. todo.shopping_list) was picked: sync
            # into it directly instead of creating a dedicated AH entity.
            sync_manager = AhListSyncManager(hass, client, list_coordinator, target_entity_id)
            sync_manager.async_setup()
            entry.async_on_unload(sync_manager.async_unload)
            coordinator.list_sync_manager = sync_manager

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_apply_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AhConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
