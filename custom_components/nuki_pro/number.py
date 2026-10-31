"""Numbers for the Nuki Pro integration: numeric lock settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NukiNumberDescription(NumberEntityDescription):
    """Describe a number bound to one field of the (advanced) config."""

    section: Literal["config", "advanced_config"]
    field: str


NUMBERS: tuple[NukiNumberDescription, ...] = (
    NukiNumberDescription(
        key="auto_lock_timeout",
        translation_key="auto_lock_timeout",
        section="advanced_config",
        field="autoLockTimeout",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=2,
        native_max_value=3600,
        native_step=1,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers, adding new ones when their data shows up."""
    coordinator = entry.runtime_data

    def _build(known: set[str]) -> list[NukiProEntity]:
        data = coordinator.data
        return [
            NukiSettingNumber(coordinator, description)
            for description in NUMBERS
            if coordinator.uid(description.key) not in known
            and getattr(data, description.section).get(description.field) is not None
        ]

    async_add_dynamic_entities(entry, async_add_entities, _build)


class NukiSettingNumber(NukiProEntity, NumberEntity):
    """Number changing a numeric lock setting through the Web API."""

    entity_description: NukiNumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _requires_web = True

    def __init__(
        self, coordinator: NukiProCoordinator, description: NukiNumberDescription
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the setting value."""
        section = getattr(self.data, self.entity_description.section)
        return section.get(self.entity_description.field)

    async def async_set_native_value(self, value: float) -> None:
        """Change the setting."""
        await self.coordinator.async_set_setting(
            self.entity_description.section,
            self.entity_description.field,
            int(value),
        )
