"""Tests for the sensors."""

from unittest.mock import patch

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
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

from .const import FROZEN_NOW, MEMBER_ID, REFRESH_TOKEN, make_client


async def _setup_integration(hass: HomeAssistant, client=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Albert Heijn",
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)
    client = client or make_client()
    with patch("custom_components.albert_heijn.AhApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return client


def _entity_id(hass: HomeAssistant, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{MEMBER_ID}_{key}")
    assert entity_id is not None
    return entity_id


async def test_koopzegels_state_and_attributes(hass: HomeAssistant):
    await _setup_integration(hass)
    state = hass.states.get(_entity_id(hass, "koopzegels"))
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


async def test_receipt_and_spending_sensors(hass: HomeAssistant, freezer):
    freezer.move_to(FROZEN_NOW)
    await _setup_integration(hass)

    last = hass.states.get(_entity_id(hass, "last_receipt"))
    assert last.state == "45.67"
    assert last.attributes["moment"] == "2026-07-01T14:30:00"

    month = hass.states.get(_entity_id(hass, "month_spending"))
    assert month.state == "45.67"
    assert month.attributes["receipt_count"] == 1


async def test_next_delivery_sensor(hass: HomeAssistant):
    await hass.config.async_set_time_zone("UTC")  # slot times are HA-local
    await _setup_integration(hass)
    state = hass.states.get(_entity_id(hass, "next_delivery"))
    assert state.state == "2099-01-05T18:00:00+00:00"
    assert state.attributes["end_time"] == "20:00"
    assert state.attributes["status"] == "PLANNED"
    assert state.attributes["device_class"] == "timestamp"


async def test_optional_sensors_unknown_when_endpoints_fail(hass: HomeAssistant):
    client = make_client()
    client.async_get_receipts.side_effect = AhApiError("broke")
    client.async_get_deliveries.side_effect = AhApiError("broke")
    await _setup_integration(hass, client)

    assert hass.states.get(_entity_id(hass, "koopzegels")).state == "510.7"
    assert hass.states.get(_entity_id(hass, "last_receipt")).state == "unknown"
    assert hass.states.get(_entity_id(hass, "month_spending")).state == "unknown"
    assert hass.states.get(_entity_id(hass, "next_delivery")).state == "unknown"


async def test_sensors_unavailable_on_api_error(hass: HomeAssistant, freezer):
    client = await _setup_integration(hass)
    entity_id = _entity_id(hass, "koopzegels")
    client.async_get_koopzegels.side_effect = AhApiError("down")

    freezer.tick(DEFAULT_UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "unavailable"
    assert hass.states.get(_entity_id(hass, "last_receipt")).state == "unavailable"


async def test_sensor_recovers_after_error(hass: HomeAssistant, freezer):
    client = await _setup_integration(hass)
    entity_id = _entity_id(hass, "koopzegels")
    client.async_get_koopzegels.side_effect = AhApiError("down")
    freezer.tick(DEFAULT_UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"

    client.async_get_koopzegels.side_effect = None
    freezer.tick(DEFAULT_UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "510.7"
