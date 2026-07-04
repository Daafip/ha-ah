"""Tests for the deliveries calendar."""

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.albert_heijn.const import CONF_MEMBER_ID, CONF_REFRESH_TOKEN, DOMAIN

from .const import MEMBER_ID, REFRESH_TOKEN, make_client


async def _setup(hass: HomeAssistant):
    await hass.config.async_set_time_zone("UTC")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MEMBER_ID,
        data={CONF_REFRESH_TOKEN: REFRESH_TOKEN, CONF_MEMBER_ID: MEMBER_ID},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.albert_heijn.AhApiClient", return_value=make_client()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id("calendar", DOMAIN, f"{MEMBER_ID}_deliveries")
    assert entity_id is not None
    return entity_id


async def test_calendar_shows_next_delivery(hass: HomeAssistant):
    entity_id = await _setup(hass)
    state = hass.states.get(entity_id)
    # The 2099 slot is upcoming but not active now.
    assert state.state == "off"
    assert state.attributes["start_time"] == "2099-01-05 18:00:00"
    assert state.attributes["end_time"] == "2099-01-05 20:00:00"
    assert state.attributes["message"] == "Albert Heijn bezorging"


async def test_calendar_get_events_window(hass: HomeAssistant):
    entity_id = await _setup(hass)
    calendar = hass.data["entity_components"]["calendar"].get_entity(entity_id)

    tz = dt_util.get_default_time_zone()
    events = await calendar.async_get_events(
        hass,
        datetime(2099, 1, 1, tzinfo=tz),
        datetime(2099, 1, 31, tzinfo=tz),
    )
    assert len(events) == 1
    assert events[0].start == datetime(2099, 1, 5, 18, 0, tzinfo=tz)
    assert events[0].end == datetime(2099, 1, 5, 20, 0, tzinfo=tz)

    # Past window catches the delivered January 2026 order.
    events = await calendar.async_get_events(
        hass,
        datetime(2026, 1, 1, tzinfo=tz),
        datetime(2026, 1, 31, tzinfo=tz),
    )
    assert len(events) == 1
    assert events[0].description == "DELIVERED"

    # Empty window in between.
    start = datetime(2030, 1, 1, tzinfo=tz)
    assert await calendar.async_get_events(hass, start, start + timedelta(days=30)) == []
