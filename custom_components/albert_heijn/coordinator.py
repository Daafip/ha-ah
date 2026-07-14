"""Data update coordinator for the Albert Heijn integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AhApiClient,
    AhApiError,
    AhAuthError,
    AhListItem,
    BasketInfo,
    DeliveryInfo,
    KoopzegelsData,
    ReceiptSummary,
    SavingGoalInfo,
)
from .const import (
    CONF_LIST_SCAN_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LIST_SCAN_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type AhConfigEntry = ConfigEntry[AhCoordinator]


@dataclass(frozen=True)
class AhData:
    """Everything one poll cycle collects.

    ``koopzegels`` is required; the rest is best-effort (None/empty when the
    endpoint fails or does not apply to the account).
    """

    koopzegels: KoopzegelsData
    last_receipt: ReceiptSummary | None = None
    month_spent: float | None = None
    month_receipt_count: int | None = None
    deliveries: list[DeliveryInfo] = field(default_factory=list)
    next_delivery: DeliveryInfo | None = None
    miles: int | None = None
    premium_savings: float | None = None
    settlements_total: float | None = None
    saving_goal: SavingGoalInfo | None = None
    basket: BasketInfo | None = None


def update_interval_from_options(entry: AhConfigEntry) -> timedelta:
    """The configured poll interval, falling back to the 6 h default."""
    return timedelta(hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS))


def list_interval_from_options(entry: AhConfigEntry) -> timedelta:
    """The configured shopping list poll interval, falling back to the 120 s default."""
    return timedelta(seconds=entry.options.get(CONF_LIST_SCAN_INTERVAL, DEFAULT_LIST_SCAN_INTERVAL))


def slot_start(delivery: DeliveryInfo) -> datetime | None:
    """Slot start as a timezone-aware datetime in HA's timezone."""
    return _slot_datetime(delivery.date, delivery.start_time or "00:00")


def slot_end(delivery: DeliveryInfo) -> datetime | None:
    """Slot end; falls back to two hours after the start."""
    if (end := _slot_datetime(delivery.date, delivery.end_time)) is not None:
        return end
    if (start := slot_start(delivery)) is not None:
        return start + timedelta(hours=2)
    return None


def _slot_datetime(date: str, time: str | None) -> datetime | None:
    if not date or not time:
        return None
    try:
        naive = datetime.fromisoformat(f"{date}T{time}")
    except ValueError:
        return None
    return naive.replace(tzinfo=dt_util.get_default_time_zone())


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
        # Set at setup when the shopping list option is enabled; None otherwise.
        self.list_coordinator: AhListCoordinator | None = None

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

        receipts, deliveries, miles, premium, settlements, goal, basket = await asyncio.gather(
            self.client.async_get_receipts(),
            self.client.async_get_deliveries(),
            self.client.async_get_miles(),
            self.client.async_get_premium_savings(),
            self.client.async_get_settlements_total(),
            self.client.async_get_saving_goal(),
            self.client.async_get_basket(),
            return_exceptions=True,
        )
        receipts = self._best_effort("receipts", receipts)
        deliveries = self._best_effort("deliveries", deliveries)

        now = dt_util.now()

        last_receipt = month_spent = month_receipt_count = None
        if receipts is not None:
            if receipts:
                last_receipt = max(receipts, key=lambda receipt: receipt.moment)
            month_receipts = [r for r in receipts if r.moment.startswith(now.strftime("%Y-%m"))]
            month_spent = round(sum(r.total for r in month_receipts), 2)
            month_receipt_count = len(month_receipts)

        next_delivery = None
        if deliveries is None:
            deliveries = []
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
            deliveries=deliveries,
            next_delivery=next_delivery,
            miles=self._best_effort("miles", miles),
            premium_savings=self._best_effort("premium savings", premium),
            settlements_total=self._best_effort("settlements", settlements),
            saving_goal=self._best_effort("saving goal", goal),
            basket=self._best_effort("basket", basket),
        )

    @staticmethod
    def _best_effort(name: str, result):
        """Unwrap a gather result: AH API errors become None, real bugs raise."""
        if isinstance(result, AhApiError):
            _LOGGER.debug("%s unavailable: %s", name, result)
            return None
        if isinstance(result, BaseException):
            raise result
        return result


class AhListCoordinator(DataUpdateCoordinator[list[AhListItem]]):
    """Polls the AH shopping list ("Mijn lijst") on its own, faster interval."""

    config_entry: AhConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AhConfigEntry, client: AhApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_list",
            update_interval=list_interval_from_options(entry),
        )
        self.client = client
        # Snapshot of the refresh before the current one, so diff logic can
        # tell "deleted upstream" from "first load". None until the second
        # successful refresh.
        self.previous_items: list[AhListItem] | None = None

    async def _async_update_data(self) -> list[AhListItem]:
        self.previous_items = self.data if self.last_update_success else None
        try:
            return await self.client.async_get_list_items()
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except AhApiError as err:
            raise UpdateFailed(f"Error fetching shopping list: {err}") from err
