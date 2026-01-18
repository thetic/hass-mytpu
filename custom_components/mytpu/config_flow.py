"""Config flow for Tacoma Public Utilities integration."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

from .auth import AuthError
from .client import MyTPUClient
from .const import CONF_POWER_SERVICE, CONF_WATER_SERVICE, DOMAIN
from .models import Service, ServiceType

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_and_fetch_services(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[dict[str, Any], list[Service]]:
    """Validate credentials and fetch available services."""
    client = MyTPUClient(data[CONF_USERNAME], data[CONF_PASSWORD])

    try:
        async with client:
            account_info = await client.get_account_info()
            account_holder = account_info.get("accountContext", {}).get(
                "accountHolder", "Unknown"
            )
            services = await client.get_services()
            return {"title": f"TPU - {account_holder}"}, services
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
        self._services: list[Service] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info, services = await validate_and_fetch_services(
                    self.hass, user_input
                )
                self._data = user_input
                self._data["title"] = info["title"]
                self._services = services
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


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
