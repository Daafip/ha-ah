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
    AhListItem,
    parse_deliveries,
    parse_koopzegels,
    parse_list_items,
    parse_receipts,
)
from custom_components.albert_heijn.const import (
    GRAPHQL_URL,
    SHOPPINGLIST_ITEMS_URL,
    TOKEN_REFRESH_URL,
    TOKEN_URL,
)

from .const import (
    DELIVERIES_RESPONSE,
    KOOPZEGELS_RESPONSE,
    LIST_ITEMS_RESPONSE,
    MEMBER_RESPONSE,
    RECEIPTS_RESPONSE,
    REFRESH_TOKEN,
    TOKEN_RESPONSE,
)


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


async def test_get_receipts(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload=RECEIPTS_RESPONSE)
        receipts = await client.async_get_receipts()
    assert len(receipts) == 2
    assert receipts[0].transaction_id == "9001"
    assert receipts[0].moment == "2026-07-01T14:30:00"
    assert receipts[0].total == 45.67
    # The pagination variables must be sent along.
    request = mock.requests[("POST", URL(GRAPHQL_URL))][0]
    assert request.kwargs["json"]["variables"] == {"offset": 0, "limit": 100}


async def test_get_deliveries(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload=DELIVERIES_RESPONSE)
        deliveries = await client.async_get_deliveries()
    assert len(deliveries) == 2
    assert deliveries[0].order_id == 555
    assert deliveries[0].date == "2099-01-05"
    assert deliveries[0].start_time == "18:00"
    assert deliveries[0].status == "PLANNED"


def test_parse_receipts_tolerates_empty_page():
    assert parse_receipts({"posReceiptsPage": None}) == []
    assert parse_receipts({"posReceiptsPage": {"posReceipts": None}}) == []


def test_parse_receipts_bad_shape_raises():
    with pytest.raises(AhApiError):
        parse_receipts({"posReceiptsPage": {"posReceipts": [{"dateTime": "2026-07-01T10:00:00"}]}})


def test_parse_deliveries_skips_slotless_and_tolerates_empty():
    assert parse_deliveries({"orderFulfillments": {"result": [{"orderId": 1, "delivery": {"slot": None}}]}}) == []
    assert parse_deliveries({"orderFulfillments": None}) == []


async def test_get_miles(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload={"data": {"milesBalance": {"balance": 1234, "errorState": None}}})
        assert await client.async_get_miles() == 1234


async def test_get_miles_error_state_raises(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload={"data": {"milesBalance": {"balance": None, "errorState": "REAUTH"}}})
        with pytest.raises(AhApiError):
            await client.async_get_miles()


async def test_get_saving_goal_none_when_unset(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload={"data": {"purchaseStampSavingGoal": None}})
        assert await client.async_get_saving_goal() is None


