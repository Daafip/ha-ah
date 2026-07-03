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
    CLIENT_ID,
    DEFAULT_FULL_BOOKLET_TARGET,
    DEFAULT_HEADERS,
    GRAPHQL_URL,
    KOOPZEGELS_OPERATION,
    KOOPZEGELS_QUERY,
    MEMBER_ID_OPERATION,
    MEMBER_ID_QUERY,
    REQUEST_TIMEOUT,
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

    async def _async_graphql(self, operation: str, query: str) -> dict[str, Any]:
        await self._async_ensure_token()
        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {self._access_token}",
            "x-apollo-operation-name": operation,
            "x-apollo-operation-type": "query",
        }
        payload = {"operationName": operation, "query": query, "variables": {}}
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

    async def _async_json(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        if response.status >= 400:
            raise AhApiError(f"HTTP {response.status} from {response.url}")
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                return await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise AhApiError(f"Invalid response from {response.url}: {err!r}") from err
