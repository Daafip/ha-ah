"""Tests for redacted diagnostics."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.const import (
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.albert_heijn.diagnostics import async_get_config_entry_diagnostics

from .const import KOOPZEGELS_DATA, MEMBER_ID, REFRESH_TOKEN


async def test_diagnostics_redacts_secrets(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
        options={CONF_UPDATE_INTERVAL: 12},
    )
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_koopzegels.return_value = KOOPZEGELS_DATA
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry_data"][CONF_REFRESH_TOKEN] == "**REDACTED**"
    assert diagnostics["entry_data"][CONF_MEMBER_ID] == "**REDACTED**"
    assert REFRESH_TOKEN not in str(diagnostics)
    assert MEMBER_ID not in str(diagnostics)
    assert diagnostics["options"] == {CONF_UPDATE_INTERVAL: 12}
    assert diagnostics["last_update_success"] is True
    assert diagnostics["koopzegels"]["payout"] == 510.7
