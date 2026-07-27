"""One-way, on-demand push from a Home Assistant todo list to the AH list.

Earlier versions kept both sides in sync continuously and in both directions.
That fell apart on longer lists: every HA state change and every AH poll
kicked off a full reconcile, each item was written with its own request, and
the two directions kept re-reading each other's half-finished work.

So: one direction, one moment. The user calls
``albert_heijn.sync_shopping_list`` (or presses the sync button) and the HA
list is pushed onto the AH list in a single batched write. Nothing runs on a
timer, nothing listens for state changes, and nothing is ever written back
into Home Assistant.

What a push does, per item on the source list:

- open in HA, not on the AH list -> added as free text;
- completed in HA, still open on AH -> checked off in the app;
- open in HA but already checked in the app -> left alone (you checked it off
  while shopping; re-opening it would fight the app);
- on the AH list but not in HA -> left alone (it was added in the app).

Matching is case- and whitespace-insensitive, because the AH API merges by
description and HA normalises whatever the user typed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import AhApiClient, AhApiError, AhListItem
from .coordinator import AhListCoordinator

_LOGGER = logging.getLogger(__name__)


def _norm(value: str) -> str:
    return value.strip().lower()


@dataclass(frozen=True)
class SyncResult:
    """What one push changed on the AH side."""

    source_entity_id: str
    added: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    unchanged: int = 0

    def as_response(self) -> dict:
        """The service response shape."""
        return {
            "source_entity_id": self.source_entity_id,
            "added": self.added,
            "checked": self.checked,
            "unchanged": self.unchanged,
        }


class AhListSyncManager:
    """Pushes a Home Assistant todo list onto the AH shopping list on demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AhApiClient,
        list_coordinator: AhListCoordinator,
        source_entity_id: str,
    ) -> None:
        self._hass = hass
        self._client = client
        self._list_coordinator = list_coordinator
        self.source_entity_id = source_entity_id
        # A push reads both sides and then writes; two overlapping runs (button
        # pressed twice, automation racing a manual call) would write the same
        # additions twice.
        self._lock = asyncio.Lock()

    async def async_push(self, source_entity_id: str | None = None) -> SyncResult:
        """Push the source todo list onto the AH shopping list.

        Raises HomeAssistantError when either side cannot be read or the write
        fails: this only ever runs on an explicit user action, so failures
        belong in front of the user instead of in the debug log.
        """
        entity_id = source_entity_id or self.source_entity_id
        async with self._lock:
            source_items = await self._async_get_source_items(entity_id)
            ah_items = await self._async_get_ah_items()
            result, writes = self._plan(entity_id, source_items, ah_items)
            if writes:
                try:
                    await self._client.async_write_list_items(writes)
                except AhApiError as err:
                    raise HomeAssistantError(f"Writing to the Albert Heijn shopping list failed: {err}") from err
                await self._list_coordinator.async_request_refresh()
            _LOGGER.debug(
                "Pushed %s to the AH list: %d added, %d checked off, %d already in sync",
                entity_id,
                len(result.added),
                len(result.checked),
                result.unchanged,
            )
            return result

    async def _async_get_source_items(self, entity_id: str) -> list[dict]:
        """Read the source list (all statuses; get_items returns both by default)."""
        response = await self._hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
        return ((response or {}).get(entity_id) or {}).get("items") or []

    async def _async_get_ah_items(self) -> list[AhListItem]:
        """A fresh AH snapshot: this is the only moment the AH side is read."""
        await self._list_coordinator.async_refresh()
        if not self._list_coordinator.last_update_success:
            raise HomeAssistantError(
                f"Could not read the Albert Heijn shopping list: {self._list_coordinator.last_exception}"
            )
        return self._list_coordinator.data or []

    @staticmethod
    def _plan(
        entity_id: str, source_items: list[dict], ah_items: list[AhListItem]
    ) -> tuple[SyncResult, list[AhListItem]]:
        """Diff the two lists into a result and the items to write."""
        ah_by_name = {_norm(item.description): item for item in ah_items}

        # Duplicates within the source list collapse onto one AH item; an open
        # entry wins over a completed one, so a re-added item is never checked
        # off by its own leftover.
        open_names: dict[str, str] = {}
        done_names: dict[str, str] = {}
        for item in source_items:
            summary = (item.get("summary") or "").strip()
            if not (key := _norm(summary)):
                continue
            bucket = done_names if item.get("status") == "completed" else open_names
            bucket.setdefault(key, summary)

        writes: list[AhListItem] = []
        added: list[str] = []
        checked: list[str] = []
        unchanged = 0

        for key, summary in open_names.items():
            if key in ah_by_name:
                unchanged += 1  # already there, checked or not: leave the app alone
                continue
            writes.append(AhListItem(description=summary, checked=False))
            added.append(summary)

        for key, summary in done_names.items():
            if key in open_names:
                continue
            ah_item = ah_by_name.get(key)
            if ah_item is None or ah_item.checked:
                continue
            writes.append(replace(ah_item, checked=True))
            checked.append(summary)

        return SyncResult(entity_id, added=added, checked=checked, unchanged=unchanged), writes
