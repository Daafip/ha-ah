"""Sensors for the Albert Heijn integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry, AhCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from a config entry."""
    member_id = entry.data.get(CONF_MEMBER_ID, entry.entry_id)
    coordinator = entry.runtime_data
    async_add_entities(
        [
            AhKoopzegelsSensor(coordinator, member_id),
            AhLastReceiptSensor(coordinator, member_id),
            AhMonthSpendingSensor(coordinator, member_id),
            AhNextDeliverySensor(coordinator, member_id),
        ]
    )


class AhSensor(CoordinatorEntity[AhCoordinator], SensorEntity):
    """Base sensor: one AH account device, unique id per translation key."""

    _attr_has_entity_name = True
    _attr_attribution = "Data from the unofficial Albert Heijn API"

    def __init__(self, coordinator: AhCoordinator, member_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{member_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, member_id)},
            name="Albert Heijn",
            manufacturer="Albert Heijn",
            entry_type=DeviceEntryType.SERVICE,
        )


class AhKoopzegelsSensor(AhSensor):
    """Euro value of the saved koopzegels."""

    _attr_translation_key = "koopzegels"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: AhCoordinator, member_id: str) -> None:
        super().__init__(coordinator, member_id)
        # Pre-0.3.0 unique_id; do not regenerate from the translation key.
        self._attr_unique_id = f"{member_id}_koopzegels"

    @property
    def native_value(self) -> float:
        """Payout value of the balance in euro."""
        return self.coordinator.data.koopzegels.payout

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Stamp counts and booklet progress."""
        data = self.coordinator.data.koopzegels
        return {
            "stamp_count": data.stamp_count,
            "full_booklets": data.full_booklets,
            "booklet_stamps": data.booklet_stamps,
            "stamps_until_next_booklet": data.stamps_until_next_booklet,
            "full_booklet_target": data.full_booklet_target,
            "invested": data.invested,
            "interest": data.interest,
        }


class AhLastReceiptSensor(AhSensor):
    """Total of the most recent in-store receipt."""

    _attr_translation_key = "last_receipt"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"

    @property
    def native_value(self) -> float | None:
        """Receipt total in euro, or None when no receipts are known."""
        receipt = self.coordinator.data.last_receipt
        return receipt.total if receipt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Moment of the receipt."""
        receipt = self.coordinator.data.last_receipt
        if receipt is None:
            return {}
        return {"moment": receipt.moment}


class AhMonthSpendingSensor(AhSensor):
    """Sum of in-store receipts in the current calendar month."""

    _attr_translation_key = "month_spending"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> float | None:
        """Euro spent in-store this month."""
        return self.coordinator.data.month_spent

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Number of receipts counted."""
        return {"receipt_count": self.coordinator.data.month_receipt_count}


class AhNextDeliverySensor(AhSensor):
    """Start of the next planned grocery delivery slot."""

    _attr_translation_key = "next_delivery"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Slot start as a timezone-aware datetime."""
        delivery = self.coordinator.data.next_delivery
        if delivery is None:
            return None
        try:
            naive = datetime.fromisoformat(f"{delivery.date}T{delivery.start_time or '00:00'}")
        except ValueError:
            return None
        return naive.replace(tzinfo=dt_util.get_default_time_zone())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Slot window, status and order id."""
        delivery = self.coordinator.data.next_delivery
        if delivery is None:
            return {}
        return {
            "date": delivery.date,
            "start_time": delivery.start_time,
            "end_time": delivery.end_time,
            "status": delivery.status,
            "order_id": delivery.order_id,
        }
