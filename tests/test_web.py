"""Web API only mode (token, no MQTT), like hass_nuki_ng without a Bridge."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

import asyncio

from homeassistant.helpers import device_registry as dr

from custom_components.nuki_pro.const import DOMAIN

from .conftest import API, LOGS, NUKI_ID, SMARTLOCK_ID, make_entry, mock_web_api

LOCK = "lock.porte_d_entree"


async def _setup(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    mock_web_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _calls(aioclient_mock: AiohttpClientMocker, method: str, suffix: str) -> list:
    return [
        call
        for call in aioclient_mock.mock_calls
        if call[0] == method and str(call[1]).endswith(suffix)
    ]


async def test_entities(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Every hass_nuki_ng entity has its counterpart, with the right values."""
    await _setup(hass, aioclient_mock)

    assert hass.states.get(LOCK).state == "locked"
    assert hass.states.get("sensor.porte_d_entree_battery").state == "87"
    assert hass.states.get("sensor.porte_d_entree_lock_state").state == "locked"
    assert hass.states.get("sensor.porte_d_entree_door_sensor_state").state == "closed"
    assert (
        hass.states.get("sensor.porte_d_entree_door_security").state
        == "closed_and_locked"
    )
    assert hass.states.get("binary_sensor.porte_d_entree_door_sensor").state == "off"
    assert hass.states.get("binary_sensor.porte_d_entree_locked").state == "off"
    assert hass.states.get("binary_sensor.porte_d_entree_battery_critical").state == "off"
    assert (
        hass.states.get("binary_sensor.porte_d_entree_keypad_battery_critical").state
        == "off"
    )
    assert (
        hass.states.get("binary_sensor.porte_d_entree_door_sensor_battery_critical").state
        == "off"
    )
    # Who did what (Web API log)
    assert hass.states.get("sensor.porte_d_entree_last_user").state == "Alice"
    assert hass.states.get("sensor.porte_d_entree_last_lock_user").state == "Alice"
    unlock_user = hass.states.get("sensor.porte_d_entree_last_unlock_user")
    assert unlock_user.state == "Femme de ménage"
    assert unlock_user.attributes["action"] == "unlatch"
    assert unlock_user.attributes["source"] == "keypad_code"
    assert (
        hass.states.get("sensor.porte_d_entree_last_unlatch_user").state
        == "Femme de ménage"
    )
    assert hass.states.get("sensor.porte_d_entree_last_action").state == "lock"
    assert hass.states.get("sensor.porte_d_entree_firmware").state == "5.1.2"
    # Settings
    assert hass.states.get("switch.porte_d_entree_auto_lock").state == "on"
    assert hass.states.get("switch.porte_d_entree_button_enabled").state == "on"
    assert hass.states.get("select.porte_d_entree_motor_speed").state == "standard"
    assert (
        hass.states.get("select.porte_d_entree_double_button_press").state == "unlatch"
    )
    assert hass.states.get("number.porte_d_entree_auto_lock_timeout").state == "300"
    # One switch per authorization, keypad code never exposed
    code_switch = hass.states.get("switch.porte_d_entree_keypad_access_femme_de_menage")
    assert code_switch.state == "on"
    assert code_switch.attributes["allowed_weekdays"] == ["mon", "wed"]
    assert code_switch.attributes["allowed_from_time"] == "08:00"
    assert "385729" not in str(code_switch.attributes)
    assert hass.states.get("switch.porte_d_entree_access_alice").state == "on"

    assert hass.states.get("switch.porte_d_entree_fob_access_fob_voiture").state == "on"
    assert hass.states.get("select.porte_d_entree_fob_single_press").state == "unlock"

    registry = er.async_get(hass)
    assert registry.async_get(LOCK).unique_id == "1A2B3C4D_lock"


