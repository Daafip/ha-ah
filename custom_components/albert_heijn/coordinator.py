"""Data update coordinator for the Albert Heijn integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AhApiClient, AhApiError, AhAuthError, KoopzegelsData
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

type AhConfigEntry = ConfigEntry[AhCoordinator]


def update_interval_from_options(entry: AhConfigEntry) -> timedelta:
    """The configured poll interval, falling back to the 6 h default."""
    return timedelta(hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS))


class AhCoordinator(DataUpdateCoordinator[KoopzegelsData]):
    """Polls the AH API and normalises the koopzegels balance."""

    config_entry: AhConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AhConfigEntry, client: AhApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval_from_options(entry),
        )
        self.client = client

    async def _async_update_data(self) -> KoopzegelsData:
        try:
            return await self.client.async_get_koopzegels()
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except AhApiError as err:
            raise UpdateFailed(f"Error fetching koopzegels: {err}") from err
