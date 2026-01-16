"""Config flow for Tacoma Public Utilities integration."""

from __future__ import annotations

import logging

# Import the mytpu library
import sys
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_POWER_METER,
    CONF_POWER_SERVICE_ID,
    CONF_POWER_SERVICE_NUMBER,
    CONF_WATER_METER,
    CONF_WATER_SERVICE_ID,
    CONF_WATER_SERVICE_NUMBER,
    DOMAIN,
)

_lib_path = Path(__file__).parent.parent.parent.parent
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from mytpu import MyTPUClient  # noqa: E402
from mytpu.auth import AuthError  # noqa: E402

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_METERS_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_POWER_METER): str,
        vol.Optional(CONF_POWER_SERVICE_ID): str,
        vol.Optional(CONF_POWER_SERVICE_NUMBER): str,
        vol.Optional(CONF_WATER_METER): str,
        vol.Optional(CONF_WATER_SERVICE_ID): str,
        vol.Optional(CONF_WATER_SERVICE_NUMBER): str,
    }
)


async def validate_credentials(
    hass: HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user credentials."""
    client = MyTPUClient(data[CONF_USERNAME], data[CONF_PASSWORD])

    try:
        async with client:
            account_info = await client.get_account_info()
            account_holder = account_info.get("accountContext", {}).get(
                "accountHolder", "Unknown"
            )
            return {"title": f"TPU - {account_holder}"}
    except AuthError as err:
        raise InvalidAuth from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during validation")
        raise CannotConnect from err


class TPUConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tacoma Public Utilities."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_credentials(self.hass, user_input)
                self._data = user_input
                self._data["title"] = info["title"]
                return await self.async_step_meters()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_meters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the meters configuration step."""
        if user_input is not None:
            self._data.update(user_input)

            # Ensure at least one meter is configured
            if not user_input.get(CONF_POWER_METER) and not user_input.get(
                CONF_WATER_METER
            ):
                return self.async_show_form(
                    step_id="meters",
                    data_schema=STEP_METERS_DATA_SCHEMA,
                    errors={"base": "no_meters"},
                )

            return self.async_create_entry(
                title=self._data.pop("title"),
                data=self._data,
            )

        return self.async_show_form(
            step_id="meters",
            data_schema=STEP_METERS_DATA_SCHEMA,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
