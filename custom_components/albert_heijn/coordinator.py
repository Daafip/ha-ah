"""Data update coordinator for the Albert Heijn integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .sync import AhListSyncManager

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
    TrackAndTrace,
)
from .const import (
    CONF_LIST_SCAN_INTERVAL,
    CONF_SYNC_TARGET_ENTITY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LIST_SCAN_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DELIVERY_DAY_INTERVAL,
    DELIVERY_DONE_STATUSES,
    DELIVERY_LIVE_GRACE,
    DELIVERY_LIVE_INTERVAL,
    DELIVERY_LIVE_LEAD,
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


@dataclass(frozen=True)
class AhDeliveryData:
    """What the delivery fast lane knows about the current or next delivery."""

    delivery: DeliveryInfo | None = None
    # Only fetched on the delivery day itself; None before it.
    tracking: TrackAndTrace | None = None
    delivery_day: bool = False  # polling at the delivery-day interval (or faster)
    live: bool = False  # polling at the fast interval right now

    @property
    def eta_start(self) -> datetime | None:
        """Start of the narrowed arrival window (the single estimate when there is no window)."""
        if self.delivery is None:
            return None
        if self.tracking is not None and (start := api_datetime(self.tracking.eta_start, self.delivery.date)):
            return start
        return api_datetime(self.delivery.estimated, self.delivery.date)

    @property
    def eta_end(self) -> datetime | None:
        """End of the narrowed arrival window."""
        if self.delivery is None or self.tracking is None:
            return None
        return api_datetime(self.tracking.eta_end, self.delivery.date)

    @property
    def message(self) -> str | None:
        """The delivery message as the app words it."""
        if self.tracking is not None and self.tracking.message:
            return self.tracking.message
        return self.delivery.message if self.delivery else None


def update_interval_from_options(entry: AhConfigEntry) -> timedelta:
    """The configured poll interval, falling back to the 6 h default."""
    return timedelta(hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS))


def list_interval_from_options(entry: AhConfigEntry) -> timedelta | None:
    """The configured shopping list poll interval, falling back to the 120 s default.

    None (no background polling at all) when the list is synced into an
    existing todo entity: that push is one-way and only runs on an explicit
    user action, so there is nothing for a poll to pick up.
    """
    if entry.options.get(CONF_SYNC_TARGET_ENTITY):
        return None
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


def api_datetime(value: str | None, date: str | None = None) -> datetime | None:
    """A timestamp from the API as an aware datetime, None when unreadable.

    Accepts an ISO datetime (a naive one is taken as HA-local time) and a bare
    ``HH:MM`` time, which is combined with ``date`` (the slot date).
    """
    if not value:
        return None
    if (parsed := dt_util.parse_datetime(value)) is None:
        return _slot_datetime(date, value) if date else None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


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
        # Live delivery tracking; polls on its own, adaptive interval.
        self.delivery_coordinator = AhDeliveryCoordinator(hass, entry, client)
        # Set at setup when the shopping list option is enabled; None otherwise.
        self.list_coordinator: AhListCoordinator | None = None
        # Set when an existing HA todo entity was picked to sync with instead
        # of the dedicated AH entity; both None when that option is unused.
        self.sync_target_entity_id: str | None = None
        self.list_sync_manager: AhListSyncManager | None = None

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


class AhDeliveryCoordinator(DataUpdateCoordinator[AhDeliveryData]):
    """Follows the current or next delivery, more often the closer it gets.

    Idles at the regular update interval until the delivery day starts. On the
    day itself it polls every DELIVERY_DAY_INTERVAL, with track & trace,
    because AH publishes the arrival window during the day and keeps shifting
    it. From DELIVERY_LIVE_LEAD before the slot it polls every
    DELIVERY_LIVE_INTERVAL, until the order is delivered or the slot is well
    and truly over.
    """

    config_entry: AhConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AhConfigEntry, client: AhApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_delivery",
            update_interval=update_interval_from_options(entry),
        )
        self.client = client

    async def _async_update_data(self) -> AhDeliveryData:
        try:
            deliveries = await self.client.async_get_deliveries(detailed=True)
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except AhApiError as err:
            raise UpdateFailed(f"Error fetching delivery details: {err}") from err

        now = dt_util.now()
        delivery = self._current_delivery(deliveries, now)
        done = delivery is None or (delivery.status or "").upper() in DELIVERY_DONE_STATUSES
        live = not done and _reached(_live_start(delivery), now)
        delivery_day = live or (not done and _reached(_day_start(delivery), now))

        tracking = None
        if delivery_day and delivery.order_id is not None:
            try:
                tracking = await self.client.async_get_track_and_trace(delivery.order_id)
            except AhAuthError as err:
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
            except AhApiError as err:
                # Best-effort: the message and estimate of the fulfillment remain.
                _LOGGER.debug("track and trace unavailable: %s", err)
            if tracking is not None and tracking.delivered_at:
                # Delivered: keep this last snapshot, stop hurrying.
                done, delivery_day, live = True, False, False

        self.update_interval = self._next_interval(delivery, done, delivery_day, live, now)
        return AhDeliveryData(delivery=delivery, tracking=tracking, delivery_day=delivery_day, live=live)

    @staticmethod
    def _current_delivery(deliveries: list[DeliveryInfo], now: datetime) -> DeliveryInfo | None:
        """The delivery under way, else the next one; None when all are over."""
        candidates = [
            (end, delivery)
            for delivery in deliveries
            if (end := slot_end(delivery)) is not None and end + DELIVERY_LIVE_GRACE > now
        ]
        return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    def _next_interval(
        self, delivery: DeliveryInfo | None, done: bool, delivery_day: bool, live: bool, now: datetime
    ) -> timedelta:
        """The interval for the current speed, shortened so that no speed-up is slept through."""
        if live:
            return DELIVERY_LIVE_INTERVAL
        idle = update_interval_from_options(self.config_entry)
        if delivery is None or done:
            return idle
        interval = DELIVERY_DAY_INTERVAL if delivery_day else idle
        for moment in (_day_start(delivery), _live_start(delivery)):
            if moment is not None and (until := moment - now) > timedelta(0):
                interval = min(interval, max(until, DELIVERY_LIVE_INTERVAL))
        return interval


def _day_start(delivery: DeliveryInfo) -> datetime | None:
    """Midnight at the start of the delivery day: the delivery-day speed starts here."""
    return _slot_datetime(delivery.date, "00:00")


def _live_start(delivery: DeliveryInfo) -> datetime | None:
    """DELIVERY_LIVE_LEAD before the slot starts: the live speed starts here."""
    start = slot_start(delivery)
    return start - DELIVERY_LIVE_LEAD if start is not None else None


def _reached(moment: datetime | None, now: datetime) -> bool:
    return moment is not None and now >= moment


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
