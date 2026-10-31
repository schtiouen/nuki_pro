"""Lock entity for the Nuki Pro integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    KEYPAD_CODE_PATTERN,
    STATE_LOCKED,
    STATE_LOCKING,
    STATE_MOTOR_BLOCKED,
    STATE_UNLATCHED,
    STATE_UNLATCHING,
    STATE_UNLOCKED,
    STATE_UNLOCKED_LNG,
    STATE_UNLOCKING,
    WEEKDAY_BITS,
    ActionTransport,
    LockAction,
)
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity

PARALLEL_UPDATES = 1

SERVICE_LOCK_ACTION = "lock_action"
SERVICE_CREATE_KEYPAD_CODE = "create_keypad_code"
SERVICE_UPDATE_AUTHORIZATION = "update_authorization"
SERVICE_DELETE_AUTHORIZATION = "delete_authorization"
SERVICE_GET_AUTHORIZATIONS = "get_authorizations"
SERVICE_GET_LOGS = "get_logs"

ATTR_ACTION = "action"
ATTR_TRANSPORT = "transport"
ATTR_AUTHORIZATION = "authorization"
ATTR_NAME = "name"
ATTR_CODE = "code"
ATTR_ENABLED = "enabled"
ATTR_REMOTE_ALLOWED = "remote_allowed"
ATTR_ALLOWED_FROM_DATE = "allowed_from_date"
ATTR_ALLOWED_UNTIL_DATE = "allowed_until_date"
ATTR_ALLOWED_WEEKDAYS = "allowed_weekdays"
ATTR_ALLOWED_FROM_TIME = "allowed_from_time"
ATTR_ALLOWED_UNTIL_TIME = "allowed_until_time"
ATTR_LIMIT = "limit"

KEYPAD_CODE = vol.All(cv.string, vol.Match(KEYPAD_CODE_PATTERN))

# Any state where the bolt is not thrown
UNLOCKED_STATES = frozenset(
    {
        STATE_UNLOCKING,
        STATE_UNLOCKED,
        STATE_LOCKING,
        STATE_UNLATCHED,
        STATE_UNLOCKED_LNG,
        STATE_UNLATCHING,
    }
)

ACCESS_LIMITS = {
    vol.Optional(ATTR_ALLOWED_FROM_DATE): cv.datetime,
    vol.Optional(ATTR_ALLOWED_UNTIL_DATE): cv.datetime,
    vol.Optional(ATTR_ALLOWED_WEEKDAYS): vol.All(
        cv.ensure_list, [vol.In(list(WEEKDAY_BITS))]
    ),
    vol.Optional(ATTR_ALLOWED_FROM_TIME): cv.time,
    vol.Optional(ATTR_ALLOWED_UNTIL_TIME): cv.time,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the lock and its entity services."""
    async_add_entities([NukiLock(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_LOCK_ACTION,
        {
            vol.Required(ATTR_ACTION): vol.In([action.value for action in LockAction]),
            vol.Optional(ATTR_TRANSPORT): vol.In(
                [transport.value for transport in ActionTransport]
            ),
        },
        "async_service_lock_action",
    )
    platform.async_register_entity_service(
        SERVICE_CREATE_KEYPAD_CODE,
        {
            vol.Required(ATTR_NAME): vol.All(cv.string, vol.Length(min=1, max=32)),
            vol.Required(ATTR_CODE): KEYPAD_CODE,
            **ACCESS_LIMITS,
        },
        "async_service_create_keypad_code",
    )
    platform.async_register_entity_service(
        SERVICE_UPDATE_AUTHORIZATION,
        {
            vol.Required(ATTR_AUTHORIZATION): cv.string,
            vol.Optional(ATTR_NAME): vol.All(cv.string, vol.Length(min=1, max=32)),
            vol.Optional(ATTR_ENABLED): cv.boolean,
            vol.Optional(ATTR_REMOTE_ALLOWED): cv.boolean,
            vol.Optional(ATTR_CODE): KEYPAD_CODE,
            **ACCESS_LIMITS,
        },
        "async_service_update_authorization",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_AUTHORIZATION,
        {vol.Required(ATTR_AUTHORIZATION): cv.string},
        "async_service_delete_authorization",
    )
    platform.async_register_entity_service(
        SERVICE_GET_AUTHORIZATIONS,
        None,
        "async_service_get_authorizations",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        SERVICE_GET_LOGS,
        {vol.Optional(ATTR_LIMIT, default=20): vol.All(int, vol.Range(1, 50))},
        "async_service_get_logs",
        supports_response=SupportsResponse.ONLY,
    )


class NukiLock(NukiProEntity, LockEntity):
    """The Nuki Smart Lock."""

    _attr_name = None
    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, coordinator: NukiProCoordinator) -> None:
        """Create the main entity of the device."""
        super().__init__(coordinator, "lock")

    @property
    def _state(self) -> int | None:
        return self.data.status.state

    @property
    def is_locked(self) -> bool | None:
        """Locked; unknown while uncalibrated or undefined."""
        if self._state == STATE_LOCKED:
            return True
        if self._state in UNLOCKED_STATES:
            return False
        return None

    @property
    def is_locking(self) -> bool:
        """Motor turning to lock."""
        return self._state == STATE_LOCKING

    @property
    def is_unlocking(self) -> bool:
        """Motor turning to unlock."""
        return self._state == STATE_UNLOCKING

    @property
    def is_open(self) -> bool:
        """Latch pulled back."""
        return self._state == STATE_UNLATCHED

    @property
    def is_opening(self) -> bool:
        """Latch being pulled back."""
        return self._state == STATE_UNLATCHING

    @property
    def is_jammed(self) -> bool:
        """Motor blocked."""
        return self._state == STATE_MOTOR_BLOCKED

    @property
    def changed_by(self) -> str | None:
        """Person behind the last lock activity."""
        activity = self.data.last_activity()
        return activity.user if activity else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Lock 'n' Go flag: the lock relocks by itself shortly."""
        return {"lock_n_go_pending": self._state == STATE_UNLOCKED_LNG}

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door."""
        await self.coordinator.async_lock_action(LockAction.LOCK)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door."""
        await self.coordinator.async_lock_action(LockAction.UNLOCK)

    async def async_open(self, **kwargs: Any) -> None:
        """Unlatch the door."""
        await self.coordinator.async_lock_action(LockAction.UNLATCH)

    # Entity services ---------------------------------------------------------

    async def async_service_lock_action(
        self, action: str, transport: str | None = None
    ) -> None:
        """Run any lock action, optionally forcing the channel."""
        await self.coordinator.async_lock_action(
            LockAction(action),
            ActionTransport(transport) if transport else None,
        )

    async def async_service_create_keypad_code(self, **kwargs: Any) -> None:
        """Create a keypad code."""
        await self.coordinator.async_create_keypad_code(**kwargs)

    async def async_service_update_authorization(
        self, authorization: str, **kwargs: Any
    ) -> None:
        """Update an authorization."""
        await self.coordinator.async_update_authorization(authorization, **kwargs)

    async def async_service_delete_authorization(self, authorization: str) -> None:
        """Delete an authorization."""
        await self.coordinator.async_delete_authorization(authorization)

    async def async_service_get_authorizations(self) -> ServiceResponse:
        """Return the authorizations (without keypad codes)."""
        return {"authorizations": self.coordinator.authorizations_summary()}

    async def async_service_get_logs(self, limit: int = 20) -> ServiceResponse:
        """Return the latest activity log entries."""
        return {"logs": await self.coordinator.async_fetch_logs(limit)}