async def test_accessory_devices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Door sensor, keypad and fob are their own devices, linked to the lock."""
    await _setup(hass, aioclient_mock)
    devices = dr.async_get(hass)
    lock = devices.async_get_device_by_identifier((DOMAIN, NUKI_ID), _entry_id(hass))
    assert lock.model == "Smart Lock Pro (5th gen)"
    expected = {
        "door_sensor": ("Door Sensor", "Porte d'entrée door sensor"),
        "keypad": ("Keypad 2", "Porte d'entrée keypad"),
        "fob": ("Fob", "Porte d'entrée fob"),
    }
    for key, (model, name) in expected.items():
        device = devices.async_get_device_by_identifier(
            (DOMAIN, f"{NUKI_ID}_{key}"), _entry_id(hass)
        )
        assert device.model == model
        assert device.name == name
        assert device.via_device_id == lock.id
    door_entities = {
        entry.entity_id
        for entry in er.async_entries_for_device(
            er.async_get(hass),
            devices.async_get_device_by_identifier(
                (DOMAIN, f"{NUKI_ID}_door_sensor"), _entry_id(hass)
            ).id,
        )
    }
    assert door_entities == {
        "binary_sensor.porte_d_entree_door_sensor",
        "binary_sensor.porte_d_entree_door_sensor_battery_critical",
        "binary_sensor.porte_d_entree_door_sensor_tamper",
        "sensor.porte_d_entree_door_sensor_state",
        "event.porte_d_entree_door_sensor_events",
    }


def _entry_id(hass: HomeAssistant) -> str:
    return hass.config_entries.async_entries(DOMAIN)[0].entry_id


async def test_parallel_settings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Two settings changed together both reach the lock."""
    await _setup(hass, aioclient_mock)
    await asyncio.gather(
        hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.porte_d_entree_auto_lock"}, blocking=True
        ),
        hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.porte_d_entree_auto_lock_timeout", "value": 60},
            blocking=True,
        ),
    )
    last = _calls(aioclient_mock, "POST", "/advanced/config")[-1][2]
    assert last["autoLock"] is False
    assert last["autoLockTimeout"] == 60