async def test_get_saving_goal(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(
            GRAPHQL_URL,
            payload={"data": {"purchaseStampSavingGoal": {"name": "Vakantie", "amount": {"amount": 52.0}}}},
        )
        goal = await client.async_get_saving_goal()
    assert goal.name == "Vakantie"
    assert goal.amount == 52.0


async def test_get_basket(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(
            GRAPHQL_URL,
            payload={"data": {"basket": {"summary": {"quantity": 12, "price": {"totalPrice": {"amount": 34.56}}}}}},
        )
        basket = await client.async_get_basket()
    assert basket.quantity == 12
    assert basket.total == 34.56


async def test_get_basket_empty(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(GRAPHQL_URL, payload={"data": {"basket": {"summary": None}}})
        basket = await client.async_get_basket()
    assert basket.quantity == 0
    assert basket.total == 0.0


async def test_get_premium_savings_and_settlements(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.post(
            GRAPHQL_URL, payload={"data": {"subscriptionPremiumSavingsV2": {"totalSavedAmount": {"amount": 56.78}}}}
        )
        mock.post(GRAPHQL_URL, payload={"data": {"settlementsTotal": {"totalAmount": {"amount": 3.21}}}})
        assert await client.async_get_premium_savings() == 56.78
        assert await client.async_get_settlements_total() == 3.21


async def test_get_list_items(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.get(SHOPPINGLIST_ITEMS_URL, payload=LIST_ITEMS_RESPONSE)
        items = await client.async_get_list_items()
        request = mock.requests[("GET", URL(SHOPPINGLIST_ITEMS_URL))][0]
        headers = request.kwargs["headers"]
    assert len(items) == 2
    assert items[0].description == "luiers"
    assert items[0].checked is False
    assert items[0].product_id is None
    assert items[1].checked is True
    assert items[1].product_id == 12345
    assert items[1].quantity == 2
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["X-Application"] == "AHWEBSHOP"


async def test_rest_401_raises_auth_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.get(SHOPPINGLIST_ITEMS_URL, status=401)
        with pytest.raises(AhAuthError):
            await client.async_get_list_items()


async def test_rest_500_raises_api_error(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.get(SHOPPINGLIST_ITEMS_URL, status=500)
        with pytest.raises(AhApiError):
            await client.async_get_list_items()


def test_parse_list_items_edge_cases():
    assert parse_list_items(None) == []
    assert parse_list_items({}) == []
    assert parse_list_items({"items": None}) == []
    # Missing description degrades to an empty string; free text has no ids.
    items = parse_list_items({"items": [{"listItemId": 0, "quantity": None}]})
    assert items[0].description == ""
    assert items[0].checked is False
    assert items[0].product_id is None
    assert items[0].quantity == 1


def test_parse_list_items_bad_shape_raises():
    with pytest.raises(AhApiError):
        parse_list_items({"items": [{"quantity": "veel"}]})
    with pytest.raises(AhApiError):
        parse_list_items({"items": ["geen dict"]})


async def test_add_free_text_item_payload(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.patch(SHOPPINGLIST_ITEMS_URL, status=200, payload={})
        await client.async_add_free_text_item("luiers")
        request = mock.requests[("PATCH", URL(SHOPPINGLIST_ITEMS_URL))][0]
    (item,) = request.kwargs["json"]["items"]
    # No productId key at all: that is what makes it a free-text note. The
    # write shape differs from the read shape (originCode PRD, strikeThrough).
    assert "productId" not in item
    assert item == {
        "description": "luiers",
        "quantity": 1,
        "type": "SHOPPABLE",
        "originCode": "PRD",
        "strikeThrough": False,
    }


async def test_set_item_checked_payload(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    product = AhListItem(description="melk", checked=False, product_id=12345, quantity=2)
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.patch(SHOPPINGLIST_ITEMS_URL, status=204)  # empty body must be fine
        await client.async_set_item_checked(product, True)
        request = mock.requests[("PATCH", URL(SHOPPINGLIST_ITEMS_URL))][0]
    (item,) = request.kwargs["json"]["items"]
    # Quantity and productId ride along so the merge cannot clobber them.
    assert item == {
        "description": "melk",
        "quantity": 2,
        "type": "SHOPPABLE",
        "originCode": "PRD",
        "strikeThrough": True,
        "productId": 12345,
    }


async def test_delete_list_items_batches_one_patch(session):
    client = AhApiClient(session, refresh_token=REFRESH_TOKEN)
    items = [
        AhListItem(description="luiers", checked=False),
        AhListItem(description="melk", checked=True, product_id=12345, quantity=2),
    ]
    with aioresponses() as mock:
        mock.post(TOKEN_REFRESH_URL, payload=TOKEN_RESPONSE)
        mock.patch(SHOPPINGLIST_ITEMS_URL, status=200, payload={})
        await client.async_delete_list_items(items)
        requests = mock.requests[("PATCH", URL(SHOPPINGLIST_ITEMS_URL))]
    assert len(requests) == 1  # one batched call
    entries = requests[0].kwargs["json"]["items"]
    # Deletion is a merge with quantity 0.
    assert [entry["quantity"] for entry in entries] == [0, 0]
    assert [entry["description"] for entry in entries] == ["luiers", "melk"]
    assert entries[1]["productId"] == 12345
