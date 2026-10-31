"""Selects for the Nuki Pro integration: lock settings with a list of values."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ACCESSORY_FOB,
    ADVERTISING_MODES,
    BATTERY_TYPES,
    BUTTON_PRESS_ACTIONS,
    FOB_ACTIONS,
    LNG_TIMEOUTS,
    MOTOR_SPEEDS,
    UNLATCH_DURATIONS,
)
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity, async_add_dynamic_entities
from .models import NukiData

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NukiSelectDescription(SelectEntityDescription):
    """Describe a select bound to one field of the (advanced) config."""

    section: Literal["config", "advanced_config"]
    field: str
    mapping: Mapping[int, str]
    exists_fn: Callable[[NukiData], bool] = lambda _: True
    # Device of the entity: None for the lock, else an accessory
    accessory: str | None = None


def _seconds(values: tuple[int, ...]) -> dict[int, str]:
    return {value: str(value) for value in values}


SELECTS: tuple[NukiSelectDescription, ...] = (
    NukiSelectDescription(
        key="single_button_press_action",
        translation_key="single_button_press_action",
        section="advanced_config",
        field="singleButtonPressAction",
        mapping=BUTTON_PRESS_ACTIONS,
    ),
    NukiSelectDescription(
        key="double_button_press_action",
        translation_key="double_button_press_action",
        section="advanced_config",
        field="doubleButtonPressAction",
        mapping=BUTTON_PRESS_ACTIONS,
    ),
    NukiSelectDescription(
        key="motor_speed",
        translation_key="motor_speed",
        section="advanced_config",
        field="motorSpeed",
        mapping=MOTOR_SPEEDS,
    ),
    NukiSelectDescription(
        key="lng_timeout",
        translation_key="lng_timeout",
        section="advanced_config",
        field="lngTimeout",
        mapping=_seconds(LNG_TIMEOUTS),
    ),
    NukiSelectDescription(
        key="unlatch_duration",
        translation_key="unlatch_duration",
        section="advanced_config",
        field="unlatchDuration",
        mapping=_seconds(UNLATCH_DURATIONS),
    ),
    NukiSelectDescription(
        key="fob_action_1",
        translation_key="fob_action_1",
        section="config",
        field="fobAction1",
        mapping=FOB_ACTIONS,
        exists_fn=lambda data: data.has_fob,
        accessory=ACCESSORY_FOB,
    ),
    NukiSelectDescription(
        key="fob_action_2",
        translation_key="fob_action_2",
        section="config",
        field="fobAction2",
        mapping=FOB_ACTIONS,
        exists_fn=lambda data: data.has_fob,
        accessory=ACCESSORY_FOB,
    ),
    NukiSelectDescription(
        key="fob_action_3",
        translation_key="fob_action_3",
        section="config",
        field="fobAction3",
        mapping=FOB_ACTIONS,
        exists_fn=lambda data: data.has_fob,
        accessory=ACCESSORY_FOB,
    ),
    NukiSelectDescription(
        key="advertising_mode",
        translation_key="advertising_mode",
        section="config",
        field="advertisingMode",
        mapping=ADVERTISING_MODES,
        entity_registry_enabled_default=False,
    ),
    NukiSelectDescription(
        key="battery_type",
        translation_key="battery_type",
        section="advanced_config",
        field="batteryType",
        mapping=BATTERY_TYPES,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects, adding new ones when their data shows up."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        data = coordinator.data
        return [
            NukiSettingSelect(coordinator, description)
            for description in SELECTS
            if coordinator.uid(description.key) not in known
            and getattr(data, description.section).get(description.field) is not None
            and description.exists_fn(data)
        ]

    async_add_dynamic_entities(entry, async_add_entities, _build)


class NukiSettingSelect(NukiProEntity, SelectEntity):
    """Select changing an enumerated lock setting through the Web API."""

    entity_description: NukiSelectDescription
    _attr_entity_category = EntityCategory.CONFIG
    _requires_web = True

    def __init__(
        self, coordinator: NukiProCoordinator, description: NukiSelectDescription
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key, description.accessory)
        self.entity_description = description
        self._attr_options = list(description.mapping.values())
        self._reverse = {name: code for code, name in description.mapping.items()}

    @property
    def current_option(self) -> str | None:
        """Return the selected value."""
        section = getattr(self.data, self.entity_description.section)
        return self.entity_description.mapping.get(
            section.get(self.entity_description.field)
        )

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        await self.coordinator.async_set_setting(
            self.entity_description.section,
            self.entity_description.field,
            self._reverse[option],
        )