async def test_door_events_from_log(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without MQTT, new log lines fire the door and activity events."""
    await _setup(hass, aioclient_mock)
    new_logs = [
        {**LOGS[0], "id": "log5", "action": 208, "trigger": 0, "name": "", "date": "2026-10-31T10:05:00.000Z"},
        {**LOGS[0], "id": "log4", "action": 1, "name": "Alice", "date": "2026-10-31T10:01:00.000Z"},
        *LOGS,
    ]
    aioclient_mock.clear_requests()
    mock_web_api(aioclient_mock, logs=new_logs)
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert (
        hass.states.get("event.porte_d_entree_door_sensor_events").attributes["event_type"]
        == "door_ajar_warning"
    )
    activity = hass.states.get("event.porte_d_entree_activity")
    assert activity.attributes["event_type"] == "unlock"
    assert activity.attributes["user"] == "Alice"


async def test_lock_actions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Lock actions go to the Web API action endpoint."""
    await _setup(hass, aioclient_mock)

    await hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    await hass.services.async_call("lock", "open", {"entity_id": LOCK}, blocking=True)
    await hass.services.async_call(
        "nuki_pro", "lock_action", {"entity_id": LOCK, "action": "full_lock"}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.porte_d_entree_lock_n_go"}, blocking=True
    )
    payloads = [call[2] for call in _calls(aioclient_mock, "POST", "/action")]
    assert payloads == [
        {"action": 1},
        {"action": 3},
        {"action": 2, "option": 4},
        {"action": 4},
    ]


async def test_settings(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A setting change sends the whole config object, optimistically applied."""
    await _setup(hass, aioclient_mock)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.porte_d_entree_auto_lock"}, blocking=True
    )
    sent = _calls(aioclient_mock, "POST", "/advanced/config")[-1][2]
    assert sent["autoLock"] is False
    assert sent["totalDegrees"] == 900  # full object
    assert hass.states.get("switch.porte_d_entree_auto_lock").state == "off"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.porte_d_entree_motor_speed", "option": "slow"},
        blocking=True,
    )
    assert _calls(aioclient_mock, "POST", "/advanced/config")[-1][2]["motorSpeed"] == 2

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.porte_d_entree_led_enabled"}, blocking=True
    )
    sent = _calls(aioclient_mock, "POST", f"/smartlock/{SMARTLOCK_ID}/config")[-1][2]
    assert sent["ledEnabled"] is False
    assert sent["name"] == "Porte d'entrée"


async def test_authorizations(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Enable/disable, keypad code creation, update and deletion."""
    await _setup(hass, aioclient_mock)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.porte_d_entree_keypad_access_femme_de_menage"},
        blocking=True,
    )
    assert _calls(aioclient_mock, "POST", "/auth/auth-code-1")[-1][2] == {
        "name": "Femme de ménage",
        "enabled": False,
    }

    await hass.services.async_call(
        "nuki_pro",
        "create_keypad_code",
        {
            "entity_id": LOCK,
            "name": "Livreur",
            "code": "456789",
            "allowed_weekdays": ["mon", "fri"],
            "allowed_from_time": "09:00",
            "allowed_until_time": "12:30",
        },
        blocking=True,
    )
    created = _calls(aioclient_mock, "PUT", "/auth")[-1][2]
    assert created == {
        "name": "Livreur",
        "type": 13,
        "code": 456789,
        "remoteAllowed": False,
        "allowedWeekDays": 64 | 4,
        "allowedFromTime": 540,
        "allowedUntilTime": 750,
    }

    await hass.services.async_call(
        "nuki_pro",
        "update_authorization",
        {"entity_id": LOCK, "authorization": "femme de ménage", "code": "987654"},
        blocking=True,
    )
    assert _calls(aioclient_mock, "POST", "/auth/auth-code-1")[-1][2] == {
        "name": "Femme de ménage",
        "code": 987654,
    }

    await hass.services.async_call(
        "nuki_pro",
        "delete_authorization",
        {"entity_id": LOCK, "authorization": "auth-code-1"},
        blocking=True,
    )
    assert _calls(aioclient_mock, "DELETE", "/auth/auth-code-1")

    response = await hass.services.async_call(
        "nuki_pro",
        "get_authorizations",
        {"entity_id": LOCK},
        blocking=True,
        return_response=True,
    )
    names = [a["name"] for a in response[LOCK]["authorizations"]]
    assert names == ["Alice", "Femme de ménage", "Fob voiture"]
    assert "385729" not in str(response)

    logs = await hass.services.async_call(
        "nuki_pro", "get_logs", {"entity_id": LOCK, "limit": 3}, blocking=True, return_response=True
    )
    assert logs[LOCK]["logs"][1]["action"] == "unlatch"
    assert logs[LOCK]["logs"][1]["name"] == "Femme de ménage"


async def test_invalid_keypad_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Codes with a 0 or starting with 12 are rejected before any call."""
    import pytest
    import voluptuous as vol

    await _setup(hass, aioclient_mock)
    for code in ("123456", "102345", "12345"):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                "nuki_pro",
                "create_keypad_code",
                {"entity_id": LOCK, "name": "X", "code": code},
                blocking=True,
            )


async def test_reauth_on_401(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected token starts the reauthentication flow."""
    aioclient_mock.get(f"{API}/smartlock/{SMARTLOCK_ID}", status=401)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


def test_activity_merge_one_to_one() -> None:
    """One log line absorbs one MQTT event; a second person stays visible."""
    from datetime import UTC, datetime, timedelta

    from custom_components.nuki_pro.models import NukiActivity, NukiData

    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    data = NukiData(nuki_id="1A2B3C4D", device_type=5)
    data.mqtt_activities = [
        NukiActivity(action=1, timestamp=now + timedelta(seconds=30), origin="mqtt", user="Bob"),
        NukiActivity(action=1, timestamp=now, origin="mqtt", user=None),
    ]
    data.web_activities = [
        NukiActivity(action=1, timestamp=now + timedelta(seconds=2), origin="web", user="Alice"),
    ]
    assert [a.user for a in data.activities] == ["Bob", "Alice"]
