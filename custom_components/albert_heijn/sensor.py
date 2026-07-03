"""Koopzegels sensor for the Albert Heijn integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry, AhCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the koopzegels sensor from a config entry."""
    member_id = entry.data.get(CONF_MEMBER_ID, entry.entry_id)
    async_add_entities([AhKoopzegelsSensor(entry.runtime_data, member_id)])


class AhKoopzegelsSensor(CoordinatorEntity[AhCoordinator], SensorEntity):
    """Euro value of the saved koopzegels."""

    _attr_has_entity_name = True
    _attr_translation_key = "koopzegels"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_attribution = "Data from the unofficial Albert Heijn API"

    def __init__(self, coordinator: AhCoordinator, member_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{member_id}_koopzegels"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, member_id)},
            name="Albert Heijn",
            manufacturer="Albert Heijn",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float:
        """Payout value of the balance in euro."""
        return self.coordinator.data.payout

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Stamp counts and booklet progress."""
        data = self.coordinator.data
        return {
            "stamp_count": data.stamp_count,
            "full_booklets": data.full_booklets,
            "booklet_stamps": data.booklet_stamps,
            "stamps_until_next_booklet": data.stamps_until_next_booklet,
            "full_booklet_target": data.full_booklet_target,
            "invested": data.invested,
            "interest": data.interest,
        }
