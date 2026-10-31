"""Data containers for the Nuki Pro integration."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Literal

# An MQTT event and a Web API log line closer than this describe one action
ACTIVITY_MATCH_WINDOW = 120


@dataclass
class NukiStatus:
    """Live status of the lock, as reported by one channel (MQTT or Web API)."""

    state: int | None = None
    mode: int | None = None
    trigger: int | None = None
    last_action: int | None = None
    battery_critical: bool | None = None
    battery_charging: bool | None = None
    battery_charge: int | None = None
    keypad_battery_critical: bool | None = None
    doorsensor_battery_critical: bool | None = None
    door_state: int | None = None
    keypad_mounting_state: int | None = None
    night_mode: bool | None = None
    timestamp: datetime | None = None

    def merged_over(self, fallback: NukiStatus) -> NukiStatus:
        """Return a copy where missing values are taken from `fallback`."""
        return NukiStatus(
            **{
                f.name: (
                    value
                    if (value := getattr(self, f.name)) is not None
                    else getattr(fallback, f.name)
                )
                for f in fields(self)
            }
        )


@dataclass
class NukiActivity:
    """One lock activity, from the MQTT lockActionEvent or a Web API log."""

    action: int
    timestamp: datetime
    origin: Literal["mqtt", "web"]
    # Event type fired by the event entity (action name, or wrong_code...)
    event: str = ""
    trigger: str | None = None
    user: str | None = None
    auth_id: int | None = None
    code_id: int | None = None
    source: str | None = None
    completion: str | None = None
    auto_unlock: bool | None = None
    presses: int | None = None
    log_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the activity as event / attribute data."""
        return {
            "action": self.event,
            "trigger": self.trigger,
            "user": self.user,
            "auth_id": self.auth_id,
            "code_id": self.code_id,
            "source": self.source,
            "completion": self.completion,
            "auto_unlock": self.auto_unlock,
            "presses": self.presses,
            "timestamp": self.timestamp.isoformat(),
            "origin": self.origin,
        }


@dataclass
class NukiData:
    """Everything the entities need, shared through the coordinator."""

    nuki_id: str
    device_type: int
    name: str | None = None
    firmware: str | None = None
    hardware: str | None = None
    product_variant: int | None = None
    mqtt_status: NukiStatus = field(default_factory=NukiStatus)
    web_status: NukiStatus = field(default_factory=NukiStatus)
    # True when the MQTT channel is subscribed and the lock reports `connected`
    mqtt_online: bool = False
    # Lock connected to the Nuki servers (MQTT serverConnected / Web serverState)
    server_connected: bool | None = None
    server_state: int | None = None
    web_available: bool = False
    smartlock: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    advanced_config: dict[str, Any] = field(default_factory=dict)
    auths: dict[str, dict[str, Any]] = field(default_factory=dict)
    auths_supported: bool = True
    logs: list[dict[str, Any]] = field(default_factory=list)
    logs_supported: bool = True
    # Recent lock activities, newest first, per channel
    mqtt_activities: list[NukiActivity] = field(default_factory=list)
    web_activities: list[NukiActivity] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> NukiStatus:
        """Merged status: MQTT wins while it is online, the Web API fills gaps."""
        if self.mqtt_online:
            return self.mqtt_status.merged_over(self.web_status)
        return self.web_status.merged_over(self.mqtt_status)

    @property
    def activities(self) -> list[NukiActivity]:
        """Lock activities from both channels, newest first, without duplicates.

        An MQTT event and the Web API log line describing the same action are
        merged one to one (closest in time); the log line wins because it
        carries the user name. Two people acting within the window stay two.
        """
        pairs = sorted(
            (abs((logged.timestamp - event.timestamp).total_seconds()), m, w)
            for m, event in enumerate(self.mqtt_activities)
            for w, logged in enumerate(self.web_activities)
            if logged.action == event.action
        )
        matched_mqtt: set[int] = set()
        matched_web: set[int] = set()
        for delta, m, w in pairs:
            if delta >= ACTIVITY_MATCH_WINDOW:
                break
            if m in matched_mqtt or w in matched_web:
                continue
            matched_mqtt.add(m)
            matched_web.add(w)
        merged = list(self.web_activities)
        merged.extend(
            event
            for m, event in enumerate(self.mqtt_activities)
            if m not in matched_mqtt
        )
        merged.sort(key=lambda activity: activity.timestamp, reverse=True)
        return merged

    def last_activity(
        self, actions: frozenset[int] | None = None
    ) -> NukiActivity | None:
        """Most recent activity, optionally restricted to some action codes."""
        return next(
            (
                activity
                for activity in self.activities
                if actions is None or activity.action in actions
            ),
            None,
        )

    @property
    def has_door_sensor(self) -> bool:
        """Door sensor paired (integrated or accessory)."""
        door_state = self.status.door_state
        return door_state is not None and door_state != 0

    @property
    def has_keypad(self) -> bool:
        """A Keypad (1 or 2) is paired."""
        if "keypadPaired" in self.config or "keypad2Paired" in self.config:
            return bool(
                self.config.get("keypadPaired") or self.config.get("keypad2Paired")
            )
        return self.mqtt_status.keypad_battery_critical is not None

    @property
    def has_fob(self) -> bool:
        """A Nuki Fob is paired."""
        return bool(self.config.get("fobPaired"))

    def auth_name(self, auth_id: int | None, code_id: int | None) -> str | None:
        """Resolve a device-level authorization (or keypad code) id to a name."""
        if code_id:
            for auth in self.auths.values():
                if auth.get("type") == 13 and auth.get("authId") == code_id:
                    return auth.get("name")
        if auth_id:
            for auth in self.auths.values():
                if auth.get("type") != 13 and auth.get("authId") == auth_id:
                    return auth.get("name")
        return None
