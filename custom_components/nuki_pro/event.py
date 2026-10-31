"""Event entities for the Nuki Pro integration.

* Activity (lock): every lock action with who did it and how, button or fob
  presses set to "no action", wrong keypad codes and fingerprints.
* Events (door sensor): door opened / closed, left open, status mismatch.
"""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACCESSORY_DOOR_SENSOR, DOOR_EVENT_TYPES, EVENT_TYPES
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity, async_add_dynamic_entities
from .models import NukiActivity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the activity event, and the door one once a sensor is paired."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        entities: list[NukiProEntity] = []
        if coordinator.uid("activity") not in known:
            entities.append(NukiActivityEvent(coordinator))
        if (
            coordinator.uid("door_events") not in known
            and coordinator.data.has_door_sensor
        ):
            entities.append(NukiDoorEvent(coordinator))
        return entities

    async_add_dynamic_entities(entry, async_add_entities, _build)


class _NukiEventBase(NukiProEntity, EventEntity):
    """Fire the coordinator activities matching the entity event types."""

    async def async_added_to_hass(self) -> None:
        """Listen to activities from the coordinator."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_activity_listener(self._handle_activity)
        )

    @callback
    def _handle_activity(self, activity: NukiActivity) -> None:
        if activity.event not in self.event_types:
            return
        self._trigger_event(activity.event, activity.as_dict())
        self.async_write_ha_state()


class NukiActivityEvent(_NukiEventBase):
    """Fires on each lock action, with who did it and how."""

    _attr_translation_key = "activity"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: NukiProCoordinator) -> None:
        """Create the entity on the lock device."""
        super().__init__(coordinator, "activity")


class NukiDoorEvent(_NukiEventBase):
    """Fires when the door sensor reports a change or a warning."""

    _attr_translation_key = "door_events"
    _attr_event_types = DOOR_EVENT_TYPES

    def __init__(self, coordinator: NukiProCoordinator) -> None:
        """Create the entity on the door sensor device."""
        super().__init__(coordinator, "door_events", ACCESSORY_DOOR_SENSOR)
