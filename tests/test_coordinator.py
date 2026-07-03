"""Tests for the coordinator."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.api import AhApiError, AhAuthError
from custom_components.albert_heijn.const import DOMAIN
from custom_components.albert_heijn.coordinator import AhCoordinator

from .const import KOOPZEGELS_DATA


def _make_coordinator(hass: HomeAssistant, client) -> AhCoordinator:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return AhCoordinator(hass, entry, client)


async def test_update_success(hass: HomeAssistant):
    client = AsyncMock()
    client.async_get_koopzegels.return_value = KOOPZEGELS_DATA
    coordinator = _make_coordinator(hass, client)
    assert await coordinator._async_update_data() == KOOPZEGELS_DATA


async def test_auth_error_triggers_reauth(hass: HomeAssistant):
    client = AsyncMock()
    client.async_get_koopzegels.side_effect = AhAuthError("expired")
    coordinator = _make_coordinator(hass, client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_marks_update_failed(hass: HomeAssistant):
    client = AsyncMock()
    client.async_get_koopzegels.side_effect = AhApiError("boom")
    coordinator = _make_coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
