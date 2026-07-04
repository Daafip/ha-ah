"""Deliveries calendar for the Albert Heijn integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry, AhCoordinator, slot_end, slot_start


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the deliveries calendar from a config entry."""
    member_id = entry.data.get(CONF_MEMBER_ID, entry.entry_id)
    async_add_entities([AhDeliveryCalendar(entry.runtime_data, member_id)])


class AhDeliveryCalendar(CoordinatorEntity[AhCoordinator], CalendarEntity):
    """Grocery delivery slots as calendar events."""

    _attr_has_entity_name = True
    _attr_translation_key = "deliveries"
    _attr_attribution = "Data from the unofficial Albert Heijn API"

    def __init__(self, coordinator: AhCoordinator, member_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{member_id}_deliveries"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, member_id)},
            name="Albert Heijn",
            manufacturer="Albert Heijn",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _events(self) -> list[CalendarEvent]:
        events = []
        for delivery in self.coordinator.data.deliveries:
            start = slot_start(delivery)
            end = slot_end(delivery)
            if start is None or end is None:
                continue
            events.append(
                CalendarEvent(
                    summary="Albert Heijn bezorging",
                    start=start,
                    end=end,
                    description=delivery.status or "",
                )
            )
        return sorted(events, key=lambda event: event.start)

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next delivery."""
        now = dt_util.now()
        return next((event for event in self._events() if event.end > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Deliveries overlapping the requested window."""
        return [event for event in self._events() if event.start < end_date and event.end > start_date]
