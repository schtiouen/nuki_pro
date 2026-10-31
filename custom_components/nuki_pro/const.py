"""Constants for the Nuki Pro integration."""

from __future__ import annotations

from enum import IntEnum, StrEnum
import logging
from typing import Final

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "nuki_pro"
MANUFACTURER: Final = "Nuki Home Solutions"

# Config entry data
CONF_NUKI_ID: Final = "nuki_id"
CONF_DEVICE_TYPE: Final = "device_type"
CONF_SMARTLOCK_ID: Final = "smartlock_id"
CONF_API_TOKEN: Final = "api_token"
CONF_USE_MQTT: Final = "use_mqtt"
CONF_MQTT_TOPIC: Final = "mqtt_topic"

# Config entry options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ACTION_TRANSPORT: Final = "action_transport"
CONF_AUTH_ENTITIES: Final = "auth_entities"

DEFAULT_MQTT_BASE_TOPIC: Final = "nuki"

# Accessories shown as their own devices, linked to the lock
ACCESSORY_DOOR_SENSOR: Final = "door_sensor"
ACCESSORY_KEYPAD: Final = "keypad"
ACCESSORY_FOB: Final = "fob"
# Web API polling. MQTT pushes the live state, so the cloud is only polled
# for settings, users and logs; without MQTT the state comes from the cloud.
DEFAULT_SCAN_INTERVAL_WITH_MQTT: Final = 300
DEFAULT_SCAN_INTERVAL_WEB_ONLY: Final = 30
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600
# Authorizations and the log change rarely: re-read every 15 minutes, and
# right after a lock activity or a change made from Home Assistant.
AUTHS_REFRESH_EVERY: Final = 900
LOGS_REFRESH_EVERY: Final = 900
LOGS_LIMIT: Final = 20


class ActionTransport(StrEnum):
    """Channel used to send lock actions."""

    AUTO = "auto"
    MQTT = "mqtt"
    WEB = "web"


class DeviceType(IntEnum):
    """Nuki device types (Web API `type`, MQTT `deviceType`)."""

    SMARTLOCK_1_2 = 0
    BOX = 1
    OPENER = 2
    SMARTDOOR = 3
    SMARTLOCK_3_4 = 4
    SMARTLOCK_5 = 5


LOCK_DEVICE_TYPES: Final = frozenset(
    {
        DeviceType.SMARTLOCK_1_2,
        DeviceType.SMARTDOOR,
        DeviceType.SMARTLOCK_3_4,
        DeviceType.SMARTLOCK_5,
    }
)

# Web API config.productVariant, only for Smart Lock 5th generation
PRODUCT_VARIANTS: Final = {1: "Go", 2: "Pro", 3: "Ultra"}


class LockAction(StrEnum):
    """Lock actions exposed by the integration."""

    UNLOCK = "unlock"
    LOCK = "lock"
    UNLATCH = "unlatch"
    LOCK_N_GO = "lock_n_go"
    LOCK_N_GO_UNLATCH = "lock_n_go_unlatch"
    FULL_LOCK = "full_lock"


# Web API: action code and option mask (4 = full lock)
WEB_LOCK_ACTIONS: Final[dict[LockAction, tuple[int, int]]] = {
    LockAction.UNLOCK: (1, 0),
    LockAction.LOCK: (2, 0),
    LockAction.UNLATCH: (3, 0),
    LockAction.LOCK_N_GO: (4, 0),
    LockAction.LOCK_N_GO_UNLATCH: (5, 0),
    LockAction.FULL_LOCK: (2, 4),
}

# Smartlock state (Web API state.state / MQTT state), lock device types
LOCK_STATES: Final = {
    0: "uncalibrated",
    1: "locked",
    2: "unlocking",
    3: "unlocked",
    4: "locking",
    5: "unlatched",
    6: "unlocked_lock_n_go",
    7: "unlatching",
    224: "error_wrong_entry_code",
    225: "error_wrong_fingerprint",
    254: "motor_blocked",
    255: "undefined",
}
STATE_LOCKED: Final = 1
STATE_UNLOCKING: Final = 2
STATE_UNLOCKED: Final = 3
STATE_LOCKING: Final = 4
STATE_UNLATCHED: Final = 5
STATE_UNLOCKED_LNG: Final = 6
STATE_UNLATCHING: Final = 7
STATE_WRONG_CODE: Final = 224
STATE_WRONG_FINGERPRINT: Final = 225
STATE_MOTOR_BLOCKED: Final = 254

LOCK_MODES: Final = {
    0: "uninitialized",
    1: "pairing",
    2: "door",
    3: "continuous",
    4: "maintenance",
    5: "off_door_charging",
}

DOOR_STATES: Final = {
    0: "unavailable",
    1: "deactivated",
    2: "closed",
    3: "opened",
    4: "unknown",
    5: "calibrating",
    16: "uncalibrated",
    240: "removed",
    255: "unknown",
}
DOOR_CLOSED: Final = 2
DOOR_OPENED: Final = 3
DOOR_REMOVED: Final = 240
# Door states meaning "no door sensor"
DOOR_SENSOR_ABSENT: Final = frozenset({0})

