"""Tests for the coordinator."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import DOMAIN
from custom_components.albert_heijn.coordinator import AhCoordinator

from .const import FROZEN_NOW, KOOPZEGELS_DATA, make_client


def _make_coordinator(hass: HomeAssistant, client) -> AhCoordinator:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AhCoordinator(hass, entry, client)


async def test_update_success(hass: HomeAssistant, freezer):
    freezer.move_to(FROZEN_NOW)
    coordinator = _make_coordinator(hass, make_client())
    data = await coordinator._async_update_data()

    assert data.koopzegels == KOOPZEGELS_DATA
    assert data.last_receipt.transaction_id == "9001"
    assert data.month_spent == 45.67  # only the July receipt counts
    assert data.month_receipt_count == 1
    assert data.next_delivery.order_id == 555  # past delivery is skipped


async def test_optional_endpoints_degrade_gracefully(hass: HomeAssistant):
    client = make_client()
    client.async_get_receipts.side_effect = AhApiError("receipts broke")
    client.async_get_deliveries.side_effect = AhApiError("deliveries broke")
    coordinator = _make_coordinator(hass, client)
    data = await coordinator._async_update_data()

    assert data.koopzegels == KOOPZEGELS_DATA
    assert data.last_receipt is None
    assert data.month_spent is None
    assert data.month_receipt_count is None
    assert data.next_delivery is None


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
