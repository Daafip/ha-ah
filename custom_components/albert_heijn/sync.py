"""Two-way sync between the AH shopping list and an existing HA todo entity.

This is the built-in alternative to the manual automation documented in the
README: instead of exposing a dedicated ``todo.albert_heijn_*`` entity that
the user then wires up themselves, this drives an existing entity (typically
``todo.shopping_list``) directly via the ``todo`` services.

Direction is split the same way the README automation split it, and for the
same reason: pushing (HA -> AH) always runs before any pull that could
otherwise read a not-yet-pushed addition as "absent from AH" and mistakenly
complete it.

- HA state changes on the target entity -> push: new needs_action items are
  added to the AH list; items completed in HA are checked in the AH app.
- AH poll updates (the list coordinator refreshing) -> pull: items checked or
  removed in the AH app are marked completed in the target entity. Never
  un-completes anything and never adds AH-only items into HA (matching the
  integration's non-goals: no resurrection, no reverse-add).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .api import AhApiClient, AhApiError, AhListItem
from .coordinator import AhListCoordinator

_LOGGER = logging.getLogger(__name__)


def _norm(value: str) -> str:
    return value.strip().lower()


class AhListSyncManager:
    """Keeps an existing HA todo entity in sync with the AH shopping list."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AhApiClient,
        list_coordinator: AhListCoordinator,
        target_entity_id: str,
    ) -> None:
        self._hass = hass
        self._client = client
        self._list_coordinator = list_coordinator
        self.target_entity_id = target_entity_id
        self._unsub_state: Callable[[], None] | None = None
        self._unsub_coordinator: Callable[[], None] | None = None

    @callback
    def async_setup(self) -> None:
        """Start listening for changes on both sides."""
        self._unsub_state = async_track_state_change_event(
            self._hass, [self.target_entity_id], self._async_handle_ha_change
        )
        self._unsub_coordinator = self._list_coordinator.async_add_listener(self._async_handle_ah_update)

    @callback
    def async_unload(self) -> None:
        """Stop listening."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        if self._unsub_coordinator is not None:
            self._unsub_coordinator()
            self._unsub_coordinator = None

    @callback
    def _async_handle_ha_change(self, event: Event[EventStateChangedData]) -> None:
        self._hass.async_create_task(self._async_push_to_ah(), eager_start=True)

    @callback
    def _async_handle_ah_update(self) -> None:
        if not self._list_coordinator.last_update_success:
            return
        self._hass.async_create_task(self._async_pull_from_ah(), eager_start=True)

    async def _async_get_target_items(self) -> list[dict] | None:
        try:
            response = await self._hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": self.target_entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug("Could not read %s: %s", self.target_entity_id, err)
            return None
        return ((response or {}).get(self.target_entity_id) or {}).get("items") or []

    async def _async_push_to_ah(self) -> None:
        """HA -> AH: add new items, check off items completed in HA."""
        target_items = await self._async_get_target_items()
        if target_items is None:
            return
        ah_by_name: dict[str, AhListItem] = {
            _norm(item.description): item for item in self._list_coordinator.data or []
        }

        for target_item in target_items:
            summary = target_item.get("summary") or ""
            key = _norm(summary)
            if not key:
                continue
            ah_item = ah_by_name.get(key)
            status = target_item.get("status")
            try:
                if status == "needs_action" and ah_item is None:
                    await self._client.async_add_free_text_item(summary)
                elif status == "completed" and ah_item is not None and not ah_item.checked:
                    await self._client.async_set_item_checked(ah_item, True)
            except AhApiError as err:
                _LOGGER.debug("Syncing %r to the AH list failed: %s", summary, err)

        await self._list_coordinator.async_request_refresh()

    async def _async_pull_from_ah(self) -> None:
        """AH -> HA: complete items that were checked or deleted in the AH app."""
        target_items = await self._async_get_target_items()
        if target_items is None:
            return
        ah_by_name: dict[str, AhListItem] = {
            _norm(item.description): item for item in self._list_coordinator.data or []
        }

        for target_item in target_items:
            if target_item.get("status") != "needs_action":
                continue
            summary = target_item.get("summary") or ""
            key = _norm(summary)
            if not key:
                continue
            ah_item = ah_by_name.get(key)
            if ah_item is not None and not ah_item.checked:
                continue  # still open on the AH side, nothing to pull
            try:
                await self._hass.services.async_call(
                    "todo",
                    "update_item",
                    {"entity_id": self.target_entity_id, "item": target_item["uid"], "status": "completed"},
                    blocking=True,
                )
            except HomeAssistantError as err:
                _LOGGER.debug("Completing %r in %s failed: %s", summary, self.target_entity_id, err)
