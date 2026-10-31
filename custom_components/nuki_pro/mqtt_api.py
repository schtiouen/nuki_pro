"""Helpers for the Nuki MQTT API (specification v1.6, 13.2.2026).

Wi-Fi/Thread Smart Locks (3.0 Pro, 4th gen, 5th gen Go/Pro/Ultra) publish
their state on the local broker under ``nuki/<NUKI_ID>/<topic>`` (retained,
QoS 0) once MQTT is enabled in the Nuki app, and accept commands on
``nuki/<NUKI_ID>/lockAction`` (QoS 2, not retained, only when "Allow locking"
is on). There is no topic to query the state: everything is republished on
each reconnection, and a topic only exists once it has a value (no
``doorsensorState`` without a door sensor).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import LockAction


def parse_bool(payload: str) -> bool | None:
    """Parse a boolean payload ("true"/"false", "1"/"0")."""
    value = payload.strip().lower()
    if value in ("true", "1", "on"):
        return True
    if value in ("false", "0", "off"):
        return False
    return None


def parse_int(payload: str) -> int | None:
    """Parse an integer payload."""
    try:
        return int(payload.strip())
    except ValueError:
        return None


def parse_command_response(payload: str) -> int | None:
    """Parse commandResponse: 0 success, else a Bluetooth API error code.

    The specification does not say whether errors are sent in decimal or in
    hex ("0x45"), so both are accepted.
    """
    value = payload.strip()
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def parse_timestamp(payload: str) -> datetime | None:
    """Parse an ISO 8601 timestamp payload."""
    return dt_util.parse_datetime(payload.strip())


# Topic -> (NukiStatus field, parser)
STATUS_TOPICS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "state": ("state", parse_int),
    "mode": ("mode", parse_int),
    "batteryCritical": ("battery_critical", parse_bool),
    "batteryCharging": ("battery_charging", parse_bool),
    "batteryChargeState": ("battery_charge", parse_int),
    "keypadBatteryCritical": ("keypad_battery_critical", parse_bool),
    "doorsensorState": ("door_state", parse_int),
    "doorsensorBatteryCritical": ("doorsensor_battery_critical", parse_bool),
    "timestamp": ("timestamp", parse_timestamp),
}

TOPIC_CONNECTED = "connected"
TOPIC_SERVER_CONNECTED = "serverConnected"
TOPIC_DEVICE_TYPE = "deviceType"
TOPIC_NAME = "name"
TOPIC_FIRMWARE = "firmware"
TOPIC_COMMAND_RESPONSE = "commandResponse"
TOPIC_LOCK_ACTION_EVENT = "lockActionEvent"

# Topics written by Home Assistant (or the lock's own HA discovery): ignored
TOPIC_LOCK_ACTION = "lockAction"
COMMAND_TOPICS = frozenset({TOPIC_LOCK_ACTION, "lock", "unlock"})

# "Only actions 1-6 are supported" on lockAction
MQTT_LOCK_ACTIONS: dict[LockAction, int] = {
    LockAction.UNLOCK: 1,
    LockAction.LOCK: 2,
    LockAction.UNLATCH: 3,
    LockAction.LOCK_N_GO: 4,
    LockAction.LOCK_N_GO_UNLATCH: 5,
    LockAction.FULL_LOCK: 6,
}
# Recommended by Nuki for commands (needs an MQTT 5 broker connection)
COMMAND_EXPIRY_SECONDS = 10

# lockActionEvent trigger codes
MQTT_TRIGGERS: dict[int, str] = {
    0: "system",
    1: "manual",
    2: "button",
    3: "automatic",
    6: "auto_lock",
    171: "homekit_matter",
    172: "mqtt",
}
TRIGGER_BUTTON = 2

# lockActionEvent action codes for a press configured as "no action"
ACTION_FOB_NO_ACTION = 80
ACTION_BUTTON_NO_ACTION = 90

# Keypad source in the 5th field when a code id is present
KEYPAD_SOURCES: dict[int, str] = {0: "back_key", 1: "keypad_code", 2: "fingerprint"}

COMMAND_SUCCESS = 0
# Bluetooth API error codes returned in commandResponse
COMMAND_ERRORS: dict[int, str] = {
    0x10: "pairing error",
    0x11: "pairing error",
    0x12: "pairing error",
    0x13: "pairing error",
    0x20: "not authorized",
    0x21: "bad PIN",
    0x25: "authorization disabled",
    0x26: "remote access not allowed",
    0x27: "not allowed at this time",
    0x40: "auto unlock too recent",
    0x41: "position unknown",
    0x42: "motor blocked",
    0x44: "motor timeout",
    0x45: "busy",
    0x47: "not calibrated",
    0x4C: "battery voltage too low",
    0x4E: "rejected",
    0x4F: "rejected (night mode)",
    0xFF: "unknown error",
}


@dataclass(frozen=True)
class LockActionEvent:
    """Decoded ``lockActionEvent``: ``action,trigger,authId,codeId,extra``.

    The 5th field is the keypad source when a code id is present, the number
    of presses for the button and the fob, else the auto-unlock flag.
    Examples: ``3,0,54321,12345,1`` unlatch with a keypad code,
    ``4,2,0,0,0`` Lock 'n' Go with the button, ``90,2,0,0,2`` button pressed
    twice while set to "no action".
    """

    action: int
    trigger: int | None
    auth_id: int | None
    code_id: int | None
    extra: int | None

    @property
    def keypad_source(self) -> str | None:
        """keypad_code, fingerprint or back_key for keypad actions."""
        if not self.code_id:
            return None
        return KEYPAD_SOURCES.get(self.extra or 0)

    @property
    def presses(self) -> int | None:
        """Number of presses for button and fob actions."""
        if self.code_id:
            return None
        if self.trigger == TRIGGER_BUTTON or self.action in (
            ACTION_FOB_NO_ACTION,
            ACTION_BUTTON_NO_ACTION,
        ):
            return self.extra
        return None

    @property
    def auto_unlock(self) -> bool | None:
        """Auto unlock flag for app actions."""
        if self.code_id or self.presses is not None or self.extra is None:
            return None
        return bool(self.extra)


def parse_lock_action_event(payload: str) -> LockActionEvent | None:
    """Decode a lockActionEvent payload, None when malformed."""
    parts = [parse_int(part) for part in payload.split(",")]
    if not parts or parts[0] is None:
        return None
    parts += [None] * (5 - len(parts))
    return LockActionEvent(
        action=parts[0],
        trigger=parts[1],
        auth_id=parts[2] or None,
        code_id=parts[3] or None,
        extra=parts[4],
    )
