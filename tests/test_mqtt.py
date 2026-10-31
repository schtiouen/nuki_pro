"""Web API + local MQTT mode."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
from pytest_homeassistant_custom_component.typing import MqttMockHAClient
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import MQTT_TOPIC, make_entry, mock_web_api

# HA's MQTT client keeps a periodic housekeeping timer alive between tests
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

LOCK = "lock.porte_d_entree"
EVENT = "event.porte_d_entree_activity"

RETAINED = {
    "deviceType": "5",
    "name": "Porte d'entrée",
    "firmware": "5.10.2",
    "connected": "true",
    "serverConnected": "true",
    "mode": "2",
    "state": "1",
    "batteryCritical": "false",
    "batteryChargeState": "92",
    "batteryCharging": "true",
    "keypadBatteryCritical": "false",
    "doorsensorState": "2",
    "doorsensorBatteryCritical": "false",
}


@pytest.fixture
async def setup_mqtt(
    hass: HomeAssistant,
    mqtt_mock: MqttMockHAClient,
    aioclient_mock: AiohttpClientMocker,
) -> MqttMockHAClient:
    """Set up the entry, then deliver the retained topics."""
    mock_web_api(aioclient_mock)
    entry = make_entry(use_mqtt=True)
    entry.add_to_hass(hass)
    with patch("custom_components.nuki_pro.coordinator.MQTT_INITIAL_WAIT", 0.01):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    for topic, payload in RETAINED.items():
        async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/{topic}", payload, retain=True)
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    return mqtt_mock


async def _push(hass: HomeAssistant, topic: str, payload: str) -> None:
    async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/{topic}", payload)
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()


async def test_push_state(hass: HomeAssistant, setup_mqtt: MqttMockHAClient) -> None:
    """MQTT values win over the Web API ones and arrive instantly."""
    assert hass.states.get("binary_sensor.porte_d_entree_mqtt_connection").state == "on"
    assert hass.states.get("sensor.porte_d_entree_battery").state == "92"
    assert hass.states.get("binary_sensor.porte_d_entree_charging").state == "on"
    assert hass.states.get("sensor.porte_d_entree_firmware").state == "5.10.2"

    await _push(hass, "state", "7")
    assert hass.states.get(LOCK).state == "opening"
    await _push(hass, "state", "5")
    assert hass.states.get(LOCK).state == "open"
    await _push(hass, "doorsensorState", "3")
    assert hass.states.get("binary_sensor.porte_d_entree_door_sensor").state == "on"
    door_event = hass.states.get("event.porte_d_entree_door_sensor_events")
    assert door_event.attributes["event_type"] == "door_opened"
    assert hass.states.get("sensor.porte_d_entree_door_security").state == "open"
    await _push(hass, "state", "254")
    assert hass.states.get(LOCK).state == "jammed"


async def test_activity_event(hass: HomeAssistant, setup_mqtt: MqttMockHAClient) -> None:
    """lockActionEvent fires the event entity with the person's name."""
    # Unlatch with keypad code 21 (Femme de ménage), source 1 = code
    await _push(hass, "lockActionEvent", "3,0,99,21,1")
    event = hass.states.get(EVENT)
    assert event.attributes["event_type"] == "unlatch"
    assert event.attributes["user"] == "Femme de ménage"
    assert event.attributes["trigger"] == "keypad"
    assert event.attributes["source"] == "keypad_code"
    assert (
        hass.states.get("sensor.porte_d_entree_last_unlatch_user").state
        == "Femme de ménage"
    )

    # Lock from the app by Alice (auth 11)
    await _push(hass, "lockActionEvent", "2,0,11,0,0")
    assert hass.states.get(EVENT).attributes["user"] == "Alice"
    assert hass.states.get("sensor.porte_d_entree_last_lock_user").state == "Alice"
    assert hass.states.get("sensor.porte_d_entree_last_action").state == "lock"

    # Button pressed twice while set to "no action": automation trigger only
    await _push(hass, "lockActionEvent", "90,2,0,0,2")
    event = hass.states.get(EVENT)
    assert event.attributes["event_type"] == "button_no_action"
    assert event.attributes["presses"] == 2
    assert hass.states.get("sensor.porte_d_entree_last_action").state == "lock"


