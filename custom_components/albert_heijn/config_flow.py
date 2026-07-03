"""Config flow for the Albert Heijn integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AhApiClient, AhApiError, AhAuthError
from .const import AUTHORIZE_URL, CONF_CODE, CONF_MEMBER_ID, CONF_REFRESH_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


def extract_code(value: str) -> str:
    """Accept either a raw code or the full ``appie://login-exit?code=...`` URL."""
    value = value.strip()
    if "code=" not in value:
        return value
    codes = parse_qs(urlsplit(value).query).get("code")
    return codes[0] if codes else value


class AhConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Albert Heijn config flow."""

    VERSION = 1

    async def _async_validate_code(self, raw_input: str) -> dict[str, str]:
        """Exchange the pasted code for tokens; returns the entry data."""
        client = AhApiClient(async_get_clientsession(self.hass))
        refresh_token = await client.async_exchange_code(extract_code(raw_input))
        member_id = await client.async_get_member_id()
        return {CONF_REFRESH_TOKEN: refresh_token, CONF_MEMBER_ID: member_id}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Initial step: user pastes the login code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await self._async_validate_code(user_input[CONF_CODE])
            except AhAuthError:
                errors["base"] = "invalid_auth"
            except AhApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating login code")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(data[CONF_MEMBER_ID])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Albert Heijn", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"authorize_url": AUTHORIZE_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Reauth entry point when the refresh token stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a fresh login code and update the existing entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            try:
                data = await self._async_validate_code(user_input[CONF_CODE])
            except AhAuthError:
                errors["base"] = "invalid_auth"
            except AhApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating login code")
                errors["base"] = "unknown"
            else:
                if reauth_entry.unique_id and data[CONF_MEMBER_ID] != reauth_entry.unique_id:
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(reauth_entry, data_updates=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"authorize_url": AUTHORIZE_URL},
        )
