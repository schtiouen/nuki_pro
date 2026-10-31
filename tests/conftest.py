"""Fixtures for the Nuki Pro tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.nuki_pro.const import (
    CONF_API_TOKEN,
    CONF_DEVICE_TYPE,
    CONF_MQTT_TOPIC,
    CONF_NUKI_ID,
    CONF_SMARTLOCK_ID,
    CONF_USE_MQTT,
    DOMAIN,
)

API = "https://api.nuki.io"
NUKI_ID = "1A2B3C4D"
SMARTLOCK_ID = (5 << 32) | 0x1A2B3C4D
TOKEN = "secret-token"
MQTT_TOPIC = f"nuki/{NUKI_ID}"

SMARTLOCK: dict[str, Any] = {
    "smartlockId": SMARTLOCK_ID,
    "accountId": 1,
    "type": 5,
    "authId": 1,
    "name": "Porte d'entrée",
    "favorite": False,
    "config": {
        "name": "Porte d'entrée",
        "latitude": 48.85,
        "longitude": 2.35,
        "pairingEnabled": True,
        "buttonEnabled": True,
        "ledEnabled": True,
        "ledBrightness": 3,
        "timezoneOffset": 60,
        "daylightSavingMode": 1,
        "fobPaired": True,
        "fobAction1": 1,
        "fobAction2": 2,
        "fobAction3": 0,
        "singleLock": False,
        "advertisingMode": 0,
        "keypadPaired": False,
        "keypad2Paired": True,
        "homekitState": 0,
        "matterState": 2,
        "timezoneId": 37,
        "deviceType": 5,
        "wifiEnabled": True,
        "productVariant": 2,
        "liftUpHandle": False,
    },
    "advancedConfig": {
        "totalDegrees": 900,
        "unlockedPositionOffsetDegrees": 0,
        "lockedPositionOffsetDegrees": 0,
        "singleLockedPositionOffsetDegrees": 0,
        "unlockedToLockedTransitionOffsetDegrees": 0,
        "lngTimeout": 20,
        "singleButtonPressAction": 1,
        "doubleButtonPressAction": 4,
        "detachedCylinder": False,
        "batteryType": 1,
        "automaticBatteryTypeDetection": True,
        "unlatchDuration": 3,
        "autoLock": True,
        "autoLockTimeout": 300,
        "autoUpdateEnabled": True,
        "motorSpeed": 0,
        "enableSlowSpeedDuringNightmode": False,
    },
    "state": {
        "mode": 2,
        "state": 1,
        "trigger": 0,
        "lastAction": 2,
        "batteryCritical": False,
        "batteryCharging": False,
        "batteryCharge": 87,
        "keypadBatteryCritical": False,
        "doorsensorBatteryCritical": False,
        "doorState": 2,
        "keypadMountingState": 1,
        "ringToOpenTimer": 0,
        "nightMode": False,
    },
    "firmwareVersion": 0x050102,
    "hardwareVersion": 0x0501,
    "serverState": 0,
    "adminPinState": 0,
    "virtualDevice": False,
    "updateDate": "2026-10-31T10:00:00.000Z",
}

AUTHS: list[dict[str, Any]] = [
    {
        "id": "auth-app-1",
        "smartlockId": SMARTLOCK_ID,
        "authId": 11,
        "type": 0,
        "name": "Alice",
        "enabled": True,
        "remoteAllowed": True,
        "lockCount": 120,
        "lastActiveDate": "2026-10-31T09:59:00.000Z",
    },
    {
        "id": "auth-code-1",
        "smartlockId": SMARTLOCK_ID,
        "authId": 21,
        "code": 385729,
        "type": 13,
        "name": "Femme de ménage",
        "enabled": True,
        "remoteAllowed": False,
        "lockCount": 4,
        "allowedWeekDays": 64 | 16,
        "allowedFromTime": 480,
        "allowedUntilTime": 720,
    },
    {
        "id": "auth-fob-1",
        "smartlockId": SMARTLOCK_ID,
        "authId": 31,
        "type": 2,
        "name": "Fob voiture",
        "enabled": True,
        "remoteAllowed": False,
        "lockCount": 9,
    },
]

LOGS: list[dict[str, Any]] = [
    {
        "id": "log3",
        "smartlockId": SMARTLOCK_ID,
        "deviceType": 5,
        "authId": "auth-app-1",
        "name": "Alice",
        "action": 2,
        "trigger": 5,
        "state": 0,
        "autoUnlock": False,
        "date": "2026-10-31T09:59:00.000Z",
        "source": 0,
    },
    {
        "id": "log2",
        "smartlockId": SMARTLOCK_ID,
        "deviceType": 5,
        "authId": "auth-code-1",
        "name": "Femme de ménage",
        "action": 3,
        "trigger": 255,
        "state": 0,
        "autoUnlock": False,
        "date": "2026-10-31T09:00:00.000Z",
        "source": 1,
    },
    {
        "id": "log1",
        "smartlockId": SMARTLOCK_ID,
        "deviceType": 5,
        "authId": "auth-app-1",
        "name": "Alice",
        "action": 1,
        "trigger": 5,
        "state": 0,
        "autoUnlock": False,
        "date": "2026-10-31T08:00:00.000Z",
        "source": 0,
    },
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/nuki_pro."""


@pytest.fixture
def smartlock() -> dict[str, Any]:
    """A fresh copy of the smartlock answer."""
    return deepcopy(SMARTLOCK)


def mock_web_api(
    aioclient_mock: AiohttpClientMocker,
    smartlock: dict[str, Any] | None = None,
    auths: list[dict[str, Any]] | None = None,
    logs: list[dict[str, Any]] | None = None,
) -> None:
    """Register the Web API answers."""
    smartlock = smartlock or deepcopy(SMARTLOCK)
    aioclient_mock.get(f"{API}/smartlock", json=[smartlock])
    aioclient_mock.get(f"{API}/smartlock/{SMARTLOCK_ID}", json=smartlock)
    aioclient_mock.get(
        f"{API}/smartlock/{SMARTLOCK_ID}/auth", json=deepcopy(auths or AUTHS)
    )
    aioclient_mock.get(
        f"{API}/smartlock/{SMARTLOCK_ID}/log", json=deepcopy(logs or LOGS)
    )
    for path in (
        "action",
        "config",
        "advanced/config",
        "auth",
        "auth/auth-app-1",
        "auth/auth-code-1",
    ):
        aioclient_mock.post(f"{API}/smartlock/{SMARTLOCK_ID}/{path}", status=204)
    aioclient_mock.put(f"{API}/smartlock/{SMARTLOCK_ID}/auth", status=204)
    aioclient_mock.delete(f"{API}/smartlock/{SMARTLOCK_ID}/auth/auth-code-1", status=204)


def make_entry(use_mqtt: bool = False) -> MockConfigEntry:
    """Config entry of the test lock."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Porte d'entrée",
        unique_id=NUKI_ID,
        data={
            CONF_NUKI_ID: NUKI_ID,
            CONF_DEVICE_TYPE: 5,
            CONF_SMARTLOCK_ID: SMARTLOCK_ID,
            CONF_API_TOKEN: TOKEN,
            CONF_USE_MQTT: use_mqtt,
            CONF_MQTT_TOPIC: MQTT_TOPIC if use_mqtt else None,
        },
    )
