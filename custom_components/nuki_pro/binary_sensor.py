"""Binary sensors for the Nuki Pro integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ACCESSORY_DOOR_SENSOR,
    ACCESSORY_KEYPAD,
    DOOR_CLOSED,
    DOOR_OPENED,
    DOOR_REMOVED,
    STATE_LOCKED,
    STATE_LOCKING,
    STATE_UNLATCHED,
    STATE_UNLATCHING,
    STATE_UNLOCKED,
    STATE_UNLOCKED_LNG,
    STATE_UNLOCKING,
)
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity, async_add_dynamic_entities
from .models import NukiData

PARALLEL_UPDATES = 0

# Bolt not thrown; uncalibrated, motor blocked and undefined stay unknown
_UNLOCKED_STATES = frozenset(
    {
        STATE_UNLOCKING,
        STATE_UNLOCKED,
        STATE_LOCKING,
        STATE_UNLATCHED,
        STATE_UNLOCKED_LNG,
        STATE_UNLATCHING,
    }
)


def _door_open(data: NukiData) -> bool | None:
    door_state = data.status.door_state
    if door_state == DOOR_OPENED:
        return True
    if door_state == DOOR_CLOSED:
        return False
    return None


def _unlocked(data: NukiData) -> bool | None:
    state = data.status.state
    if state == STATE_LOCKED:
        return False
    if state in _UNLOCKED_STATES:
        return True
    return None


def _keypad_tampered(data: NukiData) -> bool | None:
    mounting = data.status.keypad_mounting_state
    if mounting in (None, 0):
        return None
    return mounting != 1


@dataclass(frozen=True, kw_only=True)
class NukiBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Nuki binary sensor."""

    value_fn: Callable[[NukiData], bool | None]
    exists_fn: Callable[[NukiData], bool] = lambda _: True
    # Device of the entity: None for the lock, else an accessory
    accessory: str | None = None
    requires_web: bool = False
    # Shown even when both channels are down (channel health sensors)
    always_available: bool = False


BINARY_SENSORS: tuple[NukiBinarySensorDescription, ...] = (
    # Lock
    NukiBinarySensorDescription(
        # hass_nuki_ng "Locked": on means unlocked (lock device class)
        key="locked",
        translation_key="locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_unlocked,
    ),
    NukiBinarySensorDescription(
        key="battery_critical",
        translation_key="battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.battery_critical,
    ),
    NukiBinarySensorDescription(
        key="battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.battery_charging,
        exists_fn=lambda data: data.status.battery_charging is not None,
    ),
    NukiBinarySensorDescription(
        key="night_mode",
        translation_key="night_mode",
        value_fn=lambda data: data.status.night_mode,
        exists_fn=lambda data: data.status.night_mode is not None,
    ),
    NukiBinarySensorDescription(
        key="mqtt_connected",
        translation_key="mqtt_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.mqtt_online,
        exists_fn=lambda data: bool(data.extra.get("mqtt_enabled")),
        always_available=True,
    ),
    NukiBinarySensorDescription(
        key="server_connected",
        translation_key="server_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.server_connected,
        exists_fn=lambda data: data.server_connected is not None,
    ),
    NukiBinarySensorDescription(
        key="web_api_connected",
        translation_key="web_api_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.web_available,
        exists_fn=lambda data: bool(data.extra.get("web_enabled")),
        always_available=True,
    ),
    # Door sensor accessory
    NukiBinarySensorDescription(
        # Main entity of the door sensor device: named after the device
        key="door",
        name=None,
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_door_open,
        exists_fn=lambda data: data.has_door_sensor,
        accessory=ACCESSORY_DOOR_SENSOR,
    ),
    NukiBinarySensorDescription(
        key="doorsensor_battery_critical",
        translation_key="battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.doorsensor_battery_critical,
        exists_fn=lambda data: data.has_door_sensor
        and data.status.doorsensor_battery_critical is not None,
        accessory=ACCESSORY_DOOR_SENSOR,
    ),
    NukiBinarySensorDescription(
        key="door_sensor_tamper",
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.door_state == DOOR_REMOVED,
        exists_fn=lambda data: data.has_door_sensor,
        accessory=ACCESSORY_DOOR_SENSOR,
    ),
    # Keypad accessory
    NukiBinarySensorDescription(
        key="keypad_battery_critical",
        translation_key="battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status.keypad_battery_critical,
        exists_fn=lambda data: data.has_keypad,
        accessory=ACCESSORY_KEYPAD,
    ),
    NukiBinarySensorDescription(
        key="keypad_tamper",
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_keypad_tampered,
        exists_fn=lambda data: data.has_keypad
        and data.status.keypad_mounting_state not in (None, 0),
        accessory=ACCESSORY_KEYPAD,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors, adding new ones when their data shows up."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        return [
            NukiBinarySensor(coordinator, description)
            for description in BINARY_SENSORS
            if coordinator.uid(description.key) not in known
            and description.exists_fn(coordinator.data)
        ]

    async_add_dynamic_entities(entry, async_add_entities, _build)


class NukiBinarySensor(NukiProEntity, BinarySensorEntity):
    """Binary sensor reading one value of the coordinator data."""

    entity_description: NukiBinarySensorDescription

    def __init__(
        self,
        coordinator: NukiProCoordinator,
        description: NukiBinarySensorDescription,
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key, description.accessory)
        self.entity_description = description
        self._requires_web = description.requires_web

    @property
    def available(self) -> bool:
        """Channel health sensors stay available to report the outage."""
        if self.entity_description.always_available:
            return True
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Return the value."""
        return self.entity_description.value_fn(self.data)
