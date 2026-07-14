"""Diagnostics for the Albert Heijn integration (tokens and ids redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_MEMBER_ID, CONF_REFRESH_TOKEN
from .coordinator import AhConfigEntry

# List item descriptions are deliberately not redacted: they are the thing
# being debugged when the shopping list sync misbehaves.
TO_REDACT = {CONF_REFRESH_TOKEN, CONF_MEMBER_ID, "transaction_id", "order_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AhConfigEntry) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    list_coordinator = coordinator.list_coordinator
    diagnostics: dict[str, Any] = {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "update_interval": str(coordinator.update_interval),
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT) if coordinator.data else None,
    }
    if list_coordinator is not None:
        diagnostics["list_update_interval"] = str(list_coordinator.update_interval)
        diagnostics["list_last_update_success"] = list_coordinator.last_update_success
        diagnostics["list_items"] = (
            [asdict(item) for item in list_coordinator.data] if list_coordinator.data is not None else None
        )
    return diagnostics
