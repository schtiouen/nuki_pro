"""Async client for the Nuki Web API (https://api.nuki.io).

Only the endpoints used by the integration are implemented. Field names and
enumerations follow the official swagger file:
https://api.nuki.io/static/swagger/swagger.json
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://api.nuki.io"
REQUEST_TIMEOUT = 20


class NukiWebApiError(Exception):
    """Base error raised by the Nuki Web API client."""


class NukiWebApiConnectionError(NukiWebApiError):
    """The Nuki Web API could not be reached."""


class NukiWebApiAuthError(NukiWebApiError):
    """The API token is invalid or expired (HTTP 401)."""


class NukiWebApiResponseError(NukiWebApiError):
    """The Nuki Web API answered with an error status."""

    def __init__(self, status: int, message: str) -> None:
        """Store the HTTP status next to the message."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class NukiWebApiForbiddenError(NukiWebApiResponseError):
    """The token lacks the scope required by this endpoint (HTTP 403)."""


class NukiWebApiRateLimitError(NukiWebApiResponseError):
    """Too many requests were sent (HTTP 429)."""


def nuki_id_from_smartlock_id(smartlock_id: int) -> str:
    """Return the Nuki ID (8 hex digits) embedded in a Web API smartlock ID.

    The Web API identifier is the device type followed by the Nuki ID in hex,
    e.g. type 5 and Nuki ID 1A2B3C4D give 0x51A2B3C4D.
    """
    return f"{smartlock_id & 0xFFFFFFFF:08X}"


def device_type_from_smartlock_id(smartlock_id: int) -> int:
    """Return the device type embedded in a Web API smartlock ID."""
    return smartlock_id >> 32


def smartlock_id_from_nuki_id(nuki_id: str, device_type: int) -> int:
    """Build the Web API smartlock ID from a Nuki ID and a device type."""
    return (device_type << 32) | int(nuki_id, 16)


class NukiWebApi:
    """Minimal async wrapper around the Nuki Web API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the client with a shared aiohttp session."""
        self._session = session
        self._token = token
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and decode the JSON answer (None for empty bodies)."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    params=params,
                    json=payload,
                ) as resp:
                    body = await resp.read()
                    status = resp.status
        except (aiohttp.ClientError, TimeoutError) as err:
            # Never repr() the error: for some aiohttp errors it includes the
            # request headers, hence the token
            raise NukiWebApiConnectionError(
                f"{method} {path} failed: {type(err).__name__}: {err}"
            ) from err

        _LOGGER.debug("%s %s -> %s", method, path, status)
        message = body.decode("utf-8", "replace")[:300]
        if status == 401:
            raise NukiWebApiAuthError(f"{method} {path}: token rejected")
        if status == 403:
            raise NukiWebApiForbiddenError(status, message)
        if status == 429:
            raise NukiWebApiRateLimitError(status, message)
        if status >= 400:
            raise NukiWebApiResponseError(status, message)
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError as err:
            raise NukiWebApiResponseError(status, "invalid JSON answer") from err

    # Smart locks -----------------------------------------------------------

    async def async_get_smartlocks(self) -> list[dict[str, Any]]:
        """Return every device of the account."""
        return await self._request("GET", "/smartlock") or []

    async def async_get_smartlock(self, smartlock_id: int) -> dict[str, Any]:
        """Return one device with its state, config and advanced config."""
        return await self._request("GET", f"/smartlock/{smartlock_id}") or {}

    async def async_lock_action(
        self, smartlock_id: int, action: int, option: int = 0
    ) -> None:
        """Run a lock action. Option mask: 2 force, 4 full lock."""
        payload: dict[str, Any] = {"action": action}
        if option:
            payload["option"] = option
        await self._request(
            "POST", f"/smartlock/{smartlock_id}/action", payload=payload
        )

    async def async_sync(self, smartlock_id: int) -> None:
        """Ask the server to synchronise with the device."""
        await self._request("POST", f"/smartlock/{smartlock_id}/sync")

    async def async_update_config(
        self, smartlock_id: int, config: dict[str, Any]
    ) -> None:
        """Replace the config (the full object must be sent)."""
        await self._request(
            "POST", f"/smartlock/{smartlock_id}/config", payload=config
        )

    async def async_update_advanced_config(
        self, smartlock_id: int, advanced_config: dict[str, Any]
    ) -> None:
        """Replace the advanced config (the full object must be sent)."""
        await self._request(
            "POST",
            f"/smartlock/{smartlock_id}/advanced/config",
            payload=advanced_config,
        )

    # Authorizations --------------------------------------------------------

    async def async_get_auths(self, smartlock_id: int) -> list[dict[str, Any]]:
        """Return the authorizations (app users, fobs, keypad codes...)."""
        return await self._request("GET", f"/smartlock/{smartlock_id}/auth") or []

    async def async_create_auth(
        self, smartlock_id: int, data: dict[str, Any]
    ) -> None:
        """Create an authorization; applied asynchronously by the server."""
        await self._request("PUT", f"/smartlock/{smartlock_id}/auth", payload=data)

    async def async_update_auth(
        self, smartlock_id: int, auth_id: str, data: dict[str, Any]
    ) -> None:
        """Update an authorization; applied asynchronously by the server."""
        await self._request(
            "POST", f"/smartlock/{smartlock_id}/auth/{auth_id}", payload=data
        )

    async def async_delete_auth(self, smartlock_id: int, auth_id: str) -> None:
        """Delete an authorization; applied asynchronously by the server."""
        await self._request("DELETE", f"/smartlock/{smartlock_id}/auth/{auth_id}")

    # Activity log ----------------------------------------------------------

    async def async_get_logs(
        self, smartlock_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return the most recent log entries, newest first (max 50)."""
        return (
            await self._request(
                "GET",
                f"/smartlock/{smartlock_id}/log",
                params={"limit": max(1, min(limit, 50))},
            )
            or []
        )
