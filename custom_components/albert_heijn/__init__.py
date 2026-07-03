"""The Albert Heijn integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AhApiClient
from .const import CONF_REFRESH_TOKEN
from .coordinator import AhConfigEntry, AhCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


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

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AhConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
