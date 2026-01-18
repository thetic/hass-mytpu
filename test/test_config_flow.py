"""Tests for mytpu config flow."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mytpu.auth import AuthError
from custom_components.mytpu.config_flow import (
    CannotConnect,
    InvalidAuth,
    validate_and_fetch_services,
)
from custom_components.mytpu.const import CONF_POWER_SERVICE, CONF_WATER_SERVICE, DOMAIN
from custom_components.mytpu.models import Service, ServiceType


@pytest.mark.asyncio
async def test_validate_and_fetch_services_success(
    hass: HomeAssistant, mock_credentials, mock_account_info
):
    """Test successful credential validation and service fetch."""
    with patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get_account_info.return_value = mock_account_info
        mock_client.get_services.return_value = [
            Service(
                service_id="123",
                service_number="SVC001",
                meter_number="MOCK_POWER_METER",
                display_meter_number="MOCK_POWER_METER",
                service_type=ServiceType.POWER,
            ),
        ]
        mock_client_class.return_value = mock_client

        info, services = await validate_and_fetch_services(hass, mock_credentials)

        assert info["title"] == "TPU - Test User"
        assert len(services) == 1
        assert services[0].meter_number == "MOCK_POWER_METER"


@pytest.mark.asyncio
async def test_validate_and_fetch_services_auth_error(
    hass: HomeAssistant, mock_credentials
):
    """Test validation with invalid credentials."""
    with patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get_account_info.side_effect = AuthError("Invalid credentials")
        mock_client_class.return_value = mock_client

        with pytest.raises(InvalidAuth):
            await validate_and_fetch_services(hass, mock_credentials)


@pytest.mark.asyncio
async def test_validate_and_fetch_services_connection_error(
    hass: HomeAssistant, mock_credentials
):
    """Test validation with connection error."""
    with patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get_account_info.side_effect = Exception("Connection failed")
        mock_client_class.return_value = mock_client

        with pytest.raises(CannotConnect):
            await validate_and_fetch_services(hass, mock_credentials)


class TestTPUConfigFlow:
    """Test TPU config flow."""

    @pytest.mark.asyncio
    async def test_form_user_step(self, hass: HomeAssistant):
        """Test we get the form for user step."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_user_step_success(
        self, hass: HomeAssistant, mock_credentials, mock_account_info
    ):
        """Test successful user step with valid credentials."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = (
                {"title": "TPU - Test User"},
                [
                    Service(
                        service_id="123",
                        service_number="SVC001",
                        meter_number="MOCK_POWER_METER",
                        display_meter_number="MOCK_POWER_METER",
                        service_type=ServiceType.POWER,
                    ),
                ],
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "meters"
            assert "errors" not in result or result["errors"] in (None, {})

    @pytest.mark.asyncio
    async def test_user_step_cannot_connect(
        self, hass: HomeAssistant, mock_credentials
    ):
        """Test user step with connection error."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.side_effect = CannotConnect

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_user_step_invalid_auth(self, hass: HomeAssistant, mock_credentials):
        """Test user step with invalid credentials."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.side_effect = InvalidAuth

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_user_step_unknown_error(self, hass: HomeAssistant, mock_credentials):
        """Test user step with unexpected error."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.side_effect = Exception("Unexpected")

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "unknown"}

    @pytest.mark.asyncio
    async def test_meters_step_both_services(
        self,
        hass: HomeAssistant,
        mock_credentials,
        mock_power_service,
        mock_water_service,
    ):
        """Test meters step selecting both power and water."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = (
                {"title": "TPU - Test User"},
                [mock_power_service, mock_water_service],
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "meters"

            # Select both services
            power_json = json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                    "latitude": mock_power_service.latitude,
                    "longitude": mock_power_service.longitude,
                    "contract_number": mock_power_service.contract_number,
                    "totalizer": mock_power_service.totalizer,
                }
            )
            water_json = json.dumps(
                {
                    "service_id": mock_water_service.service_id,
                    "service_number": mock_water_service.service_number,
                    "meter_number": mock_water_service.meter_number,
                    "display_meter_number": mock_water_service.display_meter_number,
                    "service_type": mock_water_service.service_type.value,
                    "latitude": mock_water_service.latitude,
                    "longitude": mock_water_service.longitude,
                    "contract_number": mock_water_service.contract_number,
                    "totalizer": mock_water_service.totalizer,
                }
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_POWER_SERVICE: power_json,
                    CONF_WATER_SERVICE: water_json,
                },
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert result["title"] == "TPU - Test User"
            assert CONF_USERNAME in result["data"]
            assert CONF_PASSWORD in result["data"]
            assert CONF_POWER_SERVICE in result["data"]
            assert CONF_WATER_SERVICE in result["data"]

    @pytest.mark.asyncio
    async def test_meters_step_power_only(
        self, hass: HomeAssistant, mock_credentials, mock_power_service
    ):
        """Test meters step selecting only power service."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = (
                {"title": "TPU - Test User"},
                [mock_power_service],
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            power_json = json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                    "latitude": mock_power_service.latitude,
                    "longitude": mock_power_service.longitude,
                    "contract_number": mock_power_service.contract_number,
                    "totalizer": mock_power_service.totalizer,
                }
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_POWER_SERVICE: power_json,
                },
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert CONF_POWER_SERVICE in result["data"]
            assert CONF_WATER_SERVICE not in result["data"]

    @pytest.mark.asyncio
    async def test_meters_step_water_only(
        self, hass: HomeAssistant, mock_credentials, mock_water_service
    ):
        """Test meters step selecting only water service."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = (
                {"title": "TPU - Test User"},
                [mock_water_service],
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            water_json = json.dumps(
                {
                    "service_id": mock_water_service.service_id,
                    "service_number": mock_water_service.service_number,
                    "meter_number": mock_water_service.meter_number,
                    "display_meter_number": mock_water_service.display_meter_number,
                    "service_type": mock_water_service.service_type.value,
                    "latitude": mock_water_service.latitude,
                    "longitude": mock_water_service.longitude,
                    "contract_number": mock_water_service.contract_number,
                    "totalizer": mock_water_service.totalizer,
                }
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    CONF_WATER_SERVICE: water_json,
                },
            )

            assert result["type"] == FlowResultType.CREATE_ENTRY
            assert CONF_WATER_SERVICE in result["data"]
            assert CONF_POWER_SERVICE not in result["data"]

    @pytest.mark.asyncio
    async def test_meters_step_no_selection(
        self, hass: HomeAssistant, mock_credentials, mock_power_service
    ):
        """Test meters step with no meter selected."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = (
                {"title": "TPU - Test User"},
                [mock_power_service],
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            # Submit meters form with no selection
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "meters"
            assert result["errors"] == {"base": "no_meters"}
