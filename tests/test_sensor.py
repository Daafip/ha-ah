"""Tests for the koopzegels sensor."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.albert_heijn.api import AhApiError
from custom_components.albert_heijn.const import (
    CONF_MEMBER_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    UPDATE_INTERVAL,
)

from .const import KOOPZEGELS_DATA, MEMBER_ID, REFRESH_TOKEN


async def _setup_integration(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Albert Heijn",
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_koopzegels.return_value = KOOPZEGELS_DATA
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{MEMBER_ID}_koopzegels")
    assert entity_id is not None
    return entity_id, client


async def test_sensor_state_and_attributes(hass: HomeAssistant):
    entity_id, _ = await _setup_integration(hass)
    state = hass.states.get(entity_id)
    assert state.state == "510.7"
    assert state.attributes["unit_of_measurement"] == "EUR"
    assert state.attributes["device_class"] == "monetary"
    assert state.attributes["state_class"] == "total"
    assert state.attributes["stamp_count"] == 1030
    assert state.attributes["full_booklets"] == 2
    assert state.attributes["booklet_stamps"] == 50
    assert state.attributes["stamps_until_next_booklet"] == 440
    assert state.attributes["full_booklet_target"] == 490
    assert state.attributes["invested"] == 504.7
    assert state.attributes["interest"] == 6.0


async def test_sensor_unavailable_on_api_error(hass: HomeAssistant, freezer):
    entity_id, client = await _setup_integration(hass)
    client.async_get_koopzegels.side_effect = AhApiError("down")

    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "unavailable"


async def test_sensor_recovers_after_error(hass: HomeAssistant, freezer):
    entity_id, client = await _setup_integration(hass)
    client.async_get_koopzegels.side_effect = AhApiError("down")
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"

    client.async_get_koopzegels.side_effect = None
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "510.7"
