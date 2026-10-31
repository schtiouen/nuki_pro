"""Sensors for the Nuki Pro integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    ACCESSORY_DOOR_SENSOR,
    ACCESSORY_KEYPAD,
    ACTIVITY_TRIGGERS,
    DOOR_CLOSED,
    DOOR_OPENED,
    DOOR_STATES,
    KEYPAD_MOUNTING_STATES,
    LOCK_ACTIVITY_LOG_ACTIONS,
    LOCK_MODES,
    LOCK_STATES,
    LOCKING_LOG_ACTIONS,
    LOG_ACTIONS,
    SERVER_STATES,
    STATE_LOCKED,
    UNLATCH_LOG_ACTIONS,
    UNLOCK_LOG_ACTIONS,
)
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity, async_add_dynamic_entities
from .models import NukiActivity, NukiData

PARALLEL_UPDATES = 0


def _options(mapping: Mapping[int, str]) -> list[str]:
    return list(dict.fromkeys(mapping.values()))


def _door_security_state(data: NukiData) -> str | None:
    status = data.status
    if status.door_state == DOOR_OPENED:
        return "open"
    if status.door_state == DOOR_CLOSED:
        if status.state == STATE_LOCKED:
            return "closed_and_locked"
        return "closed_and_unlocked"
    return None


def _activity_attributes(activity: NukiActivity | None) -> dict[str, Any]:
    if activity is None:
        return {}
    return {
        "action": LOG_ACTIONS.get(activity.action, str(activity.action)),
        "trigger": activity.trigger,
        "source": activity.source,
        "auth_id": activity.auth_id,
        "timestamp": activity.timestamp.isoformat(),
        "origin": activity.origin,
    }


@dataclass(frozen=True, kw_only=True)
class NukiSensorDescription(SensorEntityDescription):
    """Describe a Nuki sensor."""

    value_fn: Callable[[NukiData], StateType | datetime]
    exists_fn: Callable[[NukiData], bool] = lambda _: True
    attributes_fn: Callable[[NukiData], dict[str, Any]] | None = None
    # Device of the entity: None for the lock, else an accessory
    accessory: str | None = None
    requires_web: bool = False


def _user_sensor(key: str, actions: frozenset[int]) -> NukiSensorDescription:
    """Name of the person behind the latest matching activity."""
    return NukiSensorDescription(
        key=key,
        translation_key=key,
        value_fn=lambda data: (
            activity.user if (activity := data.last_activity(actions)) else None
        ),
        attributes_fn=lambda data: _activity_attributes(data.last_activity(actions)),
    )


SENSORS: tuple[NukiSensorDescription, ...] = (
    NukiSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.battery_charge,
        exists_fn=lambda data: data.status.battery_charge is not None,
    ),
    NukiSensorDescription(
        key="lock_state",
        translation_key="lock_state",
        device_class=SensorDeviceClass.ENUM,
        options=_options(LOCK_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: LOCK_STATES.get(data.status.state),  # type: ignore[arg-type]
    ),
    NukiSensorDescription(
        key="lock_mode",
        translation_key="lock_mode",
        device_class=SensorDeviceClass.ENUM,
        options=_options(LOCK_MODES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: LOCK_MODES.get(data.status.mode),  # type: ignore[arg-type]
    ),
    NukiSensorDescription(
        key="door_state",
        translation_key="door_state",
        device_class=SensorDeviceClass.ENUM,
        options=_options(DOOR_STATES),
        value_fn=lambda data: DOOR_STATES.get(data.status.door_state),  # type: ignore[arg-type]
        exists_fn=lambda data: data.has_door_sensor,
        accessory=ACCESSORY_DOOR_SENSOR,
    ),
    NukiSensorDescription(
        key="door_security_state",
        translation_key="door_security_state",
        device_class=SensorDeviceClass.ENUM,
        options=["closed_and_locked", "closed_and_unlocked", "open"],
        value_fn=_door_security_state,
        exists_fn=lambda data: data.has_door_sensor,
    ),
    _user_sensor("last_user", LOCK_ACTIVITY_LOG_ACTIONS),
    _user_sensor("last_unlock_user", UNLOCK_LOG_ACTIONS),
    _user_sensor("last_unlatch_user", UNLATCH_LOG_ACTIONS),
    _user_sensor("last_lock_user", LOCKING_LOG_ACTIONS),
    NukiSensorDescription(
        key="last_action",
        translation_key="last_action",
        device_class=SensorDeviceClass.ENUM,
        options=[LOG_ACTIONS[code] for code in sorted(LOCK_ACTIVITY_LOG_ACTIONS)],
        value_fn=lambda data: (
            LOG_ACTIONS.get(activity.action)
            if (activity := data.last_activity(LOCK_ACTIVITY_LOG_ACTIONS))
            else None
        ),
        attributes_fn=lambda data: _activity_attributes(
            data.last_activity(LOCK_ACTIVITY_LOG_ACTIONS)
        ),
    ),
    NukiSensorDescription(
        key="last_action_trigger",
        translation_key="last_action_trigger",
        device_class=SensorDeviceClass.ENUM,
        options=list(ACTIVITY_TRIGGERS),
        value_fn=lambda data: (
            activity.trigger
            if (activity := data.last_activity())
            and activity.trigger in ACTIVITY_TRIGGERS
            else None
        ),
    ),
    NukiSensorDescription(
        key="last_action_time",
        translation_key="last_action_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            activity.timestamp if (activity := data.last_activity()) else None
        ),
    ),
    NukiSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firmware,
        exists_fn=lambda data: data.firmware is not None,
    ),
    NukiSensorDescription(
        key="server_state",
        translation_key="server_state",
        device_class=SensorDeviceClass.ENUM,
        options=_options(SERVER_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: SERVER_STATES.get(data.server_state),  # type: ignore[arg-type]
        exists_fn=lambda data: data.server_state is not None,
        requires_web=True,
    ),
    NukiSensorDescription(
        key="keypad_mounting_state",
        translation_key="keypad_mounting_state",
        device_class=SensorDeviceClass.ENUM,
        options=_options(KEYPAD_MOUNTING_STATES),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: KEYPAD_MOUNTING_STATES.get(
            data.status.keypad_mounting_state  # type: ignore[arg-type]
        ),
        exists_fn=lambda data: data.has_keypad
        and data.status.keypad_mounting_state is not None,
        accessory=ACCESSORY_KEYPAD,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors, adding new ones when their data shows up."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        return [
            NukiSensor(coordinator, description)
            for description in SENSORS
            if coordinator.uid(description.key) not in known
            and description.exists_fn(coordinator.data)
        ]

    async_add_dynamic_entities(entry, async_add_entities, _build)


class NukiSensor(NukiProEntity, SensorEntity):
    """Sensor reading one value of the coordinator data."""

    entity_description: NukiSensorDescription

    def __init__(
        self, coordinator: NukiProCoordinator, description: NukiSensorDescription
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key, description.accessory)
        self.entity_description = description
        self._requires_web = description.requires_web

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.entity_description.value_fn(self.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return activity details for the activity sensors."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.data)
