"""Tests for the coordinator."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import DOMAIN
from custom_components.albert_heijn.coordinator import AhCoordinator, AhListCoordinator

from .const import (
    BASKET,
    FROZEN_NOW,
    KOOPZEGELS_DATA,
    LIST_ITEMS,
    MILES,
    PREMIUM_SAVINGS,
    SAVING_GOAL,
    SETTLEMENTS_TOTAL,
    make_client,
)


def _make_coordinator(hass: HomeAssistant, client) -> AhCoordinator:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AhCoordinator(hass, entry, client)


def _make_list_coordinator(hass: HomeAssistant, client) -> AhListCoordinator:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AhListCoordinator(hass, entry, client)


async def test_update_success(hass: HomeAssistant, freezer):
    freezer.move_to(FROZEN_NOW)
    coordinator = _make_coordinator(hass, make_client())
    data = await coordinator._async_update_data()

    assert data.koopzegels == KOOPZEGELS_DATA
    assert data.last_receipt.transaction_id == "9001"
    assert data.month_spent == 45.67  # only the July receipt counts
    assert data.month_receipt_count == 1
    assert data.next_delivery.order_id == 555  # past delivery is skipped
    assert len(data.deliveries) == 2
    assert data.miles == MILES
    assert data.premium_savings == PREMIUM_SAVINGS
    assert data.settlements_total == SETTLEMENTS_TOTAL
    assert data.saving_goal == SAVING_GOAL
    assert data.basket == BASKET


async def test_optional_endpoints_degrade_gracefully(hass: HomeAssistant):
    client = make_client()
    for method in (
        client.async_get_receipts,
        client.async_get_deliveries,
        client.async_get_miles,
        client.async_get_premium_savings,
        client.async_get_settlements_total,
        client.async_get_saving_goal,
        client.async_get_basket,
    ):
        method.side_effect = AhApiError("broke")
    coordinator = _make_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.koopzegels == KOOPZEGELS_DATA
    assert data.last_receipt is None
    assert data.month_spent is None
    assert data.month_receipt_count is None
    assert data.next_delivery is None
    assert data.deliveries == []
    assert data.miles is None
    assert data.premium_savings is None
    assert data.settlements_total is None
    assert data.saving_goal is None
    assert data.basket is None


async def test_unexpected_error_in_optional_fetch_raises(hass: HomeAssistant):
    client = make_client()
    client.async_get_miles.side_effect = RuntimeError("bug, not an API failure")
    coordinator = _make_coordinator(hass, client)
    with pytest.raises(RuntimeError):
        await coordinator._async_update_data()


async def test_auth_error_triggers_reauth(hass: HomeAssistant):
    client = make_client()
    client.async_get_koopzegels.side_effect = AhAuthError("expired")
    coordinator = _make_coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_marks_update_failed(hass: HomeAssistant):
    client = make_client()
    client.async_get_koopzegels.side_effect = AhApiError("boom")
    coordinator = _make_coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_list_update_success(hass: HomeAssistant):
    client = make_client()
    coordinator = _make_list_coordinator(hass, client)
    items = await coordinator._async_update_data()

    assert items == LIST_ITEMS
    client.async_get_list_items.assert_awaited_once_with()


async def test_list_previous_items_set_after_second_refresh(hass: HomeAssistant):
    coordinator = _make_list_coordinator(hass, make_client())

    await coordinator.async_refresh()
    assert coordinator.previous_items is None  # first load: no diff base yet
    assert coordinator.data == LIST_ITEMS

    await coordinator.async_refresh()
    assert coordinator.previous_items == LIST_ITEMS


async def test_list_previous_items_reset_after_failed_refresh(hass: HomeAssistant):
    client = make_client()
    coordinator = _make_list_coordinator(hass, client)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert coordinator.previous_items == LIST_ITEMS

    client.async_get_list_items.side_effect = AhApiError("down")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False

    # After a gap the diff base is stale; treat the recovery like a first load.
    client.async_get_list_items.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.previous_items is None


async def test_list_auth_error_triggers_reauth(hass: HomeAssistant):
    client = make_client()
    client.async_get_list_items.side_effect = AhAuthError("expired")
    coordinator = _make_list_coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_list_api_error_marks_update_failed(hass: HomeAssistant):
    client = make_client()
    client.async_get_list_items.side_effect = AhApiError("boom")
    coordinator = _make_list_coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
