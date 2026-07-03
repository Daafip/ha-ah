"""Tests for the AH API client."""

import time
from unittest.mock import Mock

import aiohttp
import pytest
from aioresponses import aioresponses
from yarl import URL

from custom_components.albert_heijn.api import (
    AhApiClient,
    AhApiError,
    AhAuthError,
    parse_koopzegels,
)
from custom_components.albert_heijn.const import GRAPHQL_URL, TOKEN_REFRESH_URL, TOKEN_URL

from .const import KOOPZEGELS_RESPONSE, MEMBER_RESPONSE, REFRESH_TOKEN, TOKEN_RESPONSE


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as sess:
        yield sess


async def test_exchange_code_parses_tokens(session):
    client = AhApiClient(session)
    with aioresponses() as mock:
        mock.post(TOKEN_URL, payload=TOKEN_RESPONSE)
        refresh = await client.async_exchange_code("CODE")
    assert refresh == REFRESH_TOKEN
    assert client.refresh_token == REFRESH_TOKEN


async def test_refresh_updates_token_and_notifies(session):
    callback = Mock()
    client = AhApiClient(session, refresh_token="old-token", token_updated_callback=callback)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        await client.async_refresh()
    assert client.refresh_token == REFRESH_TOKEN
    callback.assert_called_once_with(REFRESH_TOKEN)


async def test_refresh_without_token_raises(session):
    client = AhApiClient(session)
    with pytest.raises(AhAuthError):
        await client.async_refresh()


async def test_get_koopzegels(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload=KOOPZEGELS_RESPONSE)
        data = await client.async_get_koopzegels()
    assert data.payout == 510.7
    assert data.invested == 504.7
    assert data.interest == 6.0
    assert data.stamp_count == 1030
    assert data.booklet_stamps == 50
    assert data.full_booklets == 2
    assert data.full_booklet_target == 490
    assert data.stamps_until_next_booklet == 440


async def test_get_member_id(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload=MEMBER_RESPONSE)
        assert await client.async_get_member_id() == "1234567"


async def test_no_refresh_while_token_valid(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        # A single-use refresh mock: a second refresh attempt would find no
        # matching mock and fail the data call.
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload=KOOPZEGELS_RESPONSE, repeat=True)
        await client.async_get_koopzegels()
        await client.async_get_koopzegels()
        assert len(mock.requests[("POST", URL(TOKEN_REFRESH_URL))]) == 1


async def test_proactive_refresh_near_expiry(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE, repeat=True)
        mock.post(GRAPHQL_URL, payload=KOOPZEGELS_RESPONSE, repeat=True)
        await client.async_get_koopzegels()
        client._expires_at = time.monotonic() + 10  # within the 60 s margin
        await client.async_get_koopzegels()
        assert len(mock.requests[("POST", URL(TOKEN_REFRESH_URL))]) == 2


async def test_invalid_code_raises_auth_error(session):
    client = AhApiClient(session)
    with aioresponses() as mock:
        mock.post(TOKEN_URL, status=400)
        with pytest.raises(AhAuthError):
            await client.async_exchange_code("BAD")


async def test_graphql_401_raises_auth_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, status=401)
        with pytest.raises(AhAuthError):
            await client.async_get_koopzegels()


async def test_graphql_500_raises_api_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, status=500)
        with pytest.raises(AhApiError):
            await client.async_get_koopzegels()


async def test_graphql_errors_raise_api_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload={"errors": [{"message": "boom"}]})
        with pytest.raises(AhApiError):
            await client.async_get_koopzegels()


async def test_timeout_raises_api_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, exception=TimeoutError())
        with pytest.raises(AhApiError):
            await client.async_get_koopzegels()


async def test_client_error_raises_api_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, exception=aiohttp.ClientError())
        with pytest.raises(AhApiError):
            await client.async_get_koopzegels()


def test_parse_koopzegels_missing_fields():
    with pytest.raises(AhApiError):
        parse_koopzegels({"purchaseStampBalance": {}})


def test_parse_koopzegels_defaults_booklet_target():
    payload = KOOPZEGELS_RESPONSE["data"]["purchaseStampBalance"]
    stripped = {"purchaseStampBalance": {**payload, "constants": None}}
    assert parse_koopzegels(stripped).full_booklet_target == 490
