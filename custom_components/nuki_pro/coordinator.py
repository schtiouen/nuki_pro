"""Coordinator merging the Nuki Web API (cloud) and the Nuki MQTT API (local).

* Web API (required): polled for the state (when MQTT is not online), the
  settings, the authorizations and the activity log; used for setting and
  authorization changes, and for lock actions when MQTT is not available.
* MQTT API (optional): pushes the live state and lock events, and runs lock
  actions on the local network. While MQTT is online its values win.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from datetime import datetime, time as dt_time, timedelta
import inspect
import time
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    NukiWebApi,
    NukiWebApiAuthError,
    NukiWebApiError,
    NukiWebApiForbiddenError,
    NukiWebApiRateLimitError,
    smartlock_id_from_nuki_id,
)
from .const import (
    ACCESSORY_DOOR_SENSOR,
    ACCESSORY_FOB,
    ACCESSORY_KEYPAD,
    AUTH_TYPE_KEYPAD_CODE,
    AUTH_TYPES,
    AUTHS_REFRESH_EVERY,
    CONF_ACTION_TRANSPORT,
    CONF_API_TOKEN,
    CONF_AUTH_ENTITIES,
    CONF_DEVICE_TYPE,
    CONF_MQTT_TOPIC,
    CONF_NUKI_ID,
    CONF_SCAN_INTERVAL,
    CONF_SMARTLOCK_ID,
    CONF_USE_MQTT,
    DEFAULT_SCAN_INTERVAL_WEB_ONLY,
    DEFAULT_SCAN_INTERVAL_WITH_MQTT,
    DOMAIN,
    DOOR_CLOSED,
    DOOR_OPENED,
    EVENT_TYPES,
    LOCK_ACTIVITY_LOG_ACTIONS,
    LOG_ACTIONS,
    LOG_SOURCES,
    LOG_STATES,
    LOG_TRIGGERS,
    LOGGER,
    LOGS_LIMIT,
    LOGS_REFRESH_EVERY,
    MANUFACTURER,
    PRODUCT_VARIANTS,
    STATE_WRONG_CODE,
    STATE_WRONG_FINGERPRINT,
    WEB_LOCK_ACTIONS,
    WEEKDAY_BITS,
    ActionTransport,
    DeviceType,
    LockAction,
)
from .models import NukiActivity, NukiData, NukiStatus
from .mqtt_api import (
    COMMAND_ERRORS,
    COMMAND_EXPIRY_SECONDS,
    COMMAND_SUCCESS,
    COMMAND_TOPICS,
    MQTT_LOCK_ACTIONS,
    MQTT_TRIGGERS,
    STATUS_TOPICS,
    TOPIC_COMMAND_RESPONSE,
    TOPIC_CONNECTED,
    TOPIC_DEVICE_TYPE,
    TOPIC_FIRMWARE,
    TOPIC_LOCK_ACTION,
    TOPIC_LOCK_ACTION_EVENT,
    TOPIC_NAME,
    TOPIC_SERVER_CONNECTED,
    parse_bool,
    parse_command_response,
    parse_int,
    parse_lock_action_event,
)

type NukiProConfigEntry = ConfigEntry[NukiProCoordinator]

# Wait for the retained MQTT topics before creating the entities
MQTT_INITIAL_WAIT = 5
# A little over the command expiry: past it the lock drops the command
MQTT_COMMAND_TIMEOUT = 12
# Back off after HTTP 429 (limits: 100 requests/min, 1000 requests/hour)
RATE_LIMIT_RETRY_AFTER = 120
# Coalesce the burst of MQTT topics sent for one state change
PUSH_DEBOUNCE = 0.15
# The Web API shows a change once the lock confirmed it: poll a few times
REFRESH_AFTER_ACTION = (4, 12, 30)
REFRESH_AFTER_SETTING = (8, 25)
REFRESH_AFTER_AUTH_CHANGE = (10, 40)
REFRESH_AFTER_MQTT_EVENT = (8,)
# Optimistic values survive Web API polls that still show the old value
PENDING_TTL = 90
MAX_ACTIVITIES = 30
# Never sent back to the Web API in a config update
READ_ONLY_CONFIG_FIELDS = frozenset({"operationId"})

DOOR_TRANSITION_EVENTS = {DOOR_OPENED: (240, "door_opened"), DOOR_CLOSED: (241, "door_closed")}
# Events the lock never publishes over MQTT: always taken from the Web API log
LOG_ONLY_EVENTS = frozenset(
    {
        "wrong_code",
        "wrong_fingerprint",
        "door_ajar_warning",
        "door_status_mismatch",
        "door_sensor_jammed",
    }
)

ACCESSORY_MODELS = {ACCESSORY_DOOR_SENSOR: "Door Sensor", ACCESSORY_FOB: "Fob"}
# Home Assistant 2026.8+ links devices by registry id (via_device is deprecated)
VIA_DEVICE_ID_SUPPORTED = "via_device_id" in (
    DeviceInfo.__optional_keys__ | DeviceInfo.__required_keys__
)
# Home Assistant 2025.12+ accepts a retry delay on UpdateFailed
UPDATE_FAILED_RETRY_AFTER = (
    "retry_after" in inspect.signature(UpdateFailed.__init__).parameters
)


class MqttUnreachableError(Exception):
    """An MQTT command could not be published or got no answer in time."""


def _decode_version(value: Any) -> str | None:
    """Decode a Web API version integer (0x020A03 -> 2.10.3)."""
    if isinstance(value, str):
        return value or None
    if not isinstance(value, int) or value <= 0:
        return None
    return f"{(value >> 16) & 0xFF}.{(value >> 8) & 0xFF}.{value & 0xFF}"


def _nuki_datetime(value: datetime) -> str:
    """Format a datetime the way the Web API expects it (UTC, Z suffix)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _minutes(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def model_name(device_type: int, product_variant: int | None) -> str:
    """Human readable model."""
    if device_type == DeviceType.SMARTLOCK_5:
        variant = PRODUCT_VARIANTS.get(product_variant or 0)
        return f"Smart Lock {variant} (5th gen)" if variant else "Smart Lock (5th gen)"
    return {
        DeviceType.SMARTLOCK_1_2: "Smart Lock 1.0/2.0",
        DeviceType.BOX: "Box",
        DeviceType.OPENER: "Opener",
        DeviceType.SMARTDOOR: "Smart Door",
        DeviceType.SMARTLOCK_3_4: "Smart Lock 3.0/4.0",
    }.get(device_type, f"Nuki device type {device_type}")


class NukiProCoordinator(DataUpdateCoordinator[NukiData]):
    """Keep the lock data up to date from both channels."""

    config_entry: NukiProConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NukiProConfigEntry) -> None:
        """Read the config entry and prepare both channels."""
        self.nuki_id: str = entry.data[CONF_NUKI_ID]
        self.device_type: int = entry.data[CONF_DEVICE_TYPE]
        self.smartlock_id: int = entry.data.get(
            CONF_SMARTLOCK_ID
        ) or smartlock_id_from_nuki_id(self.nuki_id, self.device_type)
        token = entry.data.get(CONF_API_TOKEN)
        self.web = NukiWebApi(async_get_clientsession(hass), token) if token else None
        self.mqtt_topic: str | None = (
            entry.data.get(CONF_MQTT_TOPIC) if entry.data.get(CONF_USE_MQTT) else None
        )
        options = entry.options
        self.action_transport = ActionTransport(
            options.get(CONF_ACTION_TRANSPORT, ActionTransport.AUTO)
        )
        self.auth_entities_enabled: bool = options.get(CONF_AUTH_ENTITIES, True)
        # Without a user choice the interval follows the MQTT state: 30 s
        # while the Web API is the only live source, 300 s with MQTT online
        self._user_scan_interval = CONF_SCAN_INTERVAL in options
        scan_interval = options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_WEB_ONLY)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.nuki_id}",
            update_interval=timedelta(seconds=scan_interval) if self.web else None,
        )
        self.data = NukiData(
            nuki_id=self.nuki_id, device_type=self.device_type, name=entry.title
        )
        self.data.extra["mqtt_enabled"] = self.mqtt_topic is not None
        self.data.extra["web_enabled"] = self.web is not None
        # Device registry id of the lock, parent of the accessory devices
        self.lock_device_id: str | None = None

        self._activity_listeners: list[Callable[[NukiActivity], None]] = []
        self._mqtt_issue_id = f"mqtt_unavailable_{entry.entry_id}"
        self._unsub_mqtt: CALLBACK_TYPE | None = None
        self._unsub_broker: CALLBACK_TYPE | None = None
        self._broker_connected = False
        self._lock_connected: bool | None = None
        self._mqtt_has_state = False
        self._mqtt_first_state = asyncio.Event()
        self._command_waiters: list[asyncio.Future[int]] = []
        self._command_lock = asyncio.Lock()
        self._mqtt_expiry_supported = True
        self._settings_lock = asyncio.Lock()
        self._push_handle: asyncio.TimerHandle | None = None
        self._delayed: set[CALLBACK_TYPE] = set()
        # (section, field) -> (value, expiry) for settings sent but not yet seen
        self._pending_settings: dict[tuple[str, str], tuple[Any, float]] = {}
        # (auth id, field) -> (value, expiry)
        self._pending_auths: dict[tuple[str, str], tuple[Any, float]] = {}
        self._auths_fetched_at = 0.0
        self._auths_dirty = True
        self._logs_fetched_at = 0.0
        self._logs_dirty = True
        self._seen_log_ids: set[str] | None = None
        self._web_state_key: tuple[Any, ...] | None = None

    # Helpers -----------------------------------------------------------------

    def uid(self, key: str) -> str:
        """Unique id of an entity of this lock."""
        return f"{self.nuki_id}_{key}"

    @property
    def model(self) -> str:
        """Human readable model."""
        return model_name(self.device_type, self.data.product_variant)

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry entry of the lock."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.nuki_id)},
            manufacturer=MANUFACTURER,
            model=self.model,
            name=self.data.name or f"Nuki {self.nuki_id}",
            serial_number=self.nuki_id,
            sw_version=self.data.firmware,
            hw_version=self.data.hardware,
        )

    def accessory_device_info(self, accessory: str) -> DeviceInfo:
        """Device registry entry of an accessory paired with the lock."""
        if accessory == ACCESSORY_KEYPAD:
            model = "Keypad 2" if self.data.config.get("keypad2Paired") else "Keypad"
        else:
            model = ACCESSORY_MODELS[accessory]
        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.nuki_id}_{accessory}")},
            manufacturer=MANUFACTURER,
            model=model,
            translation_key=accessory,
            translation_placeholders={
                "lock": self.data.name or f"Nuki {self.nuki_id}"
            },
        )
        if not VIA_DEVICE_ID_SUPPORTED:
            # Home Assistant before via_device_id: link by identifiers
            info["via_device"] = (DOMAIN, self.nuki_id)  # type: ignore[typeddict-unknown-key]
        elif self.lock_device_id:
            info["via_device_id"] = self.lock_device_id
        return info

    @callback
    def async_add_activity_listener(
        self, listener: Callable[[NukiActivity], None]
    ) -> CALLBACK_TYPE:
        """Call `listener` for every new lock or door activity."""
        self._activity_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._activity_listeners.remove(listener)

        return _remove

    @callback
    def _fire_activity(self, activity: NukiActivity) -> None:
        LOGGER.debug("Activity: %s", activity)
        for listener in list(self._activity_listeners):
            listener(activity)

    @callback
    def _schedule_push(self) -> None:
        """Notify the entities soon, once per burst of MQTT messages."""
        if self._push_handle is None:
            self._push_handle = self.hass.loop.call_later(
                PUSH_DEBOUNCE, self._push_now
            )

    @callback
    def _push_now(self) -> None:
        self._push_handle = None
        self.async_update_listeners()

    @callback
    def _schedule_refreshes(self, delays: Iterable[float]) -> None:
        """Poll the Web API after a change, to pick up the confirmed values."""
        if self.web is None:
            return
        for delay in delays:
            self._schedule_refresh_in(delay)

    @callback
    def _schedule_refresh_in(self, delay: float) -> None:
        cancel: CALLBACK_TYPE

        @callback
        def _run(_now: datetime) -> None:
            self._delayed.discard(cancel)
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), f"{DOMAIN} delayed refresh"
            )

        cancel = async_call_later(self.hass, delay, _run)
        self._delayed.add(cancel)

    def _require_web(self) -> NukiWebApi:
        if self.web is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="web_api_required"
            )
        return self.web

    def _web_error(self, err: NukiWebApiError) -> HomeAssistantError:
        if isinstance(err, NukiWebApiAuthError):
            self.config_entry.async_start_reauth(self.hass)
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="web_api_error",
            translation_placeholders={"error": str(err)},
        )

    def _web_auth_failed(self, err: NukiWebApiAuthError) -> None:
        """Token rejected: ask for a new one, keep running on MQTT if it is up."""
        self.data.web_available = False
        if self.data.mqtt_online:
            LOGGER.warning(
                "Nuki Web API token rejected; MQTT keeps the lock working until "
                "a new token is entered"
            )
            self.config_entry.async_start_reauth(self.hass)
            return
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err

    @staticmethod
    def _update_failed(err: NukiWebApiError) -> UpdateFailed:
        kwargs: dict[str, Any] = {
            "translation_domain": DOMAIN,
            "translation_key": "web_api_error",
            "translation_placeholders": {"error": str(err)},
        }
        if UPDATE_FAILED_RETRY_AFTER and isinstance(err, NukiWebApiRateLimitError):
            kwargs["retry_after"] = RATE_LIMIT_RETRY_AFTER
        return UpdateFailed(**kwargs)

    async def async_shutdown(self) -> None:
        """Stop MQTT and pending timers."""
        await super().async_shutdown()
        if self._unsub_mqtt:
            self._unsub_mqtt()
            self._unsub_mqtt = None
        if self._unsub_broker:
            self._unsub_broker()
            self._unsub_broker = None
        if self._push_handle:
            self._push_handle.cancel()
            self._push_handle = None
        for cancel in self._delayed:
            cancel()
        self._delayed.clear()
        for waiter in self._command_waiters:
            waiter.cancel()

    @callback
    def _async_update_device(self) -> None:
        """Push firmware or model changes to the device registry."""
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if (DOMAIN, self.nuki_id) not in device.identifiers:
                continue
            registry.async_update_device(
                device.id,
                sw_version=self.data.firmware,
                hw_version=self.data.hardware,
                model=self.model,
            )

    # MQTT --------------------------------------------------------------------

    async def async_start_mqtt(self) -> None:
        """Subscribe to the lock topics (when MQTT is enabled)."""
        if self.mqtt_topic is None:
            return
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            if self.web is None:
                raise ConfigEntryNotReady(
                    translation_domain=DOMAIN, translation_key="mqtt_unavailable"
                )
            LOGGER.warning(
                "MQTT integration unavailable: Nuki %s runs on the Web API only",
                self.nuki_id,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._mqtt_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="mqtt_unavailable",
                translation_placeholders={"name": self.config_entry.title},
            )
            return
        ir.async_delete_issue(self.hass, DOMAIN, self._mqtt_issue_id)
        self._broker_connected = mqtt.is_connected(self.hass)
        self._unsub_broker = mqtt.async_subscribe_connection_status(
            self.hass, self._async_broker_status
        )
        self._unsub_mqtt = await mqtt.async_subscribe(
            self.hass, f"{self.mqtt_topic}/#", self._async_mqtt_message, qos=1
        )
        try:
            async with asyncio.timeout(MQTT_INITIAL_WAIT):
                await self._mqtt_first_state.wait()
        except TimeoutError:
            LOGGER.warning(
                "No MQTT state received on %s/state within %s s; check that MQTT "
                "is enabled in the Nuki app and the topic is right",
                self.mqtt_topic,
                MQTT_INITIAL_WAIT,
            )

    @callback
    def _async_broker_status(self, connected: bool) -> None:
        self._broker_connected = connected
        if not connected:
            # Retained topics are replayed after the reconnection: start over
            self._mqtt_has_state = False
            self._lock_connected = None
        self._update_mqtt_online()
        self._schedule_push()

    @callback
    def _update_mqtt_online(self) -> None:
        online = (
            self._unsub_mqtt is not None
            and self._broker_connected
            and self._lock_connected is not False
            and self._mqtt_has_state
        )
        if online == self.data.mqtt_online:
            return
        self.data.mqtt_online = online
        LOGGER.info(
            "MQTT channel for Nuki %s is %s", self.nuki_id, "up" if online else "down"
        )
        if self.web is not None and not self._user_scan_interval:
            self.update_interval = timedelta(
                seconds=DEFAULT_SCAN_INTERVAL_WITH_MQTT
                if online
                else DEFAULT_SCAN_INTERVAL_WEB_ONLY
            )
        if online:
            if not self.last_update_success:
                # MQTT alone can serve the entities again
                self.async_set_updated_data(self.data)
        else:
            # Replace the frozen MQTT values by fresh cloud ones
            self._schedule_refreshes((1,))

    @callback
    def _async_mqtt_message(self, msg: ReceiveMessage) -> None:
        assert self.mqtt_topic is not None
        topic = msg.topic[len(self.mqtt_topic) + 1 :]
        payload = (
            msg.payload.decode("utf-8", "replace")
            if isinstance(msg.payload, (bytes, bytearray))
            else str(msg.payload)
        )
        if topic in COMMAND_TOPICS or "/" in topic:
            return
        LOGGER.debug("MQTT %s = %s", topic, payload)
        data = self.data

        if field_parser := STATUS_TOPICS.get(topic):
            field, parser = field_parser
            value = parser(payload)
            if field == "state" and value in (STATE_WRONG_CODE, STATE_WRONG_FINGERPRINT):
                # Transient error state: keep the real lock state
                if not msg.retain:
                    self._fire_error_activity(value)
            else:
                if field == "door_state" and not msg.retain:
                    self._door_transition(data.mqtt_status.door_state, value)
                setattr(data.mqtt_status, field, value)
            if field == "state":
                self._mqtt_has_state = True
                self._mqtt_first_state.set()
        elif topic == TOPIC_CONNECTED:
            self._lock_connected = parse_bool(payload)
        elif topic == TOPIC_SERVER_CONNECTED:
            data.server_connected = parse_bool(payload)
        elif topic == TOPIC_LOCK_ACTION_EVENT:
            self._handle_lock_action_event(payload, historic=msg.retain)
        elif topic == TOPIC_COMMAND_RESPONSE:
            # A retained answer belongs to an older command
            if not msg.retain and (code := parse_command_response(payload)) is not None:
                for waiter in self._command_waiters:
                    if not waiter.done():
                        waiter.set_result(code)
        elif topic == TOPIC_FIRMWARE:
            if payload and payload != data.firmware:
                data.firmware = payload
                self._async_update_device()
        elif topic == TOPIC_NAME:
            if payload and not data.name:
                data.name = payload
        elif topic == TOPIC_DEVICE_TYPE:
            if (device_type := parse_int(payload)) not in (None, self.device_type):
                LOGGER.debug(
                    "MQTT device type %s differs from %s", device_type, self.device_type
                )
        else:
            data.extra.setdefault("mqtt_other", {})[topic] = payload

        self._update_mqtt_online()
        self._schedule_push()

    @callback
    def _door_transition(self, old: int | None, new: int | None) -> None:
        """Fire door_opened / door_closed when the door sensor changes."""
        if old == new or old not in DOOR_TRANSITION_EVENTS:
            return
        if (event := DOOR_TRANSITION_EVENTS.get(new)) is None:  # type: ignore[arg-type]
            return
        action, name = event
        self._fire_activity(
            NukiActivity(
                action=action, timestamp=dt_util.utcnow(), origin="mqtt", event=name
            )
        )

    @callback
    def _handle_lock_action_event(self, payload: str, historic: bool) -> None:
        if historic:
            # Retained event replayed on subscribe: not a new activity
            return
        if (event := parse_lock_action_event(payload)) is None:
            LOGGER.debug("Ignoring malformed lockActionEvent %r", payload)
            return
        trigger = (
            MQTT_TRIGGERS.get(event.trigger) if event.trigger is not None else None
        )
        activity = NukiActivity(
            action=event.action,
            timestamp=dt_util.utcnow(),
            origin="mqtt",
            event=LOG_ACTIONS.get(event.action, f"action_{event.action}"),
            trigger="keypad" if event.code_id else trigger,
            user=self.data.auth_name(event.auth_id, event.code_id),
            auth_id=event.auth_id,
            code_id=event.code_id,
            source=event.keypad_source,
            auto_unlock=event.auto_unlock,
            presses=event.presses,
        )
        if event.action not in LOCK_ACTIVITY_LOG_ACTIONS:
            # Button or fob press set to "no action": an event only
            if activity.event in EVENT_TYPES:
                self._fire_activity(activity)
            else:
                LOGGER.debug("Ignoring lockActionEvent action %s", event.action)
            return
        self.data.mqtt_activities.insert(0, activity)
        del self.data.mqtt_activities[MAX_ACTIVITIES:]
        self._fire_activity(activity)
        self._logs_dirty = True
        self._schedule_refreshes(REFRESH_AFTER_MQTT_EVENT)

    @callback
    def _fire_error_activity(self, state: int) -> None:
        """A wrong keypad code or fingerprint was presented (MQTT state)."""
        self._fire_activity(
            NukiActivity(
                action=0,
                timestamp=dt_util.utcnow(),
                origin="mqtt",
                event="wrong_fingerprint"
                if state == STATE_WRONG_FINGERPRINT
                else "wrong_code",
            )
        )

    async def _async_publish_command(self, payload: str) -> None:
        """Publish on lockAction.

        Nuki recommends QoS 2 with a 10 s message expiry, which needs an MQTT 5
        broker connection (and Home Assistant 2026.6+). Without expiry the
        command goes out with QoS 0: the broker never keeps it for a lock that
        just dropped off, so a command that timed out cannot run minutes later.
        """
        assert self.mqtt_topic is not None
        topic = f"{self.mqtt_topic}/{TOPIC_LOCK_ACTION}"
        if self._mqtt_expiry_supported:
            try:
                await mqtt.async_publish(
                    self.hass,
                    topic,
                    payload,
                    qos=2,
                    retain=False,
                    message_expiry_interval=COMMAND_EXPIRY_SECONDS,
                )
            except (ServiceValidationError, TypeError):
                # MQTT 3.1.1 broker connection, or Home Assistant before 2026.6
                self._mqtt_expiry_supported = False
            else:
                return
        await mqtt.async_publish(self.hass, topic, payload, qos=0, retain=False)

    async def _async_mqtt_action(self, action: LockAction) -> None:
        """Send a command and wait for commandResponse.

        The lock handles one command at a time and its answers carry no id,
        so commands are sent one after the other.
        """
        async with self._command_lock:
            waiter: asyncio.Future[int] = self.hass.loop.create_future()
            self._command_waiters.append(waiter)
            try:
                await self._async_publish_command(str(MQTT_LOCK_ACTIONS[action]))
                async with asyncio.timeout(MQTT_COMMAND_TIMEOUT):
                    code = await waiter
            except (TimeoutError, HomeAssistantError) as err:
                raise MqttUnreachableError from err
            finally:
                self._command_waiters.remove(waiter)
        if code != COMMAND_SUCCESS:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="mqtt_command_failed",
                translation_placeholders={
                    "code": f"0x{code:02X}",
                    "reason": COMMAND_ERRORS.get(code, "?"),
                },
            )

    # Web API polling ---------------------------------------------------------

    async def _async_update_data(self) -> NukiData:
        """Poll the Web API (state, settings, then users and log when needed)."""
        if self.web is None:
            return self.data
        try:
            smartlock = await self.web.async_get_smartlock(self.smartlock_id)
        except NukiWebApiAuthError as err:
            self._web_auth_failed(err)
            return self.data
        except NukiWebApiError as err:
            self.data.web_available = False
            if self.data.mqtt_online:
                LOGGER.warning("Nuki Web API unavailable, MQTT still up: %s", err)
                return self.data
            raise self._update_failed(err) from err

        self._apply_smartlock(smartlock)
        now = time.monotonic()
        if self.data.auths_supported and (
            self._auths_dirty or now - self._auths_fetched_at > AUTHS_REFRESH_EVERY
        ):
            await self._async_refresh_auths()
        # Without MQTT the log is the only source of events: read it each poll
        if self.data.logs_supported and (
            self._logs_dirty
            or not self.data.mqtt_online
            or now - self._logs_fetched_at > LOGS_REFRESH_EVERY
        ):
            await self._async_refresh_logs()
        return self.data

    def _apply_smartlock(self, smartlock: dict[str, Any]) -> None:
        data = self.data
        state = smartlock.get("state") or {}
        data.smartlock = smartlock
        data.web_available = True
        data.web_status = NukiStatus(
            state=None
            if state.get("state") in (STATE_WRONG_CODE, STATE_WRONG_FINGERPRINT)
            else state.get("state"),
            mode=state.get("mode"),
            trigger=state.get("trigger"),
            last_action=state.get("lastAction"),
            battery_critical=state.get("batteryCritical"),
            battery_charging=state.get("batteryCharging"),
            battery_charge=state.get("batteryCharge"),
            keypad_battery_critical=state.get("keypadBatteryCritical"),
            doorsensor_battery_critical=state.get("doorsensorBatteryCritical"),
            door_state=state.get("doorState"),
            keypad_mounting_state=state.get("keypadMountingState"),
            night_mode=state.get("nightMode"),
            timestamp=dt_util.parse_datetime(smartlock.get("updateDate") or ""),
        )
        data.name = smartlock.get("name") or data.name
        data.config = self._with_pending("config", smartlock.get("config") or {})
        data.advanced_config = self._with_pending(
            "advanced_config", smartlock.get("advancedConfig") or {}
        )
        data.product_variant = data.config.get("productVariant")
        data.server_state = smartlock.get("serverState")
        if not data.mqtt_online or data.server_connected is None:
            data.server_connected = data.server_state == 0
        firmware = data.firmware if self.mqtt_topic and data.firmware else None
        firmware = firmware or _decode_version(smartlock.get("firmwareVersion"))
        hardware = _decode_version(smartlock.get("hardwareVersion"))
        if (firmware, hardware) != (data.firmware, data.hardware):
            data.firmware, data.hardware = firmware, hardware
            self._async_update_device()
        state_key = (
            state.get("state"),
            state.get("lastAction"),
            state.get("trigger"),
            state.get("doorState"),
        )
        if self._web_state_key is not None and state_key != self._web_state_key:
            self._logs_dirty = True
        self._web_state_key = state_key

    def _with_pending(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        """Overlay settings sent recently that the server does not show yet."""
        values = dict(values)
        now = time.monotonic()
        for (pending_section, field), (value, expiry) in list(
            self._pending_settings.items()
        ):
            if pending_section != section:
                continue
            if expiry < now or values.get(field) == value:
                del self._pending_settings[(pending_section, field)]
            else:
                values[field] = value
        return values

    async def _async_refresh_auths(self) -> None:
        assert self.web is not None
        try:
            auths = await self.web.async_get_auths(self.smartlock_id)
        except NukiWebApiForbiddenError:
            LOGGER.warning(
                "The API token cannot read authorizations (scope smartlock.auth)"
            )
            self.data.auths_supported = False
            return
        except NukiWebApiAuthError as err:
            self._web_auth_failed(err)
            return
        except NukiWebApiError as err:
            LOGGER.debug("Could not refresh authorizations: %s", err)
            return
        now = time.monotonic()
        result: dict[str, dict[str, Any]] = {}
        for auth in auths:
            if not (auth_id := auth.get("id")):
                continue
            auth = dict(auth)
            for (pending_id, field), (value, expiry) in list(
                self._pending_auths.items()
            ):
                if pending_id != auth_id:
                    continue
                if expiry < now or auth.get(field) == value:
                    del self._pending_auths[(pending_id, field)]
                else:
                    auth[field] = value
            result[auth_id] = auth
        self.data.auths = result
        self.data.extra["auths_fetched"] = True
        self._auths_fetched_at = now
        self._auths_dirty = False
        # Names may now be known for past MQTT events
        for activity in self.data.mqtt_activities:
            if activity.user is None:
                activity.user = self.data.auth_name(activity.auth_id, activity.code_id)

    async def _async_refresh_logs(self) -> None:
        assert self.web is not None
        try:
            logs = await self.web.async_get_logs(self.smartlock_id, LOGS_LIMIT)
        except NukiWebApiForbiddenError:
            LOGGER.warning("The API token cannot read the log (scope smartlock.log)")
            self.data.logs_supported = False
            return
        except NukiWebApiAuthError as err:
            self._web_auth_failed(err)
            return
        except NukiWebApiError as err:
            LOGGER.debug("Could not refresh the log: %s", err)
            return
        self._logs_fetched_at = time.monotonic()
        self._logs_dirty = False
        self.data.logs = logs

        parsed = [
            activity
            for entry in logs
            if (activity := self._activity_from_log(entry)) is not None
        ]
        self.data.web_activities = [
            activity
            for activity in parsed
            if activity.action in LOCK_ACTIVITY_LOG_ACTIONS
            and activity.completion in (None, "success")
        ][:MAX_ACTIVITIES]

        ids = {activity.log_id for activity in parsed if activity.log_id}
        if self._seen_log_ids is None:
            # First fetch: history only, no events
            self._seen_log_ids = ids
            return
        new = [a for a in parsed if a.log_id and a.log_id not in self._seen_log_ids]
        self._seen_log_ids |= ids
        for activity in sorted(new, key=lambda a: a.timestamp):
            if activity.event in LOG_ONLY_EVENTS:
                self._fire_activity(activity)
            elif self.data.mqtt_online:
                # MQTT already fired lock actions and door changes live
                continue
            elif activity.event in ("door_opened", "door_closed") or (
                activity.action in LOCK_ACTIVITY_LOG_ACTIONS
                and activity.completion in (None, "success")
            ):
                self._fire_activity(activity)

    @staticmethod
    def _activity_from_log(entry: dict[str, Any]) -> NukiActivity | None:
        timestamp = dt_util.parse_datetime(entry.get("date") or "")
        if timestamp is None or (action := entry.get("action")) is None:
            return None
        state = entry.get("state")
        trigger = entry.get("trigger")
        event = LOG_ACTIONS.get(action, f"action_{action}")
        if state == 225:
            event = "wrong_fingerprint"
        elif state in (224, 226) or trigger == 253:
            event = "wrong_code"
        return NukiActivity(
            action=action,
            timestamp=timestamp,
            origin="web",
            event=event,
            trigger=LOG_TRIGGERS.get(trigger) if trigger is not None else None,
            user=entry.get("name") or None,
            source=LOG_SOURCES.get(entry.get("source") or 0),
            completion=LOG_STATES.get(state) if state is not None else None,
            auto_unlock=entry.get("autoUnlock"),
            log_id=entry.get("id"),
        )

    async def async_full_refresh(self) -> None:
        """Refresh everything now (state, settings, users, log).

        Users changed in the app reach Nuki Web only at its daily sync, so a
        sync is requested first, then read again a little later.
        """
        if self.web is None:
            return
        self._auths_dirty = True
        self._logs_dirty = True
        try:
            await self.web.async_sync(self.smartlock_id)
        except NukiWebApiError as err:
            LOGGER.debug("Sync request failed: %s", err)
        else:
            self._schedule_refreshes(REFRESH_AFTER_AUTH_CHANGE)
        await self.async_refresh()

    # Actions -----------------------------------------------------------------

    async def async_lock_action(
        self, action: LockAction, transport: ActionTransport | None = None
    ) -> None:
        """Run a lock action, locally over MQTT when possible."""
        transport = transport or self.action_transport
        if transport is ActionTransport.MQTT and not self.data.mqtt_online:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="mqtt_offline"
            )
        if transport is not ActionTransport.WEB and self.data.mqtt_online:
            try:
                await self._async_mqtt_action(action)
            except MqttUnreachableError as err:
                # No answer: "Allow locking" may be off in the Nuki app, or the
                # Wi-Fi link dropped. The command cannot run late (expiry or
                # QoS 0), so the cloud can take over.
                if transport is ActionTransport.MQTT or self.web is None:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="mqtt_no_response"
                    ) from err
                LOGGER.warning(
                    "No MQTT answer to %s from Nuki %s, using the Web API",
                    action,
                    self.nuki_id,
                )
            else:
                return
        web = self._require_web()
        code, option = WEB_LOCK_ACTIONS[action]
        try:
            await web.async_lock_action(self.smartlock_id, code, option)
        except NukiWebApiError as err:
            raise self._web_error(err) from err
        self._logs_dirty = True
        self._schedule_refreshes(REFRESH_AFTER_ACTION)

    async def async_set_setting(self, section: str, field: str, value: Any) -> None:
        """Change one field of the config or advanced config.

        The Web API needs the whole object: changes are serialized so that two
        settings changed together do not overwrite each other.
        """
        web = self._require_web()
        async with self._settings_lock:
            current: dict[str, Any] = getattr(self.data, section)
            if not current:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="settings_unknown"
                )
            payload = {
                key: val
                for key, val in {**current, field: value}.items()
                if key not in READ_ONLY_CONFIG_FIELDS
            }
            try:
                if section == "config":
                    await web.async_update_config(self.smartlock_id, payload)
                else:
                    await web.async_update_advanced_config(self.smartlock_id, payload)
            except NukiWebApiError as err:
                raise self._web_error(err) from err
            self._pending_settings[(section, field)] = (
                value,
                time.monotonic() + PENDING_TTL,
            )
            # A poll may have replaced the dict meanwhile: update the live one
            getattr(self.data, section)[field] = value
        self.async_update_listeners()
        self._schedule_refreshes(REFRESH_AFTER_SETTING)

    # Authorizations ----------------------------------------------------------

    def _resolve_auth(self, reference: str) -> tuple[str, dict[str, Any]]:
        """Find an authorization by Web API id or by (unique) name."""
        if reference in self.data.auths:
            return reference, self.data.auths[reference]
        matches = [
            (auth_id, auth)
            for auth_id, auth in self.data.auths.items()
            if (auth.get("name") or "").casefold() == reference.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="authorization_ambiguous"
            if matches
            else "authorization_not_found",
            translation_placeholders={"authorization": reference},
        )

    @staticmethod
    def _access_payload(values: dict[str, Any]) -> dict[str, Any]:
        """Translate service fields into Web API authorization fields."""
        payload: dict[str, Any] = {}
        if (value := values.get("allowed_from_date")) is not None:
            payload["allowedFromDate"] = _nuki_datetime(value)
        if (value := values.get("allowed_until_date")) is not None:
            payload["allowedUntilDate"] = _nuki_datetime(value)
        if (days := values.get("allowed_weekdays")) is not None:
            payload["allowedWeekDays"] = sum(WEEKDAY_BITS[day] for day in set(days))
        if (value := values.get("allowed_from_time")) is not None:
            payload["allowedFromTime"] = _minutes(value)
        if (value := values.get("allowed_until_time")) is not None:
            payload["allowedUntilTime"] = _minutes(value)
        if (value := values.get("remote_allowed")) is not None:
            payload["remoteAllowed"] = value
        if (value := values.get("enabled")) is not None:
            payload["enabled"] = value
        return payload

    async def async_update_auth(self, auth_id: str, changes: dict[str, Any]) -> None:
        """Change Web API fields of one authorization."""
        web = self._require_web()
        auth = self.data.auths.get(auth_id, {})
        payload = {"name": auth.get("name"), **changes}
        try:
            await web.async_update_auth(self.smartlock_id, auth_id, payload)
        except NukiWebApiError as err:
            raise self._web_error(err) from err
        expiry = time.monotonic() + PENDING_TTL
        for field, value in changes.items():
            if field != "code":
                self._pending_auths[(auth_id, field)] = (value, expiry)
                auth[field] = value
        self._auths_dirty = True
        self.async_update_listeners()
        self._schedule_refreshes(REFRESH_AFTER_AUTH_CHANGE)

    async def async_create_keypad_code(
        self, name: str, code: str, **values: Any
    ) -> None:
        """Create a keypad code."""
        web = self._require_web()
        payload = {
            "name": name,
            "type": AUTH_TYPE_KEYPAD_CODE,
            "code": int(code),
            "remoteAllowed": False,
            **self._access_payload(values),
        }
        try:
            await web.async_create_auth(self.smartlock_id, payload)
        except NukiWebApiError as err:
            raise self._web_error(err) from err
        self._auths_dirty = True
        self._schedule_refreshes(REFRESH_AFTER_AUTH_CHANGE)

    async def async_update_authorization(
        self, authorization: str, **values: Any
    ) -> None:
        """Rename, enable/disable, restrict or change the code of an authorization."""
        auth_id, auth = self._resolve_auth(authorization)
        changes = self._access_payload(values)
        if (name := values.get("name")) is not None:
            changes["name"] = name
        if (code := values.get("code")) is not None:
            if auth.get("type") != AUTH_TYPE_KEYPAD_CODE:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="code_not_keypad"
                )
            changes["code"] = int(code)
        if not changes:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_update"
            )
        await self.async_update_auth(auth_id, changes)

    async def async_delete_authorization(self, authorization: str) -> None:
        """Delete an authorization."""
        web = self._require_web()
        auth_id, _ = self._resolve_auth(authorization)
        try:
            await web.async_delete_auth(self.smartlock_id, auth_id)
        except NukiWebApiError as err:
            raise self._web_error(err) from err
        self._auths_dirty = True
        self._schedule_refreshes(REFRESH_AFTER_AUTH_CHANGE)

    def authorizations_summary(self) -> list[dict[str, Any]]:
        """Authorizations for a service response, keypad codes removed."""
        self._require_web()
        return [
            {
                "id": auth_id,
                "name": auth.get("name"),
                "type": AUTH_TYPES.get(auth.get("type", -1), auth.get("type")),
                "enabled": auth.get("enabled"),
                "remote_allowed": auth.get("remoteAllowed"),
                "lock_count": auth.get("lockCount"),
                "last_active_date": auth.get("lastActiveDate"),
                "allowed_from_date": auth.get("allowedFromDate"),
                "allowed_until_date": auth.get("allowedUntilDate"),
                "allowed_weekdays": auth.get("allowedWeekDays"),
                "allowed_from_time": auth.get("allowedFromTime"),
                "allowed_until_time": auth.get("allowedUntilTime"),
            }
            for auth_id, auth in self.data.auths.items()
        ]

    async def async_fetch_logs(self, limit: int) -> list[dict[str, Any]]:
        """Latest log entries, decoded, for a service response."""
        web = self._require_web()
        try:
            logs = await web.async_get_logs(self.smartlock_id, limit)
        except NukiWebApiError as err:
            raise self._web_error(err) from err
        result = []
        for entry in logs:
            activity = self._activity_from_log(entry)
            if activity is None:
                continue
            result.append(
                {
                    "date": activity.timestamp.isoformat(),
                    "name": activity.user,
                    "action": activity.event,
                    "trigger": activity.trigger,
                    "source": activity.source,
                    "completion": activity.completion,
                    "auto_unlock": activity.auto_unlock,
                }
            )
        return result
