"""Diagnostics for the Nuki Pro integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN
from .coordinator import NukiProConfigEntry

TO_REDACT = {
    CONF_API_TOKEN,
    "code",
    "latitude",
    "longitude",
    "accountId",
    "accountUserId",
    "authId",
    "name",
    "email",
    "fingerprints",
    "user",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NukiProConfigEntry
) -> dict[str, Any]:
    """Return the data of one lock, without secrets nor personal data."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "channels": {
            "mqtt_enabled": coordinator.mqtt_topic is not None,
            "mqtt_online": data.mqtt_online,
            "web_enabled": coordinator.web is not None,
            "web_available": data.web_available,
            "last_update_success": coordinator.last_update_success,
        },
        "model": coordinator.model,
        "firmware": data.firmware,
        "hardware": data.hardware,
        "mqtt_status": asdict(data.mqtt_status),
        "web_status": asdict(data.web_status),
        "status": asdict(data.status),
        "smartlock": async_redact_data(data.smartlock, TO_REDACT),
        "authorizations": async_redact_data(list(data.auths.values()), TO_REDACT),
        "logs": async_redact_data(data.logs[:10], TO_REDACT),
        "activities": [
            async_redact_data(activity.as_dict(), TO_REDACT)
            for activity in data.activities[:10]
        ],
        "extra": data.extra,
    }
