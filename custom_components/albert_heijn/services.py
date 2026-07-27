"""Integration services: the manual shopping list push."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_SYNC_SHOPPING_LIST
from .coordinator import AhConfigEntry
from .sync import AhListSyncManager

SYNC_SHOPPING_LIST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def _sync_manager(hass: HomeAssistant, entry_id: str | None) -> AhListSyncManager:
    """The sync manager to push with, or a ServiceValidationError explaining why not."""
    entries: list[AhConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and entry.runtime_data.list_sync_manager is not None
    ]
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_synced")
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_sync_target")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="multiple_entries")
    manager = entries[0].runtime_data.list_sync_manager
    assert manager is not None  # filtered on above
    return manager


async def _async_sync_shopping_list(call: ServiceCall) -> ServiceResponse:
    """Push a Home Assistant todo list onto the AH shopping list."""
    manager = _sync_manager(call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
    result = await manager.async_push(call.data.get(ATTR_ENTITY_ID))
    return result.as_response()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration-level services (once, at component setup)."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_SHOPPING_LIST,
        _async_sync_shopping_list,
        schema=SYNC_SHOPPING_LIST_SCHEMA,
        # Optional so the button (and any automation that does not care) can
        # call it without asking for the summary of what changed.
        supports_response=SupportsResponse.OPTIONAL,
    )
