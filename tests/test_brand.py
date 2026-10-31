"""The Nuki logo ships with the integration (brand/ folder, HA 2026+)."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_custom_components

BRAND = Path(__file__).parent.parent / "custom_components" / "nuki_pro" / "brand"


async def test_brand_images(hass: HomeAssistant) -> None:
    """Home Assistant sees the local brand images."""
    integration = (await async_get_custom_components(hass))["nuki_pro"]
    assert integration.has_branding
    for image in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png", "dark_icon.png"):
        assert (BRAND / image).read_bytes().startswith(b"\x89PNG")