async def test_retained_event_ignored(
    hass: HomeAssistant, setup_mqtt: MqttMockHAClient
) -> None:
    """A retained lockActionEvent replayed on subscribe is not a new event."""
    before = hass.states.get(EVENT).state
    async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/lockActionEvent", "1,0,11,0,0", retain=True)
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).state == before


async def test_lock_over_mqtt(
    hass: HomeAssistant,
    setup_mqtt: MqttMockHAClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Actions are published on lockAction (QoS 2) and wait for commandResponse."""
    task = hass.async_create_task(
        hass.services.async_call("lock", "lock", {"entity_id": LOCK}, blocking=True)
    )
    await asyncio.sleep(0.1)
    call = setup_mqtt.async_publish.call_args
    assert call.args == (f"{MQTT_TOPIC}/lockAction", "2", 2, False)
    assert call.kwargs == {"message_expiry_interval": 10}
    async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/commandResponse", "0")
    await task
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/action")]


async def test_mqtt_command_rejected(
    hass: HomeAssistant, setup_mqtt: MqttMockHAClient
) -> None:
    """A non-zero commandResponse is reported with its meaning."""
    task = hass.async_create_task(
        hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    )
    await asyncio.sleep(0.1)
    async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/commandResponse", "69")
    with pytest.raises(HomeAssistantError, match="busy"):
        await task


async def test_fallback_to_web(
    hass: HomeAssistant,
    setup_mqtt: MqttMockHAClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """No MQTT answer (Allow locking off?): the Web API takes over."""
    with patch("custom_components.nuki_pro.coordinator.MQTT_COMMAND_TIMEOUT", 0.2):
        await hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    calls = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/action")]
    assert calls[-1][2] == {"action": 1}


async def test_mqtt_offline_uses_web(
    hass: HomeAssistant,
    setup_mqtt: MqttMockHAClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """When the lock reports connected=false, Web API values are used."""
    await _push(hass, "connected", "false")
    assert hass.states.get("binary_sensor.porte_d_entree_mqtt_connection").state == "off"
    # Web API battery (87) replaces the frozen MQTT one (92)
    assert hass.states.get("sensor.porte_d_entree_battery").state == "87"
    assert hass.states.get(LOCK).state == "locked"
    await hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    calls = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/action")]
    assert calls[-1][2] == {"action": 1}


async def test_unknown_event_action_ignored(
    hass: HomeAssistant, setup_mqtt: MqttMockHAClient
) -> None:
    """An unexpected action code neither crashes nor changes the last action."""
    await _push(hass, "lockActionEvent", "2,0,11,0,0")
    await _push(hass, "lockActionEvent", "240,0,0,0,0")
    assert hass.states.get("sensor.porte_d_entree_last_action").state == "lock"


async def test_revoked_token_keeps_mqtt_control(
    hass: HomeAssistant,
    setup_mqtt: MqttMockHAClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A rejected token asks for a new one but the lock stays usable over MQTT."""
    from .conftest import API, SMARTLOCK_ID

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/smartlock/{SMARTLOCK_ID}", status=401)
    coordinator = hass.config_entries.async_entries("nuki_pro")[0].runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert hass.states.get(LOCK).state == "locked"
    assert hass.states.get("binary_sensor.porte_d_entree_web_api_connection").state == "off"

    task = hass.async_create_task(
        hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    )
    await asyncio.sleep(0.1)
    async_fire_mqtt_message(hass, f"{MQTT_TOPIC}/commandResponse", "0")
    await task
    assert setup_mqtt.async_publish.call_args.args[:2] == (f"{MQTT_TOPIC}/lockAction", "1")


async def test_retained_command_response_ignored(
    hass: HomeAssistant, setup_mqtt: MqttMockHAClient
) -> None:
    """A retained commandResponse replayed by the broker is not an answer."""
    with patch("custom_components.nuki_pro.coordinator.MQTT_COMMAND_TIMEOUT", 0.3):
        task = hass.async_create_task(
            hass.services.async_call(
                "nuki_pro",
                "lock_action",
                {"entity_id": LOCK, "action": "lock", "transport": "mqtt"},
                blocking=True,
            )
        )
        await asyncio.sleep(0.1)
        async_fire_mqtt_message(
            hass, f"{MQTT_TOPIC}/commandResponse", "0", retain=True
        )
        with pytest.raises(HomeAssistantError):
            await task
