"""Base entity for the Nuki Pro integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NukiProConfigEntry, NukiProCoordinator
from .models import NukiData


class NukiProEntity(CoordinatorEntity[NukiProCoordinator]):
    """Entity bound to one Nuki lock."""

    _attr_has_entity_name = True
    # Entities needing the Web API (settings, users) set this to True
    _requires_web = False

    def __init__(
        self,
        coordinator: NukiProCoordinator,
        key: str,
        accessory: str | None = None,
    ) -> None:
        """Set the unique id and the device: the lock or one of its accessories."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.nuki_id}_{key}"
        self._attr_device_info = (
            coordinator.accessory_device_info(accessory)
            if accessory
            else coordinator.device_info
        )

    @property
    def data(self) -> NukiData:
        """Shortcut to the coordinator data."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Available when the channel providing the value is up."""
        if not super().available:
            return False
        if self._requires_web:
            return self.data.web_available
        return self.data.mqtt_online or self.data.web_available


@callback
def async_add_dynamic_entities(
    entry: NukiProConfigEntry,
    add_entities: Callable[[Iterable[Entity]], None],
    build: Callable[[set[str]], list[NukiProEntity]],
) -> None:
    """Add entities now and whenever new data makes more of them relevant.

    `build` receives the keys already added and returns only new entities;
    it is called again after every coordinator update, so settings that only
    appear once the Web API answers (or a new keypad code) get an entity.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _check() -> None:
        if new := build(known):
            known.update(entity.unique_id or "" for entity in new)
            add_entities(new)

    _check()
    entry.async_on_unload(coordinator.async_add_listener(_check))


@callback
def async_remove_stale_entities(
    coordinator: NukiProCoordinator, platform: str, keep_unique_ids: set[str], prefix: str
) -> None:
    """Remove registry entries whose unique id starts with prefix and is gone."""
    registry = er.async_get(coordinator.hass)
    for entry in er.async_entries_for_config_entry(
        registry, coordinator.config_entry.entry_id
    ):
        if (
            entry.domain == platform
            and entry.unique_id.startswith(prefix)
            and entry.unique_id not in keep_unique_ids
        ):
            registry.async_remove(entry.entity_id)
