"""Switches for the Nuki Pro integration: lock settings and authorizations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACCESSORY_FOB, ACCESSORY_KEYPAD, AUTH_TYPES, WEEKDAY_BITS
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import (
    NukiProEntity,
    async_add_dynamic_entities,
    async_remove_stale_entities,
)

PARALLEL_UPDATES = 1

AUTH_KEY_PREFIX = "auth_"

AUTH_ICONS = {
    0: "mdi:cellphone-key",
    1: "mdi:bridge",
    2: "mdi:remote",
    3: "mdi:dialpad",
    13: "mdi:form-textbox-password",
    14: "mdi:key-chain",
    15: "mdi:account-key",
}


@dataclass(frozen=True, kw_only=True)
class NukiSettingSwitchDescription(SwitchEntityDescription):
    """Describe a switch bound to one field of the (advanced) config."""

    section: Literal["config", "advanced_config"]
    field: str


SETTING_SWITCHES: tuple[NukiSettingSwitchDescription, ...] = (
    NukiSettingSwitchDescription(
        key="auto_lock",
        translation_key="auto_lock",
        section="advanced_config",
        field="autoLock",
    ),
    NukiSettingSwitchDescription(
        key="button_enabled",
        translation_key="button_enabled",
        section="config",
        field="buttonEnabled",
    ),
    NukiSettingSwitchDescription(
        key="led_enabled",
        translation_key="led_enabled",
        section="config",
        field="ledEnabled",
    ),
    NukiSettingSwitchDescription(
        key="auto_update",
        translation_key="auto_update",
        section="advanced_config",
        field="autoUpdateEnabled",
    ),
    NukiSettingSwitchDescription(
        key="slow_speed_night_mode",
        translation_key="slow_speed_night_mode",
        section="advanced_config",
        field="enableSlowSpeedDuringNightmode",
    ),
    NukiSettingSwitchDescription(
        key="pairing_enabled",
        translation_key="pairing_enabled",
        section="config",
        field="pairingEnabled",
        entity_registry_enabled_default=False,
    ),
    NukiSettingSwitchDescription(
        key="detached_cylinder",
        translation_key="detached_cylinder",
        section="advanced_config",
        field="detachedCylinder",
        entity_registry_enabled_default=False,
    ),
    NukiSettingSwitchDescription(
        key="lift_up_handle",
        translation_key="lift_up_handle",
        section="config",
        field="liftUpHandle",
        entity_registry_enabled_default=False,
    ),
    NukiSettingSwitchDescription(
        key="automatic_battery_type_detection",
        translation_key="automatic_battery_type_detection",
        section="advanced_config",
        field="automaticBatteryTypeDetection",
        entity_registry_enabled_default=False,
    ),
)


def _minutes_to_hhmm(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _weekdays(mask: int | None) -> list[str] | None:
    if not mask:
        return None
    return [day for day, bit in WEEKDAY_BITS.items() if mask & bit]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up setting switches and one switch per authorization."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        data = coordinator.data
        entities: list[NukiProEntity] = [
            NukiSettingSwitch(coordinator, description)
            for description in SETTING_SWITCHES
            if coordinator.uid(description.key) not in known
            and getattr(data, description.section).get(description.field) is not None
        ]
        if coordinator.auth_entities_enabled:
            entities.extend(
                NukiAuthSwitch(coordinator, auth_id)
                for auth_id in data.auths
                if coordinator.uid(f"{AUTH_KEY_PREFIX}{auth_id}") not in known
            )
        return entities

    async_add_dynamic_entities(entry, async_add_entities, _build)

    @callback
    def _remove_deleted_auths() -> None:
        # Only prune after a successful authorizations fetch
        if not coordinator.data.extra.get("auths_fetched"):
            return
        async_remove_stale_entities(
            coordinator,
            "switch",
            {
                coordinator.uid(f"{AUTH_KEY_PREFIX}{auth_id}")
                for auth_id in coordinator.data.auths
            }
            if coordinator.auth_entities_enabled
            else set(),
            coordinator.uid(AUTH_KEY_PREFIX),
        )

    _remove_deleted_auths()
    entry.async_on_unload(coordinator.async_add_listener(_remove_deleted_auths))


class NukiSettingSwitch(NukiProEntity, SwitchEntity):
    """Switch changing a boolean lock setting through the Web API."""

    entity_description: NukiSettingSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG
    _requires_web = True

    def __init__(
        self,
        coordinator: NukiProCoordinator,
        description: NukiSettingSwitchDescription,
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the setting value."""
        section = getattr(self.data, self.entity_description.section)
        return section.get(self.entity_description.field)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        await self.coordinator.async_set_setting(
            self.entity_description.section, self.entity_description.field, value
        )


class NukiAuthSwitch(NukiProEntity, SwitchEntity):
    """Enable or disable one authorization (app user, fob, keypad code...)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "authorization"
    _requires_web = True

    def __init__(self, coordinator: NukiProCoordinator, auth_id: str) -> None:
        """Bind the authorization, on the device it belongs to."""
        auth_type = coordinator.data.auths.get(auth_id, {}).get("type")
        accessory = None
        if auth_type in (3, 13) and coordinator.data.has_keypad:
            accessory = ACCESSORY_KEYPAD
        elif auth_type == 2 and coordinator.data.has_fob:
            accessory = ACCESSORY_FOB
        super().__init__(coordinator, f"{AUTH_KEY_PREFIX}{auth_id}", accessory)
        self._auth_id = auth_id
        self._attr_icon = AUTH_ICONS.get(self._auth.get("type", -1), "mdi:account-key")

    @property
    def _auth(self) -> Mapping[str, Any]:
        return self.data.auths.get(self._auth_id, {})

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Name the entity after the authorization."""
        return {"name": self._auth.get("name") or self._auth_id}

    @property
    def available(self) -> bool:
        """Unavailable once the authorization is gone."""
        return super().available and bool(self._auth)

    @property
    def is_on(self) -> bool | None:
        """Return True when the authorization is enabled."""
        return self._auth.get("enabled")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the authorization details (never the keypad code itself)."""
        auth = self._auth
        return {
            "authorization_id": self._auth_id,
            "device_auth_id": auth.get("authId"),
            "type": AUTH_TYPES.get(auth.get("type", -1), auth.get("type")),
            "remote_allowed": auth.get("remoteAllowed"),
            "lock_count": auth.get("lockCount"),
            "last_active_date": auth.get("lastActiveDate"),
            "allowed_from_date": auth.get("allowedFromDate"),
            "allowed_until_date": auth.get("allowedUntilDate"),
            "allowed_weekdays": _weekdays(auth.get("allowedWeekDays")),
            "allowed_from_time": _minutes_to_hhmm(auth.get("allowedFromTime")),
            "allowed_until_time": _minutes_to_hhmm(auth.get("allowedUntilTime")),
            "fingerprints": len(auth.get("fingerprints") or {}),
            "creation_date": auth.get("creationDate"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the authorization."""
        await self.coordinator.async_update_auth(self._auth_id, {"enabled": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the authorization."""
        await self.coordinator.async_update_auth(self._auth_id, {"enabled": False})
