"""Buttons for the Nuki Pro integration: extra lock actions and refresh."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LockAction
from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .entity import NukiProEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NukiButtonDescription(ButtonEntityDescription):
    """Describe a button; `action` None means a data refresh."""

    action: LockAction | None = None


BUTTONS: tuple[NukiButtonDescription, ...] = (
    NukiButtonDescription(
        key="lock_n_go",
        translation_key="lock_n_go",
        action=LockAction.LOCK_N_GO,
    ),
    NukiButtonDescription(
        key="lock_n_go_unlatch",
        translation_key="lock_n_go_unlatch",
        action=LockAction.LOCK_N_GO_UNLATCH,
        # Opens the door: off by default to avoid accidental presses
        entity_registry_enabled_default=False,
    ),
    NukiButtonDescription(
        key="full_lock",
        translation_key="full_lock",
        action=LockAction.FULL_LOCK,
    ),
    NukiButtonDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NukiProConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        NukiButton(coordinator, description) for description in BUTTONS
    )


class NukiButton(NukiProEntity, ButtonEntity):
    """Button running a lock action or refreshing the data."""

    entity_description: NukiButtonDescription

    def __init__(
        self, coordinator: NukiProCoordinator, description: NukiButtonDescription
    ) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """The refresh button stays usable to recover from an outage."""
        if self.entity_description.action is None:
            return True
        return super().available

    async def async_press(self) -> None:
        """Run the action."""
        if (action := self.entity_description.action) is None:
            await self.coordinator.async_full_refresh()
            return
        await self.coordinator.async_lock_action(action)