# Log `action` codes (also used by the MQTT lockActionEvent)
LOG_ACTIONS: Final = {
    1: "unlock",
    2: "lock",
    3: "unlatch",
    4: "lock_n_go",
    5: "lock_n_go_unlatch",
    6: "full_lock",
    11: "factory_reset",
    # MQTT lockActionEvent: a press configured as "no action"
    80: "fob_no_action",
    90: "button_no_action",
    208: "door_ajar_warning",
    209: "door_status_mismatch",
    224: "doorbell_recognition",
    240: "door_opened",
    241: "door_closed",
    242: "door_sensor_jammed",
    243: "firmware_update",
    250: "door_log_enabled",
    251: "door_log_disabled",
    252: "initialization",
    253: "calibration",
    254: "log_enabled",
    255: "log_disabled",
}
# Last unlock user: unlock, unlatch, lock 'n' go with unlatch
UNLOCK_LOG_ACTIONS: Final = frozenset({1, 3, 5})
# Door opened by the latch: unlatch, lock 'n' go with unlatch
UNLATCH_LOG_ACTIONS: Final = frozenset({3, 5})
# Door locked: lock, lock 'n' go, full lock
LOCKING_LOG_ACTIONS: Final = frozenset({2, 4, 6})
LOCK_ACTIVITY_LOG_ACTIONS: Final = frozenset({1, 2, 3, 4, 5, 6})

# Event types of the activity event entity. The "no action" presses let the
# Nuki button or a fob drive Home Assistant automations.
EVENT_TYPES: Final = [
    *(LOG_ACTIONS[code] for code in sorted(LOCK_ACTIVITY_LOG_ACTIONS)),
    "button_no_action",
    "fob_no_action",
    "wrong_code",
    "wrong_fingerprint",
]

# Event types of the door sensor event entity
DOOR_EVENT_TYPES: Final = [
    "door_opened",
    "door_closed",
    "door_ajar_warning",
    "door_status_mismatch",
    "door_sensor_jammed",
]

# Log `trigger` codes (Web API)
LOG_TRIGGERS: Final = {
    0: "system",
    1: "manual",
    2: "button",
    3: "automatic",
    4: "web",
    5: "app",
    6: "auto_lock",
    7: "accessory",
    253: "keypad_error",
    254: "nuki_mode",
    255: "keypad",
}

# Every trigger name an activity can carry (Web API log + MQTT event)
ACTIVITY_TRIGGERS: Final = (
    "system",
    "manual",
    "button",
    "automatic",
    "web",
    "app",
    "auto_lock",
    "accessory",
    "keypad",
    "keypad_error",
    "nuki_mode",
    "homekit_matter",
    "mqtt",
)

# Log completion `state`
LOG_STATES: Final = {
    0: "success",
    1: "motor_blocked",
    2: "canceled",
    3: "too_recent",
    4: "busy",
    5: "low_motor_voltage",
    6: "clutch_failure",
    7: "motor_power_failure",
    8: "incomplete",
    9: "rejected",
    10: "rejected_night_mode",
    224: "invalid_code",
    225: "invalid_fingerprint",
    226: "invalid_nfc_tag",
    254: "other_error",
    255: "unknown_error",
}

# Log `source`
LOG_SOURCES: Final = {
    0: "default",
    1: "keypad_code",
    2: "fingerprint",
    3: "tap_to_unlock",
}

# Authorization `type`
AUTH_TYPES: Final = {
    0: "app",
    1: "bridge",
    2: "fob",
    3: "keypad",
    13: "keypad_code",
    14: "z_key",
    15: "virtual",
}
AUTH_TYPE_KEYPAD_CODE: Final = 13

SERVER_STATES: Final = {
    0: "ok",
    1: "unregistered",
    2: "auth_uuid_invalid",
    3: "auth_invalid",
    4: "offline",
}

KEYPAD_MOUNTING_STATES: Final = {
    0: "unknown",
    1: "mounted",
    2: "moved",
    255: "error",
}

# advancedConfig.singleButtonPressAction / doubleButtonPressAction
BUTTON_PRESS_ACTIONS: Final = {
    0: "no_action",
    1: "intelligent",
    2: "unlock",
    3: "lock",
    4: "unlatch",
    5: "lock_n_go",
    6: "show_status",
}

# config.fobAction1/2/3 for lock device types
FOB_ACTIONS: Final = {
    0: "none",
    1: "unlock",
    2: "lock",
    3: "lock_n_go",
    4: "intelligent",
}

MOTOR_SPEEDS: Final = {0: "standard", 1: "fast", 2: "slow"}
BATTERY_TYPES: Final = {0: "alkali", 1: "accumulator", 2: "lithium"}
ADVERTISING_MODES: Final = {0: "automatic", 1: "normal", 2: "slow", 3: "slowest"}
LNG_TIMEOUTS: Final = (5, 10, 15, 20, 30, 45, 60)
UNLATCH_DURATIONS: Final = (1, 3, 5, 7, 10, 15, 20, 30)

# Keypad codes: 6 digits from 1 to 9, must not start with "12"
KEYPAD_CODE_PATTERN: Final = r"^(?!12)[1-9]{6}$"

WEEKDAY_BITS: Final = {
    "mon": 64,
    "tue": 32,
    "wed": 16,
    "thu": 8,
    "fri": 4,
    "sat": 2,
    "sun": 1,
}
