"""Config flow tests."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.nuki_pro.const import (
    CONF_ACTION_TRANSPORT,
    CONF_API_TOKEN,
    CONF_AUTH_ENTITIES,
    CONF_MQTT_TOPIC,
    CONF_NUKI_ID,
    CONF_SCAN_INTERVAL,
    CONF_USE_MQTT,
    DOMAIN,
)

from .conftest import API, MQTT_TOPIC, NUKI_ID, SMARTLOCK, SMARTLOCK_ID, TOKEN, make_entry, mock_web_api

FLOW = "custom_components.nuki_pro.config_flow"


def _no_mqtt():
    return patch(f"{FLOW}._async_mqtt_ready", AsyncMock(return_value=False))


async def test_user_flow_web_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Token only, one lock, no MQTT integration: entry created directly."""
    mock_web_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with _no_mqtt(), patch("custom_components.nuki_pro.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_TOKEN: f" {TOKEN} "}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Porte d'entrée"
    assert result["data"] == {
        CONF_NUKI_ID: NUKI_ID,
        "device_type": 5,
        "smartlock_id": SMARTLOCK_ID,
        CONF_API_TOKEN: TOKEN,
        CONF_USE_MQTT: False,
        CONF_MQTT_TOPIC: None,
    }
    assert result["result"].unique_id == NUKI_ID


async def test_user_flow_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rejected token, then an account without lock."""
    aioclient_mock.get(f"{API}/smartlock", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    opener = {**deepcopy(SMARTLOCK), "type": 2}
    aioclient_mock.get(f"{API}/smartlock", json=[opener])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: TOKEN}
    )
    assert result["errors"] == {"base": "no_devices"}


async def test_user_flow_select_lock(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Several locks on the account: the user picks one."""
    other = {**deepcopy(SMARTLOCK), "smartlockId": (4 << 32) | 0x0BADCAFE, "type": 4, "name": "Garage"}
    aioclient_mock.get(f"{API}/smartlock", json=[deepcopy(SMARTLOCK), other])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: TOKEN}
    )
    assert result["step_id"] == "select_lock"
    with _no_mqtt(), patch("custom_components.nuki_pro.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NUKI_ID: "0BADCAFE"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage"
    assert result["data"]["device_type"] == 4


async def test_mqtt_discovery_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The lock announces itself over MQTT; the token is still asked."""
    mock_web_api(aioclient_mock)
    info = MqttServiceInfo(
        topic=f"{MQTT_TOPIC}/deviceType",
        payload="5",
        qos=0,
        retain=True,
        subscribed_topic="nuki/+/deviceType",
        timestamp=0,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=info
    )
    assert result["step_id"] == "user"
    with patch(f"{FLOW}._async_mqtt_ready", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_TOKEN: TOKEN}
        )
    assert result["step_id"] == "mqtt_setup"
    with (
        patch(f"{FLOW}._async_probe_mqtt_topic", AsyncMock(return_value=True)),
        patch("custom_components.nuki_pro.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USE_MQTT: True, CONF_MQTT_TOPIC: MQTT_TOPIC}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USE_MQTT] is True
    assert result["data"][CONF_MQTT_TOPIC] == MQTT_TOPIC

    # An Opener announced on the same broker: ignored
    opener = MqttServiceInfo(
        topic="nuki/0BADCAFE/deviceType",
        payload="2",
        qos=0,
        retain=True,
        subscribed_topic="nuki/+/deviceType",
        timestamp=0,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=opener
    )
    assert result["reason"] == "not_supported"

    # Same lock announced again: aborted
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_MQTT}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A new token is stored."""
    mock_web_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.nuki_pro.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_TOKEN: "new-token"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == "new-token"


async def test_options_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Polling interval, channel and per-user switches."""
    mock_web_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 45.0, CONF_ACTION_TRANSPORT: "web", CONF_AUTH_ENTITIES: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.update_interval.total_seconds() == 45

    # Interval left empty: automatic again
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 45.0, CONF_ACTION_TRANSPORT: "web", CONF_AUTH_ENTITIES: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        CONF_SCAN_INTERVAL: 45,
        CONF_ACTION_TRANSPORT: "web",
        CONF_AUTH_ENTITIES: False,
    }
    # Reloaded without the per-user switches
    assert hass.states.get("switch.porte_d_entree_access_alice") is None
