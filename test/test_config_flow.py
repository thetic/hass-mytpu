"""Tests for mytpu config flow."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol  # Import voluptuous
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mytpu.auth import AuthError
from custom_components.mytpu.config_flow import (
    CannotConnect,
    InvalidAuth,
    TPUOptionsFlow,
    ValidationResult,
    validate_and_fetch_services,
)
from custom_components.mytpu.const import (
    CONF_POWER_SERVICE,
    CONF_TOKEN_DATA,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_WATER_SERVICE,
    DOMAIN,
)
from custom_components.mytpu.models import Service, ServiceType


@pytest.mark.asyncio
async def test_validate_and_fetch_services_success(
    hass: HomeAssistant, mock_credentials, mock_account_info, mock_token_data
):
    """Test successful credential validation and service fetch."""
    with (
        patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
        patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class,
    ):
        # Mock the auth instance - use MagicMock for synchronous methods
        mock_auth = MagicMock()
        mock_auth.async_login = AsyncMock()
        mock_auth.get_token_data = MagicMock(return_value=mock_token_data)
        mock_auth_class.return_value = mock_auth

        # Mock the client instance
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client._session = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_services = AsyncMock(
            return_value=[
                Service(
                    service_id="123",
                    service_number="SVC001",
                    meter_number="MOCK_POWER_METER",
                    display_meter_number="MOCK_POWER_METER",
                    service_type=ServiceType.POWER,
                ),
            ]
        )
        mock_client_class.return_value = mock_client

        validation_result = await validate_and_fetch_services(hass, mock_credentials)

        assert validation_result.title == "TPU - Test User"
        assert len(validation_result.services) == 1
        assert validation_result.services[0].meter_number == "MOCK_POWER_METER"
        assert validation_result.token_data == mock_token_data


@pytest.mark.asyncio
async def test_validate_and_fetch_services_auth_error(
    hass: HomeAssistant, mock_credentials
):
    """Test validation with invalid credentials."""
    with (
        patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
        patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class,
    ):
        # Mock the auth instance
        mock_auth = MagicMock()
        mock_auth.async_login = AsyncMock(side_effect=AuthError("Invalid credentials"))
        mock_auth.get_token_data = MagicMock(return_value=None)
        mock_auth_class.return_value = mock_auth

        # Mock the client instance
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client._session = AsyncMock()
        mock_client_class.return_value = mock_client

        with pytest.raises(InvalidAuth):
            await validate_and_fetch_services(hass, mock_credentials)


@pytest.mark.asyncio
async def test_validate_and_fetch_services_connection_error(
    hass: HomeAssistant, mock_credentials, mock_token_data
):
    """Test validation with connection error."""
    with (
        patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
        patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class,
    ):
        mock_auth = MagicMock()
        mock_auth.get_token_data = MagicMock(return_value=mock_token_data)
        mock_auth_class.return_value = mock_auth

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get_account_info = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        mock_client_class.return_value = mock_client

        with pytest.raises(CannotConnect):
            await validate_and_fetch_services(hass, mock_credentials)


@pytest.mark.asyncio
async def test_validate_and_fetch_services_session_none_for_login(
    hass: HomeAssistant, mock_credentials
):
    """Test validation when client session is None during async_login attempt."""
    with (
        patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
        patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class,
    ):
        mock_auth = MagicMock()
        mock_auth.async_login = AsyncMock()  # This won't be called if session is None
        mock_auth.get_token_data = MagicMock(return_value=None)
        mock_auth_class.return_value = mock_auth

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client._session = None  # Simulate session being None
        mock_client_class.return_value = mock_client

        with pytest.raises(CannotConnect):
            await validate_and_fetch_services(hass, mock_credentials)


@pytest.mark.asyncio
async def test_validate_and_fetch_services_no_token_data(
    hass: HomeAssistant, mock_credentials, mock_account_info
):
    """Test validation when no token data is returned after successful login."""
    with (
        patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
        patch("custom_components.mytpu.config_flow.MyTPUClient") as mock_client_class,
    ):
        mock_auth = MagicMock()
        mock_auth.async_login = AsyncMock()
        mock_auth.get_token_data = MagicMock(
            return_value=None
        )  # Simulate no token data
        mock_auth_class.return_value = mock_auth

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client._session = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_services = AsyncMock(
            return_value=[]
        )  # Not relevant for this specific test branch
        mock_client_class.return_value = mock_client

        with pytest.raises(InvalidAuth):  # Removed match=...
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
        self, hass: HomeAssistant, mock_credentials, mock_account_info, mock_token_data
    ):
        """Test successful user step with valid credentials."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title="TPU - Test User",
                services=[
                    Service(
                        service_id="123",
                        service_number="SVC001",
                        meter_number="MOCK_POWER_METER",
                        display_meter_number="MOCK_POWER_METER",
                        service_type=ServiceType.POWER,
                    ),
                ],
                token_data=mock_token_data,
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
    async def test_user_step_abort_if_unique_id_configured(
        self, hass: HomeAssistant, mock_credentials, mock_token_data
    ):
        """Test user step when unique_id is already configured."""
        mock_title = "TPU - Existing User"
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=mock_title,
            data={CONF_USERNAME: "existing_user", CONF_TOKEN_DATA: mock_token_data},
            title=mock_title,
        )
        mock_config_entry.add_to_hass(hass)

        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title=mock_title,  # Same title as existing entry
                services=[],
                token_data=mock_token_data,
            )

            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                mock_credentials,
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "already_configured"

    @pytest.mark.asyncio
    async def test_meters_step_both_services(
        self,
        hass: HomeAssistant,
        mock_credentials,
        mock_token_data,
        mock_power_service,
        mock_water_service,
    ):
        """Test meters step selecting both power and water."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title="TPU - Test User",
                services=[mock_power_service, mock_water_service],
                token_data=mock_token_data,
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
            assert CONF_TOKEN_DATA in result["data"]
            assert CONF_POWER_SERVICE in result["data"]
            assert CONF_WATER_SERVICE in result["data"]

    @pytest.mark.asyncio
    async def test_meters_step_power_only(
        self, hass: HomeAssistant, mock_credentials, mock_token_data, mock_power_service
    ):
        """Test meters step selecting only power service."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title="TPU - Test User",
                services=[mock_power_service],
                token_data=mock_token_data,
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
        self, hass: HomeAssistant, mock_credentials, mock_token_data, mock_water_service
    ):
        """Test meters step selecting only water service."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title="TPU - Test User",
                services=[mock_water_service],
                token_data=mock_token_data,
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
        self, hass: HomeAssistant, mock_credentials, mock_token_data, mock_power_service
    ):
        """Test meters step with no meter selected."""
        with patch(
            "custom_components.mytpu.config_flow.validate_and_fetch_services"
        ) as mock_validate:
            mock_validate.return_value = ValidationResult(
                title="TPU - Test User",
                services=[mock_power_service],
                token_data=mock_token_data,
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

    @pytest.mark.asyncio
    async def test_reauth_confirm_success(
        self, hass: HomeAssistant, mock_credentials, mock_account_info, mock_token_data
    ):
        """Test successful re-authentication."""

        # Setup a mock config entry that needs reauth
        entry_id = "test_reauth_entry"
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="TPU - Test User",
            data={
                CONF_USERNAME: mock_credentials[CONF_USERNAME],
                CONF_POWER_SERVICE: '{"meter_number": "existing_power"}',
            },
            entry_id=entry_id,
        )
        mock_config_entry.add_to_hass(hass)

        # Start reauth flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry_id},
            data=mock_config_entry.data,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        with (
            patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
            patch(
                "custom_components.mytpu.config_flow.MyTPUClient"
            ) as mock_client_class,
            patch.object(
                hass.config_entries, "async_update_entry"
            ) as mock_update_entry,
            patch.object(
                hass.config_entries, "async_schedule_reload"
            ) as mock_schedule_reload,
        ):
            mock_auth = AsyncMock()
            mock_auth.async_login = AsyncMock()
            mock_auth.get_token_data = MagicMock(return_value=mock_token_data)
            mock_auth_class.return_value = mock_auth

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client._session = AsyncMock()
            mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
            mock_client_class.return_value = mock_client

            # Submit credentials to reauth form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: mock_credentials[CONF_PASSWORD]},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "reauth_successful"
            mock_update_entry.assert_called_once()
            mock_schedule_reload.assert_called_once_with(entry_id)

            # Verify the updated entry data preserves existing services
            updated_data = mock_update_entry.call_args.kwargs["data"]
            assert updated_data[CONF_USERNAME] == mock_credentials[CONF_USERNAME]
            assert updated_data[CONF_TOKEN_DATA] == mock_token_data
            assert (
                updated_data[CONF_POWER_SERVICE] == '{"meter_number": "existing_power"}'
            )
            assert CONF_WATER_SERVICE not in updated_data

    @pytest.mark.asyncio
    async def test_reauth_confirm_invalid_auth(
        self, hass: HomeAssistant, mock_credentials
    ):
        """Test re-authentication with invalid credentials."""

        # Setup a mock config entry that needs reauth
        entry_id = "test_reauth_entry_invalid"
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="TPU - Existing User Invalid",
            data={CONF_USERNAME: mock_credentials[CONF_USERNAME]},
            entry_id=entry_id,
        )
        mock_config_entry.add_to_hass(hass)

        # Start reauth flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry_id},
            data=mock_config_entry.data,
        )

        with (
            patch("custom_components.mytpu.config_flow.MyTPUAuth") as mock_auth_class,
            patch(
                "custom_components.mytpu.config_flow.MyTPUClient"
            ) as mock_client_class,
        ):
            mock_auth = AsyncMock()
            # This is the line that needs to cause AuthError for InvalidAuth
            mock_auth.async_login = AsyncMock(
                side_effect=AuthError("Invalid credentials")
            )
            mock_auth.get_token_data = MagicMock(return_value=None)
            mock_auth_class.return_value = mock_auth

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client._session = AsyncMock()
            mock_client_class.return_value = mock_client

            # Submit invalid credentials to reauth form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: "wrong_password"},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_reauth_confirm_cannot_connect(
        self, hass: HomeAssistant, mock_credentials
    ):
        """Test re-authentication with connection error."""

        # Setup a mock config entry that needs reauth
        entry_id = "test_reauth_entry_connect_error"
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="TPU - Existing User Connect Error",
            data={CONF_USERNAME: mock_credentials[CONF_USERNAME]},
            entry_id=entry_id,
        )
        mock_config_entry.add_to_hass(hass)

        # Start reauth flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry_id},
            data=mock_config_entry.data,
        )

        with (
            patch(
                "custom_components.mytpu.config_flow.MyTPUClient"
            ) as mock_client_class,
            patch(
                "custom_components.mytpu.config_flow.MyTPUAuth"
            ) as mock_auth_class,  # Need auth mock too
        ):
            mock_auth = AsyncMock()
            mock_auth.async_login = AsyncMock()  # Successful login for this path
            mock_auth.get_token_data = MagicMock(
                return_value={"some_token": "data"}
            )  # Needs token data
            mock_auth_class.return_value = mock_auth

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client._session = AsyncMock()
            mock_client.get_account_info = AsyncMock(side_effect=CannotConnect)
            mock_client_class.return_value = mock_client

            # Submit credentials to reauth form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: mock_credentials[CONF_PASSWORD]},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_reauth_confirm_unexpected_error(
        self, hass: HomeAssistant, mock_credentials
    ):
        """Test re-authentication with an unexpected error."""

        # Setup a mock config entry that needs reauth
        entry_id = "test_reauth_entry_unexpected_error"
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="TPU - Existing User Unexpected Error",
            data={CONF_USERNAME: mock_credentials[CONF_USERNAME]},
            entry_id=entry_id,
        )
        mock_config_entry.add_to_hass(hass)

        # Start reauth flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry_id},
            data=mock_config_entry.data,
        )

        with (
            patch(
                "custom_components.mytpu.config_flow.MyTPUClient"
            ) as mock_client_class,
            patch(
                "custom_components.mytpu.config_flow.MyTPUAuth"
            ) as mock_auth_class,  # Need auth mock too
        ):
            mock_auth = AsyncMock()
            mock_auth.async_login = AsyncMock()
            mock_auth.get_token_data = MagicMock(return_value={"some_token": "data"})
            mock_auth_class.return_value = mock_auth

            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client._session = AsyncMock()
            mock_client.get_account_info = AsyncMock(
                side_effect=TypeError("Unexpected Error")
            )
            mock_client_class.return_value = mock_client

            # Submit credentials to reauth form
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: mock_credentials[CONF_PASSWORD]},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["errors"] == {"base": "unknown"}


class TestTPUOptionsFlow:
    """Test TPU options flow."""

    @pytest.mark.asyncio
    async def test_options_flow_init(self, hass: HomeAssistant):
        """Test the initialization of the options flow."""
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="test_options",
            data={CONF_USERNAME: "user"},
            options={CONF_UPDATE_INTERVAL_HOURS: 5},
        )
        flow = TPUOptionsFlow(mock_config_entry)

        result = await flow.async_step_init()
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"
        assert result["errors"] is None

        # Find the vol.Optional key corresponding to CONF_UPDATE_INTERVAL_HOURS
        assert result["data_schema"] is not None
        optional_key = next(
            (
                k
                for k in result["data_schema"].schema
                if isinstance(k, vol.Optional)
                and k.schema == CONF_UPDATE_INTERVAL_HOURS
            ),
            None,
        )
        assert optional_key is not None
        assert optional_key.default() == 5

    @pytest.mark.asyncio
    async def test_options_flow_update(self, hass: HomeAssistant):
        """Test updating options."""
        mock_config_entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="test_options_update",
            data={CONF_USERNAME: "user"},
            options={CONF_UPDATE_INTERVAL_HOURS: 5},
        )
        flow = TPUOptionsFlow(mock_config_entry)

        result = await flow.async_step_init(user_input={CONF_UPDATE_INTERVAL_HOURS: 10})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_UPDATE_INTERVAL_HOURS] == 10
        assert (
            mock_config_entry.options[CONF_UPDATE_INTERVAL_HOURS] == 5
        )  # Original entry options should not change yet
