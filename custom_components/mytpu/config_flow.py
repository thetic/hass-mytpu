"""Config flow for Tacoma Public Utilities integration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

from .auth import AuthError, MyTPUAuth
from .client import MyTPUClient
from .const import (
    CONF_POWER_SERVICE,
    CONF_TOKEN_DATA,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_WATER_SERVICE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
from .models import Service, ServiceType

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


@dataclass
class ValidationResult:
    """Result of validating credentials and fetching services."""

    title: str
    services: list[Service]
    token_data: dict


async def validate_and_fetch_services(
    hass: HomeAssistant, data: dict[str, Any]
) -> ValidationResult:
    """Validate credentials and fetch available services."""
    auth = MyTPUAuth(token_data=data.get(CONF_TOKEN_DATA))
    client = MyTPUClient(auth)

    try:
        async with client:
            # If token_data is not present, or refresh fails, perform full login
            if not auth.get_token_data():
                if client._session is None:
                    raise CannotConnect
                await auth.async_login(
                    data[CONF_USERNAME], data[CONF_PASSWORD], client._session
                )

            account_info = await client.get_account_info()
            account_holder = account_info.get("accountContext", {}).get(
                "accountHolder", "Unknown"
            )
            services = await client.get_services()
            token_data = auth.get_token_data()
            if token_data is None:
                raise AuthError("Authentication failed to produce token data")
            return ValidationResult(
                title=f"TPU - {account_holder}",
                services=services,
                token_data=token_data,
            )
    except AuthError as err:
        _LOGGER.debug("Authentication failed: %s", err)
        raise InvalidAuth from err
    except Exception as err:
        _LOGGER.exception("Unexpected error during validation")
        raise CannotConnect from err


class TPUConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tacoma Public Utilities."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return TPUOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._services: list[Service] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                validation_result = await validate_and_fetch_services(
                    self.hass, user_input
                )
                await self.async_set_unique_id(validation_result.title)
                self._abort_if_unique_id_configured()

                self._data = {
                    "title": validation_result.title,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_TOKEN_DATA: validation_result.token_data,
                }
                self._services = validation_result.services
                return await self.async_step_meters()
            except AbortFlow:
                return self.async_abort(reason="already_configured")
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
        """Handle the meters selection step."""
        if user_input is not None:
            # Store selected services as JSON
            if user_input.get(CONF_POWER_SERVICE):
                self._data[CONF_POWER_SERVICE] = user_input[CONF_POWER_SERVICE]
            if user_input.get(CONF_WATER_SERVICE):
                self._data[CONF_WATER_SERVICE] = user_input[CONF_WATER_SERVICE]

            # Ensure at least one meter is configured
            if not self._data.get(CONF_POWER_SERVICE) and not self._data.get(
                CONF_WATER_SERVICE
            ):
                return self.async_show_form(
                    step_id="meters",
                    data_schema=self._build_meters_schema(),
                    errors={"base": "no_meters"},
                )

            return self.async_create_entry(
                title=self._data.pop("title"),
                data=self._data,
            )

        return self.async_show_form(
            step_id="meters",
            data_schema=self._build_meters_schema(),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication."""
        self._data = entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication confirmation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                username = self._data[CONF_USERNAME]
                password = user_input[CONF_PASSWORD]

                auth = MyTPUAuth()
                async with MyTPUClient(auth) as client:
                    if client._session is None:
                        raise CannotConnect
                    await auth.async_login(username, password, client._session)
                    # Get account info to verify authentication
                    await client.get_account_info()

                new_data = {
                    CONF_USERNAME: username,
                    CONF_TOKEN_DATA: auth.get_token_data(),
                }

                # Preserve existing selected services
                if self._data.get(CONF_POWER_SERVICE):
                    new_data[CONF_POWER_SERVICE] = self._data[CONF_POWER_SERVICE]
                if self._data.get(CONF_WATER_SERVICE):
                    new_data[CONF_WATER_SERVICE] = self._data[CONF_WATER_SERVICE]

                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                if entry:
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(self.context["entry_id"])
                return self.async_abort(reason="reauth_successful")

            except AuthError:  # direct login failures
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=self._data.get(CONF_USERNAME, "")
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={"username": self._data.get(CONF_USERNAME, "")},
        )

    def _build_meters_schema(self) -> vol.Schema:
        """Build the meters selection schema based on available services."""
        power_meters = [
            s for s in self._services if s.service_type == ServiceType.POWER
        ]
        water_meters = [
            s for s in self._services if s.service_type == ServiceType.WATER
        ]

        schema_dict: dict[Any, Any] = {}

        if power_meters:
            power_options = {
                self._service_to_json(s): s.display_meter_number for s in power_meters
            }
            schema_dict[vol.Optional(CONF_POWER_SERVICE)] = vol.In(power_options)

        if water_meters:
            water_options = {
                self._service_to_json(s): s.display_meter_number for s in water_meters
            }
            schema_dict[vol.Optional(CONF_WATER_SERVICE)] = vol.In(water_options)

        return vol.Schema(schema_dict)

    def _service_to_json(self, service: Service) -> str:
        """Serialize a service to JSON for storage."""
        return json.dumps(
            {
                "service_id": service.service_id,
                "service_number": service.service_number,
                "meter_number": service.meter_number,
                "display_meter_number": service.display_meter_number,
                "service_type": service.service_type.value,
                "latitude": service.latitude,
                "longitude": service.longitude,
                "contract_number": service.contract_number,
                "totalizer": service.totalizer,
            }
        )


class TPUOptionsFlow(OptionsFlow):
    """Handle an options flow for Tacoma Public Utilities."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step of the options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL_HOURS,
                    default=self._config_entry.options.get(
                        CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
                    ),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
