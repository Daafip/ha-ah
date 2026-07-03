"""Data update coordinator for the Albert Heijn integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AhApiClient, AhApiError, AhAuthError, DeliveryInfo, KoopzegelsData, ReceiptSummary
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

type AhConfigEntry = ConfigEntry[AhCoordinator]


@dataclass(frozen=True)
class AhData:
    """Everything one poll cycle collects.

    ``koopzegels`` is required; the rest is best-effort (None when the
    endpoint fails or does not apply to the account).
    """

    koopzegels: KoopzegelsData
    last_receipt: ReceiptSummary | None = None
    month_spent: float | None = None
    month_receipt_count: int | None = None
    next_delivery: DeliveryInfo | None = None


def update_interval_from_options(entry: AhConfigEntry) -> timedelta:
    """The configured poll interval, falling back to the 6 h default."""
    return timedelta(hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS))


class AhCoordinator(DataUpdateCoordinator[AhData]):
    """Polls the AH API and normalises the results."""

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

    async def _async_update_data(self) -> AhData:
        # Koopzegels is the primary sensor: its failures decide availability
        # and reauth. The other endpoints are unofficial-upon-unofficial, so
        # they degrade to None instead of failing the whole update.
        try:
            koopzegels = await self.client.async_get_koopzegels()
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except AhApiError as err:
            raise UpdateFailed(f"Error fetching koopzegels: {err}") from err

        now = dt_util.now()

        last_receipt = month_spent = month_receipt_count = None
        try:
            receipts = await self.client.async_get_receipts()
        except AhApiError as err:
            _LOGGER.debug("Receipts unavailable: %s", err)
        else:
            if receipts:
                last_receipt = max(receipts, key=lambda receipt: receipt.moment)
            month_receipts = [r for r in receipts if r.moment.startswith(now.strftime("%Y-%m"))]
            month_spent = round(sum(r.total for r in month_receipts), 2)
            month_receipt_count = len(month_receipts)

        next_delivery = None
        try:
            deliveries = await self.client.async_get_deliveries()
        except AhApiError as err:
            _LOGGER.debug("Deliveries unavailable: %s", err)
        else:
            today = now.date().isoformat()
            upcoming = [d for d in deliveries if d.date >= today]
            if upcoming:
                next_delivery = min(upcoming, key=lambda d: (d.date, d.start_time or ""))

        return AhData(
            koopzegels=koopzegels,
            last_receipt=last_receipt,
            month_spent=month_spent,
            month_receipt_count=month_receipt_count,
            next_delivery=next_delivery,
        )
