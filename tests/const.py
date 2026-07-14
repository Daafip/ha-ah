"""Shared, anonymised test constants."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

from custom_components.albert_heijn.api import (
    AhListItem,
    BasketInfo,
    DeliveryInfo,
    KoopzegelsData,
    ReceiptSummary,
    SavingGoalInfo,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


TOKEN_RESPONSE = load_fixture("token.json")
KOOPZEGELS_RESPONSE = load_fixture("koopzegels.json")
RECEIPTS_RESPONSE = load_fixture("receipts.json")
DELIVERIES_RESPONSE = load_fixture("deliveries.json")
LIST_ITEMS_RESPONSE = load_fixture("list_items.json")

REFRESH_TOKEN = TOKEN_RESPONSE["refresh_token"]
MEMBER_ID = "1234567"
MEMBER_RESPONSE = {"data": {"member": {"id": 1234567}}}

# Tests that assert month-based numbers freeze time to this moment,
# matching the July/June receipts in receipts.json.
FROZEN_NOW = "2026-07-03T12:00:00+00:00"

KOOPZEGELS_DATA = KoopzegelsData(
    payout=510.7,
    invested=504.7,
    interest=6.0,
    stamp_count=1030,
    booklet_stamps=50,
    full_booklets=2,
    full_booklet_target=490,
)

RECEIPTS = [
    ReceiptSummary(transaction_id="9001", moment="2026-07-01T14:30:00", total=45.67),
    ReceiptSummary(transaction_id="9000", moment="2026-06-20T10:00:00", total=12.34),
]

DELIVERIES = [
    DeliveryInfo(order_id=555, date="2099-01-05", start_time="18:00", end_time="20:00", status="PLANNED"),
    DeliveryInfo(order_id=444, date="2026-01-02", start_time="08:00", end_time="10:00", status="DELIVERED"),
]


MILES = 1234
PREMIUM_SAVINGS = 56.78
SETTLEMENTS_TOTAL = 3.21
SAVING_GOAL = SavingGoalInfo(name="Vakantie", amount=52.0)
BASKET = BasketInfo(quantity=12, total=34.56)

LIST_ITEMS = [
    AhListItem(description="luiers", checked=False),
    AhListItem(description="melk", checked=True, product_id=12345, quantity=2),
]


def make_client() -> AsyncMock:
    """An AhApiClient mock with all data methods stubbed."""
    client = AsyncMock()
    client.async_get_koopzegels.return_value = KOOPZEGELS_DATA
    client.async_get_receipts.return_value = RECEIPTS
    client.async_get_deliveries.return_value = DELIVERIES
    client.async_get_member_id.return_value = MEMBER_ID
    client.async_get_miles.return_value = MILES
    client.async_get_premium_savings.return_value = PREMIUM_SAVINGS
    client.async_get_settlements_total.return_value = SETTLEMENTS_TOTAL
    client.async_get_saving_goal.return_value = SAVING_GOAL
    client.async_get_basket.return_value = BASKET
    client.async_get_list_items.return_value = LIST_ITEMS
    client.async_add_free_text_item.return_value = None
    client.async_set_item_checked.return_value = None
    client.async_delete_list_items.return_value = None
    return client
