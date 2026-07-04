"""Async client for the (unofficial) Albert Heijn mobile API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    BASKET_OPERATION,
    BASKET_QUERY,
    CLIENT_ID,
    DEFAULT_FULL_BOOKLET_TARGET,
    DEFAULT_HEADERS,
    DELIVERIES_OPERATION,
    DELIVERIES_QUERY,
    GRAPHQL_URL,
    KOOPZEGELS_OPERATION,
    KOOPZEGELS_QUERY,
    MEMBER_ID_OPERATION,
    MEMBER_ID_QUERY,
    MILES_OPERATION,
    MILES_QUERY,
    PREMIUM_SAVINGS_OPERATION,
    PREMIUM_SAVINGS_QUERY,
    RECEIPTS_OPERATION,
    RECEIPTS_PAGE_LIMIT,
    RECEIPTS_QUERY,
    REQUEST_TIMEOUT,
    SAVING_GOAL_OPERATION,
    SAVING_GOAL_QUERY,
    SETTLEMENTS_OPERATION,
    SETTLEMENTS_QUERY,
    TOKEN_EXPIRY_MARGIN,
    TOKEN_REFRESH_URL,
    TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)


class AhApiError(Exception):
    """The AH API returned an unexpected response."""


class AhAuthError(AhApiError):
    """Authentication with the AH API failed."""


@dataclass(frozen=True)
class KoopzegelsData:
    """Normalised koopzegels balance."""

    payout: float
    invested: float
    interest: float
    stamp_count: int
    booklet_stamps: int
    full_booklets: int
    full_booklet_target: int = DEFAULT_FULL_BOOKLET_TARGET

    @property
    def stamps_until_next_booklet(self) -> int:
        """Stamps still needed to fill the current booklet."""
        return max(0, self.full_booklet_target - self.booklet_stamps)


@dataclass(frozen=True)
class ReceiptSummary:
    """One in-store receipt, as listed by the receipts query."""

    transaction_id: str
    moment: str  # ISO datetime string as returned by the API
    total: float


@dataclass(frozen=True)
class SavingGoalInfo:
    """The koopzegels saving goal, when one is set."""

    name: str | None
    amount: float


@dataclass(frozen=True)
class BasketInfo:
    """Summary of the current webshop basket."""

    quantity: int
    total: float


@dataclass(frozen=True)
class DeliveryInfo:
    """A (planned) delivery slot from an order fulfillment."""

    order_id: int | None
    date: str  # YYYY-MM-DD
    start_time: str | None  # HH:MM
    end_time: str | None
    status: str | None


def _money_value(value: Any) -> float:
    """Accept both a flat number and nested ``{"amount": {"amount": x}}`` shapes."""
    while isinstance(value, dict):
        value = value.get("amount")
    return float(value)


def parse_receipts(data: dict[str, Any]) -> list[ReceiptSummary]:
    """Map the posReceiptsPage GraphQL payload onto :class:`ReceiptSummary` items."""
    try:
        items = (data.get("posReceiptsPage") or {}).get("posReceipts") or []
        return [
            ReceiptSummary(
                transaction_id=str(item["id"]),
                moment=str(item["dateTime"]),
                total=_money_value(item["totalAmount"]),
            )
            for item in items
        ]
    except (KeyError, TypeError, ValueError) as err:
        raise AhApiError(f"Unexpected receipts response: {err!r}") from err


def parse_deliveries(data: dict[str, Any]) -> list[DeliveryInfo]:
    """Map the fulfillments GraphQL payload onto :class:`DeliveryInfo` items."""
    try:
        fulfillments = (data.get("orderFulfillments") or {}).get("result") or []
        deliveries = []
        for item in fulfillments:
            slot = ((item.get("delivery") or {}).get("slot")) or {}
            if not slot.get("date"):
                continue
            deliveries.append(
                DeliveryInfo(
                    order_id=item.get("orderId"),
                    date=str(slot["date"]),
                    start_time=slot.get("startTime"),
                    end_time=slot.get("endTime"),
                    status=(item.get("delivery") or {}).get("status"),
                )
            )
        return deliveries
    except (KeyError, TypeError, ValueError) as err:
        raise AhApiError(f"Unexpected fulfillments response: {err!r}") from err


def parse_koopzegels(data: dict[str, Any]) -> KoopzegelsData:
    """Map the GraphQL ``data`` payload onto :class:`KoopzegelsData`.

    Schema-dependent, together with the query constants in const.py.
    """
    try:
        balance = data["purchaseStampBalance"]
        points = balance["points"]
        money = balance["money"]
        target = ((balance.get("constants") or {}).get("fullBookletTarget") or {}).get(
            "points"
        ) or DEFAULT_FULL_BOOKLET_TARGET
        return KoopzegelsData(
            payout=float(money["payout"]["amount"]),
            invested=float(money["invested"]["amount"]),
            interest=float(money["interest"]["amount"]),
            stamp_count=int(points["totalPoints"]),
            booklet_stamps=int(points["currentBookletPoints"]),
            full_booklets=int(points["fullBooklets"]),
            full_booklet_target=int(target),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise AhApiError(f"Unexpected koopzegels response: {err!r}") from err


class AhApiClient:
    """Thin async wrapper over the AH token endpoints and GraphQL API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str | None = None,
        token_updated_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._token_updated_callback = token_updated_callback
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def refresh_token(self) -> str | None:
        """The current refresh token (persist this)."""
        return self._refresh_token

    async def async_exchange_code(self, code: str) -> str:
        """Exchange a one-time login code for tokens; returns the refresh token."""
        data = await self._async_token_request(TOKEN_URL, {"clientId": CLIENT_ID, "code": code})
        self._store_tokens(data)
        assert self._refresh_token is not None
        return self._refresh_token

    async def async_refresh(self) -> None:
        """Refresh the access token using the stored refresh token."""
        if not self._refresh_token:
            raise AhAuthError("No refresh token available")
        data = await self._async_token_request(
            TOKEN_REFRESH_URL, {"clientId": CLIENT_ID, "refreshToken": self._refresh_token}
        )
        self._store_tokens(data)

    async def async_get_member_id(self) -> str:
        """Return the AH member id of the authenticated account."""
        data = await self._async_graphql(MEMBER_ID_OPERATION, MEMBER_ID_QUERY)
        member_id = (data.get("member") or {}).get("id")
        if member_id is None:
            raise AhApiError("No member id in response")
        return str(member_id)

    async def async_get_koopzegels(self) -> KoopzegelsData:
        """Fetch the current koopzegels balance."""
        data = await self._async_graphql(KOOPZEGELS_OPERATION, KOOPZEGELS_QUERY)
        return parse_koopzegels(data)

    async def async_get_receipts(self) -> list[ReceiptSummary]:
        """Fetch the list of in-store receipts."""
        data = await self._async_graphql(
            RECEIPTS_OPERATION, RECEIPTS_QUERY, {"offset": 0, "limit": RECEIPTS_PAGE_LIMIT}
        )
        return parse_receipts(data)

    async def async_get_deliveries(self) -> list[DeliveryInfo]:
        """Fetch planned/known deliveries from order fulfillments."""
        data = await self._async_graphql(DELIVERIES_OPERATION, DELIVERIES_QUERY)
        return parse_deliveries(data)

    async def async_get_miles(self) -> int:
        """Fetch the Air Miles balance."""
        data = await self._async_graphql(MILES_OPERATION, MILES_QUERY)
        miles = data.get("milesBalance") or {}
        if miles.get("balance") is None:
            raise AhApiError(f"No miles balance in response (errorState={miles.get('errorState')})")
        return int(miles["balance"])

    async def async_get_premium_savings(self) -> float:
        """Fetch the total amount saved through the Premium subscription."""
        data = await self._async_graphql(PREMIUM_SAVINGS_OPERATION, PREMIUM_SAVINGS_QUERY)
        try:
            return _money_value(data["subscriptionPremiumSavingsV2"]["totalSavedAmount"])
        except (KeyError, TypeError, ValueError) as err:
            raise AhApiError(f"Unexpected premium savings response: {err!r}") from err

    async def async_get_settlements_total(self) -> float:
        """Fetch the total of open settlements (refunds owed)."""
        data = await self._async_graphql(SETTLEMENTS_OPERATION, SETTLEMENTS_QUERY)
        try:
            return _money_value(data["settlementsTotal"]["totalAmount"])
        except (KeyError, TypeError, ValueError) as err:
            raise AhApiError(f"Unexpected settlements response: {err!r}") from err

    async def async_get_saving_goal(self) -> SavingGoalInfo | None:
        """Fetch the koopzegels saving goal; None when no goal is set."""
        data = await self._async_graphql(SAVING_GOAL_OPERATION, SAVING_GOAL_QUERY)
        goal = data.get("purchaseStampSavingGoal")
        if not goal:
            return None
        try:
            return SavingGoalInfo(name=goal.get("name"), amount=_money_value(goal["amount"]))
        except (KeyError, TypeError, ValueError) as err:
            raise AhApiError(f"Unexpected saving goal response: {err!r}") from err

    async def async_get_basket(self) -> BasketInfo:
        """Fetch a summary of the current webshop basket."""
        data = await self._async_graphql(BASKET_OPERATION, BASKET_QUERY)
        try:
            summary = (data.get("basket") or {}).get("summary") or {}
            total = ((summary.get("price") or {}).get("totalPrice") or {}).get("amount")
            return BasketInfo(
                quantity=int(summary.get("quantity") or 0),
                total=float(total) if total is not None else 0.0,
            )
        except (TypeError, ValueError) as err:
            raise AhApiError(f"Unexpected basket response: {err!r}") from err

    def _store_tokens(self, data: dict[str, Any]) -> None:
        try:
            access_token = data["access_token"]
            expires_in = float(data["expires_in"])
        except (KeyError, TypeError, ValueError) as err:
            raise AhApiError(f"Unexpected token response: {err!r}") from err
        self._access_token = access_token
        self._expires_at = time.monotonic() + expires_in
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            if self._token_updated_callback is not None:
                self._token_updated_callback(new_refresh)

    async def _async_ensure_token(self) -> None:
        async with self._token_lock:
            if self._access_token is None or time.monotonic() >= self._expires_at - TOKEN_EXPIRY_MARGIN:
                _LOGGER.debug("Access token missing or near expiry, refreshing")
                await self.async_refresh()

    async def _async_token_request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._async_post(url, payload, DEFAULT_HEADERS)
        if response.status in (400, 401, 403):
            raise AhAuthError(f"Token request rejected with HTTP {response.status}")
        return await self._async_json(response)

    async def _async_graphql(
        self, operation: str, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self._async_ensure_token()
        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {self._access_token}",
            "x-apollo-operation-name": operation,
            "x-apollo-operation-type": "query",
        }
        payload = {"operationName": operation, "query": query, "variables": variables or {}}
        _LOGGER.debug("GraphQL request: %s", operation)
        response = await self._async_post(GRAPHQL_URL, payload, headers)
        if response.status in (401, 403):
            raise AhAuthError(f"GraphQL request {operation} rejected with HTTP {response.status}")
        body = await self._async_json(response)
        if body.get("errors"):
            raise AhApiError(f"GraphQL errors: {body['errors']}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise AhApiError("GraphQL response contains no data")
        return data

    async def _async_post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> aiohttp.ClientResponse:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await self._session.post(url, json=payload, headers=headers)
        except TimeoutError as err:
            raise AhApiError(f"Timeout talking to {url}") from err
        except aiohttp.ClientError as err:
            raise AhApiError(f"Error talking to {url}: {err!r}") from err

    async def _async_json(self, response: aiohttp.ClientResponse) -> Any:
        if response.status >= 400:
            raise AhApiError(f"HTTP {response.status} from {response.url}")
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise AhApiError(f"Invalid response from {response.url}: {err!r}") from err
