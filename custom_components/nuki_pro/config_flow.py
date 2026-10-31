"""Config flow for the Nuki Pro integration.

1. Nuki Web API token (required): lists the locks of the account.
2. Lock choice, when the account has several.
3. MQTT (optional, only when the MQTT integration is set up): local push
   and local lock actions. Without it everything goes through the Web API.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .api import (
    NukiWebApi,
    NukiWebApiAuthError,
    NukiWebApiError,
    NukiWebApiForbiddenError,
    nuki_id_from_smartlock_id,
)
from .const import (
    CONF_ACTION_TRANSPORT,
    CONF_API_TOKEN,
    CONF_AUTH_ENTITIES,
    CONF_DEVICE_TYPE,
    CONF_MQTT_TOPIC,
    CONF_NUKI_ID,
    CONF_SCAN_INTERVAL,
    CONF_SMARTLOCK_ID,
    CONF_USE_MQTT,
    DEFAULT_MQTT_BASE_TOPIC,
    DOMAIN,
    LOCK_DEVICE_TYPES,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    ActionTransport,
)
from .coordinator import NukiProConfigEntry, model_name

TOKEN_URL = "https://web.nuki.io"
MQTT_PROBE_SECONDS = 4
NUKI_ID_RE = re.compile(r"^[0-9A-Fa-f]{8}$")

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _async_fetch_locks(hass: Any, token: str) -> dict[str, dict[str, Any]]:
    """Return the locks of the account, keyed by Nuki ID."""
    api = NukiWebApi(async_get_clientsession(hass), token)
    return {
        nuki_id_from_smartlock_id(smartlock["smartlockId"]): smartlock
        for smartlock in await api.async_get_smartlocks()
        if smartlock.get("smartlockId") and smartlock.get("type") in LOCK_DEVICE_TYPES
    }


async def _async_validate_token(
    hass: Any, token: str, errors: dict[str, str]
) -> dict[str, dict[str, Any]] | None:
    """Fetch the locks, filling `errors` on failure."""
    try:
        locks = await _async_fetch_locks(hass, token)
    except NukiWebApiAuthError:
        errors["base"] = "invalid_auth"
    except NukiWebApiForbiddenError:
        errors["base"] = "missing_scope"
    except NukiWebApiError as err:
        LOGGER.debug("Nuki Web API error: %s", err)
        errors["base"] = "cannot_connect"
    except Exception:
        LOGGER.exception("Unexpected error while validating the Nuki token")
        errors["base"] = "unknown"
    else:
        if locks:
            return locks
        errors["base"] = "no_devices"
    return None


async def _async_mqtt_ready(hass: Any) -> bool:
    """True when the MQTT integration is set up."""
    if "mqtt" not in hass.config.components:
        return False
    return await mqtt.async_wait_for_mqtt_client(hass)


async def _async_find_mqtt_topic(hass: Any, nuki_id: str) -> str | None:
    """Look for the retained ``nuki/<id>/deviceType`` topic of the lock."""
    found = asyncio.Event()
    topic: list[str] = []

    @callback
    def _message(msg: mqtt.ReceiveMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) == 3 and parts[1].upper() == nuki_id.upper():
            topic.append(f"{parts[0]}/{parts[1]}")
            found.set()

    unsubscribe = await mqtt.async_subscribe(
        hass, f"{DEFAULT_MQTT_BASE_TOPIC}/+/deviceType", _message
    )
    try:
        async with asyncio.timeout(MQTT_PROBE_SECONDS):
            await found.wait()
    except TimeoutError:
        return None
    finally:
        unsubscribe()
    return topic[0]


async def _async_probe_mqtt_topic(hass: Any, topic: str) -> bool:
    """True when the lock publishes something under `topic`."""
    received = asyncio.Event()

    @callback
    def _message(msg: mqtt.ReceiveMessage) -> None:
        received.set()

    unsubscribe = await mqtt.async_subscribe(hass, f"{topic}/#", _message)
    try:
        async with asyncio.timeout(MQTT_PROBE_SECONDS):
            await received.wait()
    except TimeoutError:
        return False
    finally:
        unsubscribe()
    return True


class NukiProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Nuki lock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._token: str | None = None
        self._locks: dict[str, dict[str, Any]] = {}
        self._nuki_id: str | None = None
        self._discovered_topic: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: NukiProConfigEntry) -> NukiProOptionsFlow:
        """Options of an entry."""
        return NukiProOptionsFlow()

    # Discovery ---------------------------------------------------------------

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """A lock announced itself on ``nuki/<id>/deviceType``."""
        parts = discovery_info.topic.split("/")
        if len(parts) != 3 or not NUKI_ID_RE.match(parts[1]):
            return self.async_abort(reason="invalid_discovery_info")
        payload = discovery_info.payload
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", "replace")
        try:
            device_type = int(str(payload).strip())
        except ValueError:
            return self.async_abort(reason="invalid_discovery_info")
        if device_type not in LOCK_DEVICE_TYPES:
            # An Opener or another Nuki device sharing the broker
            return self.async_abort(reason="not_supported")
        nuki_id = parts[1].upper()
        await self.async_set_unique_id(nuki_id)
        self._abort_if_unique_id_configured()
        self._nuki_id = nuki_id
        self._discovered_topic = f"{parts[0]}/{parts[1]}"
        self.context["title_placeholders"] = {"name": f"Nuki {nuki_id}"}
        return await self.async_step_user()

    # User steps --------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Nuki Web API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            if (locks := await _async_validate_token(self.hass, token, errors)) is not None:
                self._token = token
                self._locks = locks
                if self._nuki_id is not None:
                    if self._nuki_id in locks:
                        return await self._async_lock_chosen(self._nuki_id)
                    errors["base"] = "lock_not_in_account"
                elif len(locks) == 1:
                    return await self._async_lock_chosen(next(iter(locks)))
                else:
                    return await self.async_step_select_lock()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
            description_placeholders={"token_url": TOKEN_URL},
        )

    async def async_step_select_lock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one lock of the account."""
        if user_input is not None:
            return await self._async_lock_chosen(user_input[CONF_NUKI_ID])
        options = [
            SelectOptionDict(
                value=nuki_id,
                label=f"{lock.get('name') or nuki_id} – "
                f"{model_name(lock['type'], (lock.get('config') or {}).get('productVariant'))}",
            )
            for nuki_id, lock in self._locks.items()
        ]
        return self.async_show_form(
            step_id="select_lock",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NUKI_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def _async_lock_chosen(self, nuki_id: str) -> ConfigFlowResult:
        await self.async_set_unique_id(nuki_id)
        self._abort_if_unique_id_configured()
        self._nuki_id = nuki_id
        if await _async_mqtt_ready(self.hass):
            return await self.async_step_mqtt_setup()
        return self._async_create(use_mqtt=False, topic=None)

    async def async_step_mqtt_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally use the local MQTT API of the lock."""
        assert self._nuki_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_USE_MQTT]:
                return self._async_create(use_mqtt=False, topic=None)
            topic = user_input[CONF_MQTT_TOPIC].strip().rstrip("/")
            if await _async_probe_mqtt_topic(self.hass, topic):
                return self._async_create(use_mqtt=True, topic=topic)
            errors["base"] = "mqtt_no_data"
        if self._discovered_topic is None:
            self._discovered_topic = await _async_find_mqtt_topic(
                self.hass, self._nuki_id
            )
        detected = self._discovered_topic is not None
        return self.async_show_form(
            step_id="mqtt_setup",
            data_schema=vol.Schema(
                {
                    # Web API only by default
                    vol.Required(CONF_USE_MQTT, default=False): BooleanSelector(),
                    vol.Required(
                        CONF_MQTT_TOPIC,
                        default=self._discovered_topic
                        or f"{DEFAULT_MQTT_BASE_TOPIC}/{self._nuki_id}",
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "detected": "✅" if detected else "❌",
                "nuki_id": self._nuki_id,
            },
        )

    @callback
    def _async_create(self, use_mqtt: bool, topic: str | None) -> ConfigFlowResult:
        assert self._nuki_id is not None and self._token is not None
        lock = self._locks[self._nuki_id]
        return self.async_create_entry(
            title=lock.get("name") or f"Nuki {self._nuki_id}",
            data={
                CONF_NUKI_ID: self._nuki_id,
                CONF_DEVICE_TYPE: lock["type"],
                CONF_SMARTLOCK_ID: lock["smartlockId"],
                CONF_API_TOKEN: self._token,
                CONF_USE_MQTT: use_mqtt,
                CONF_MQTT_TOPIC: topic,
            },
        )

    # Reauth / reconfigure ----------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The token was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            locks = await _async_validate_token(self.hass, token, errors)
            if locks is not None:
                if entry.data[CONF_NUKI_ID] in locks:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_API_TOKEN: token}
                    )
                errors["base"] = "lock_not_in_account"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
            description_placeholders={"token_url": TOKEN_URL, "name": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the token or the MQTT settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_API_TOKEN) or "").strip() or entry.data[
                CONF_API_TOKEN
            ]
            use_mqtt = user_input[CONF_USE_MQTT]
            topic = (user_input.get(CONF_MQTT_TOPIC) or "").strip().rstrip("/") or None
            locks = await _async_validate_token(self.hass, token, errors)
            if locks is not None and entry.data[CONF_NUKI_ID] not in locks:
                errors["base"] = "lock_not_in_account"
            if not errors and use_mqtt:
                if not await _async_mqtt_ready(self.hass):
                    errors["base"] = "mqtt_not_configured"
                elif not topic or not await _async_probe_mqtt_topic(self.hass, topic):
                    errors["base"] = "mqtt_no_data"
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_API_TOKEN: token,
                        CONF_USE_MQTT: use_mqtt,
                        CONF_MQTT_TOPIC: topic if use_mqtt else entry.data.get(CONF_MQTT_TOPIC),
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_API_TOKEN): TOKEN_SELECTOR,
                    vol.Required(
                        CONF_USE_MQTT, default=entry.data.get(CONF_USE_MQTT, False)
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_MQTT_TOPIC,
                        default=entry.data.get(CONF_MQTT_TOPIC)
                        or f"{DEFAULT_MQTT_BASE_TOPIC}/{entry.data[CONF_NUKI_ID]}",
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )


class NukiProOptionsFlow(OptionsFlowWithReload):
    """Polling interval, action channel and per-user switches."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            # Left empty: automatic interval (30 s, or 300 s with MQTT online)
            if user_input.get(CONF_SCAN_INTERVAL) is not None:
                user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data=user_input)
        defaults = {
            CONF_ACTION_TRANSPORT: ActionTransport.AUTO.value,
            CONF_AUTH_ENTITIES: True,
            **self.config_entry.options,
        }
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(CONF_ACTION_TRANSPORT): SelectSelector(
                    SelectSelectorConfig(
                        options=[transport.value for transport in ActionTransport],
                        translation_key=CONF_ACTION_TRANSPORT,
                    )
                ),
                vol.Required(CONF_AUTH_ENTITIES): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
        )
