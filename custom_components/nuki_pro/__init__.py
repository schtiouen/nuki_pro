"""Nuki Pro: Nuki Smart Lock (5th generation) through the Nuki Web API and MQTT."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .coordinator import NukiProConfigEntry, NukiProCoordinator

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.EVENT,
]


async def async_setup_entry(hass: HomeAssistant, entry: NukiProConfigEntry) -> bool:
    """Set up one Nuki lock."""
    coordinator = NukiProCoordinator(hass, entry)
    await coordinator.async_start_mqtt()
    await coordinator.async_config_entry_first_refresh()
    # The lock device first: its accessories (door sensor, keypad, fob) link to it
    lock_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **coordinator.device_info
    )
    coordinator.lock_device_id = lock_device.id
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NukiProConfigEntry) -> bool:
    """Unload a config entry (the coordinator shuts MQTT down on unload)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
