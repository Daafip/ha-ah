"""Sensors for the Albert Heijn integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MEMBER_ID, DOMAIN
from .coordinator import AhConfigEntry, AhCoordinator, slot_start


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
            AhAirMilesSensor(coordinator, member_id),
            AhPremiumSavingsSensor(coordinator, member_id),
            AhSettlementsSensor(coordinator, member_id),
            AhSavingGoalSensor(coordinator, member_id),
            AhBasketSensor(coordinator, member_id),
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
    _attr_suggested_display_precision = 2
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
    _attr_suggested_display_precision = 2

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
    _attr_suggested_display_precision = 2
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
        return slot_start(delivery) if delivery else None

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


class AhAirMilesSensor(AhSensor):
    """Air Miles balance."""

    _attr_translation_key = "air_miles"
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> int | None:
        """Miles balance, None when the account has no Air Miles link."""
        return self.coordinator.data.miles


class AhPremiumSavingsSensor(AhSensor):
    """Total saved through the Premium subscription."""

    _attr_translation_key = "premium_savings"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def native_value(self) -> float | None:
        """Euro saved, None without a Premium subscription."""
        return self.coordinator.data.premium_savings


class AhSettlementsSensor(AhSensor):
    """Total of open settlements (refunds owed)."""

    _attr_translation_key = "settlements"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Open settlement total in euro."""
        return self.coordinator.data.settlements_total


class AhSavingGoalSensor(AhSensor):
    """The koopzegels saving goal, with progress attributes."""

    _attr_translation_key = "saving_goal"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Goal amount in euro, None when no goal is set."""
        goal = self.coordinator.data.saving_goal
        return goal.amount if goal else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Goal name and progress based on the current payout value."""
        goal = self.coordinator.data.saving_goal
        if goal is None:
            return {}
        payout = self.coordinator.data.koopzegels.payout
        progress = round(100 * payout / goal.amount, 1) if goal.amount else None
        return {"name": goal.name, "saved": payout, "progress_pct": progress}


class AhBasketSensor(AhSensor):
    """Total price of the current webshop basket."""

    _attr_translation_key = "basket"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Basket total in euro."""
        basket = self.coordinator.data.basket
        return basket.total if basket else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Number of items in the basket."""
        basket = self.coordinator.data.basket
        return {"quantity": basket.quantity} if basket else {}
