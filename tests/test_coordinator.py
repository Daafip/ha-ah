"""Tests for the coordinator."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import DEFAULT_UPDATE_INTERVAL, DELIVERY_LIVE_INTERVAL, DOMAIN
from custom_components.albert_heijn.coordinator import (
    AhCoordinator,
    AhDeliveryCoordinator,
    AhListCoordinator,
    api_datetime,
)

from .const import (
    BASKET,
    DELIVERIES,
    ETA_MESSAGE,
    FROZEN_NOW,
    KOOPZEGELS_DATA,
    LIST_ITEMS,
    LIVE_DELIVERY,
    LIVE_NOW,
    MILES,
    PREMIUM_SAVINGS,
    SAVING_GOAL,
    SETTLEMENTS_TOTAL,
    TRACK_AND_TRACE,
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


# --- delivery fast lane ---
# LIVE_DELIVERY has slot 15:00-17:00 (Amsterdam) on 2026-11-15; the fast lane
# runs from an hour before the slot until an hour after it.


async def _make_delivery_coordinator(hass: HomeAssistant, client) -> AhDeliveryCoordinator:
    await hass.config.async_set_time_zone("Europe/Amsterdam")  # slot times are HA-local
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AhDeliveryCoordinator(hass, entry, client)


def _live_client(tracking=TRACK_AND_TRACE, delivery=LIVE_DELIVERY):
    client = make_client()
    client.async_get_deliveries.return_value = [DELIVERIES[0], delivery, DELIVERIES[1]]
    client.async_get_track_and_trace.return_value = tracking
    return client


def _amsterdam(time: str) -> str:
    return f"2026-11-15T{time}:00+01:00"


async def test_delivery_idle_when_next_delivery_is_far_away(hass: HomeAssistant, freezer):
    freezer.move_to(FROZEN_NOW)
    client = make_client()
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.delivery.order_id == 555  # the past delivery is skipped
    assert data.live is False
    assert data.tracking is None
    assert data.eta_start is None
    assert data.eta_end is None
    assert data.message is None
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    client.async_get_deliveries.assert_awaited_once_with(detailed=True)
    client.async_get_track_and_trace.assert_not_awaited()


async def test_delivery_live_fetches_track_and_trace(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    client = _live_client()
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.delivery == LIVE_DELIVERY
    assert data.live is True
    assert data.tracking == TRACK_AND_TRACE
    assert data.eta_start == datetime.fromisoformat(_amsterdam("15:15"))
    assert data.eta_end == datetime.fromisoformat(_amsterdam("15:45"))
    assert data.message == ETA_MESSAGE
    assert coordinator.update_interval == DELIVERY_LIVE_INTERVAL
    client.async_get_track_and_trace.assert_awaited_once_with(777)


@pytest.mark.parametrize(
    ("now", "expected_interval"),
    [
        ("11:30", timedelta(hours=2, minutes=30)),  # wake up at 14:00, an hour before the slot
        ("06:00", DEFAULT_UPDATE_INTERVAL),  # further away than one idle interval
        ("13:59", DELIVERY_LIVE_INTERVAL),  # never faster than the live rate
    ],
)
async def test_delivery_idle_interval_never_sleeps_through_the_live_window(
    hass: HomeAssistant, freezer, now, expected_interval
):
    freezer.move_to(_amsterdam(now))
    client = _live_client()
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.delivery == LIVE_DELIVERY
    assert data.live is False
    assert coordinator.update_interval == expected_interval
    client.async_get_track_and_trace.assert_not_awaited()


@pytest.mark.parametrize("now", ["14:00", "16:59", "17:30"])  # lead, slot, running late
async def test_delivery_live_window_bounds(hass: HomeAssistant, freezer, now):
    freezer.move_to(_amsterdam(now))
    coordinator = await _make_delivery_coordinator(hass, _live_client())
    data = await coordinator._async_update_data()

    assert data.delivery == LIVE_DELIVERY
    assert data.live is True


async def test_delivery_moves_on_once_the_slot_is_long_over(hass: HomeAssistant, freezer):
    freezer.move_to(_amsterdam("18:01"))
    client = _live_client()
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.delivery.order_id == 555
    assert data.live is False
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    client.async_get_track_and_trace.assert_not_awaited()


async def test_delivery_stops_hurrying_once_delivered(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    delivered = replace(TRACK_AND_TRACE, type="DELIVERED", delivered_at=_amsterdam("15:18"))
    coordinator = await _make_delivery_coordinator(hass, _live_client(tracking=delivered))
    data = await coordinator._async_update_data()

    assert data.live is False
    assert data.tracking == delivered  # the last snapshot stays visible
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL


async def test_delivery_with_final_status_is_not_tracked(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    client = _live_client(delivery=replace(LIVE_DELIVERY, status="DELIVERED"))
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.delivery.status == "DELIVERED"
    assert data.live is False
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    client.async_get_track_and_trace.assert_not_awaited()


async def test_delivery_falls_back_to_fulfillment_when_track_and_trace_fails(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    client = _live_client()
    client.async_get_track_and_trace.side_effect = AhApiError("Subgraph errors redacted")
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.live is True  # keep trying
    assert data.tracking is None
    assert data.eta_start == datetime.fromisoformat(_amsterdam("15:30"))  # the single estimate
    assert data.eta_end is None
    assert data.message == ETA_MESSAGE
    assert coordinator.update_interval == DELIVERY_LIVE_INTERVAL


async def test_delivery_without_any_eta(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    client = _live_client(tracking=None, delivery=replace(LIVE_DELIVERY, estimated=None, message=None))
    coordinator = await _make_delivery_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.live is True
    assert data.eta_start is None
    assert data.eta_end is None
    assert data.message is None


async def test_delivery_auth_errors_trigger_reauth(hass: HomeAssistant, freezer):
    freezer.move_to(LIVE_NOW)
    client = _live_client()
    client.async_get_track_and_trace.side_effect = AhAuthError("expired")
    coordinator = await _make_delivery_coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    client.async_get_deliveries.side_effect = AhAuthError("expired")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_delivery_api_error_marks_update_failed(hass: HomeAssistant):
    client = make_client()
    client.async_get_deliveries.side_effect = AhApiError("boom")
    coordinator = await _make_delivery_coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.parametrize(
    ("value", "date", "expected"),
    [
        ("2026-11-15T15:15:00+01:00", None, "2026-11-15T15:15:00+01:00"),
        ("2026-11-15T14:15:00Z", None, "2026-11-15T15:15:00+01:00"),
        ("2026-11-15T15:15:00", None, "2026-11-15T15:15:00+01:00"),  # naive: HA-local
        ("15:15", "2026-11-15", "2026-11-15T15:15:00+01:00"),  # bare time: on the slot date
        ("15:15:00", "2026-11-15", "2026-11-15T15:15:00+01:00"),
        ("15:15", None, None),
        ("straks", "2026-11-15", None),
        ("", "2026-11-15", None),
        (None, "2026-11-15", None),
    ],
)
async def test_api_datetime_accepts_the_plausible_formats(hass: HomeAssistant, value, date, expected):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    parsed = api_datetime(value, date)
    if expected is None:
        assert parsed is None
    else:
        assert parsed == datetime.fromisoformat(expected)
        assert parsed.tzinfo is not None
