"""Diagnostics never leak the token, keypad codes, names or position."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.nuki_pro.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN, make_entry, mock_web_api


async def test_diagnostics_redacted(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Secrets and personal data are redacted."""
    mock_web_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(result, default=str)
    for secret in (TOKEN, "385729", "48.85", "Femme de ménage", "Alice"):
        assert secret not in dumped
    assert result["model"] == "Smart Lock Pro (5th gen)"
    assert result["status"]["battery_charge"] == 87
