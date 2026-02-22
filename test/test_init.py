"""Tests for mytpu integration setup and coordinator."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.mytpu import (
    TPUDataUpdateCoordinator,
    _service_from_config,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.mytpu.const import CONF_TOKEN_DATA, DOMAIN
from custom_components.mytpu.models import Service, ServiceType, UsageReading


def test_service_from_config(mock_power_service):
    """Test reconstructing Service from JSON config."""
    service_json = json.dumps(
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

    service = _service_from_config(service_json)

    assert service.service_id == mock_power_service.service_id
    assert service.service_number == mock_power_service.service_number
    assert service.meter_number == mock_power_service.meter_number
    assert service.service_type == ServiceType.POWER


def test_service_from_config_minimal():
    """Test reconstructing Service with minimal fields."""
    service_json = json.dumps(
        {
            "service_id": "123",
            "service_number": "SVC",
            "meter_number": "MTR",
            "display_meter_number": "MTR",
            "service_type": "W",
        }
    )

    service = _service_from_config(service_json)

    assert service.service_id == "123"
    assert service.service_type == ServiceType.WATER
    assert service.totalizer is False


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant, mock_config_entry):
    """Test successful setup of config entry."""
    # Add the config entry to hass before setup
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.mytpu.MyTPUClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        with (
            patch.object(
                TPUDataUpdateCoordinator, "async_config_entry_first_refresh"
            ) as mock_refresh,
            # Mock the platform forwarding since we're testing the setup logic
            patch.object(
                hass.config_entries, "async_forward_entry_setups", return_value=None
            ) as mock_forward,
        ):
            result = await async_setup_entry(hass, mock_config_entry)

            assert result is True
            assert DOMAIN in hass.data
            assert mock_config_entry.entry_id in hass.data[DOMAIN]
            mock_refresh.assert_called_once()
            mock_forward.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_migration_auth_failure(
    hass: HomeAssistant, make_config_entry, mock_migration_client_and_auth
):
    """Test setup with config migration failing due to auth error."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    from custom_components.mytpu.auth import AuthError

    config_entry = make_config_entry(include_password=True)
    config_entry.add_to_hass(hass)

    mock_auth, mock_client = mock_migration_client_and_auth
    mock_auth.async_login = AsyncMock(side_effect=AuthError("Invalid credentials"))

    with (
        patch("custom_components.mytpu.MyTPUAuth", return_value=mock_auth),
        patch("custom_components.mytpu.MyTPUClient", return_value=mock_client),
        pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"),
    ):
        await async_setup_entry(hass, config_entry)


@pytest.mark.asyncio
async def test_async_setup_entry_migration_generic_failure(
    hass: HomeAssistant, make_config_entry, mock_migration_client_and_auth
):
    """Test setup with config migration failing due to generic error."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    config_entry = make_config_entry(include_password=True)
    config_entry.add_to_hass(hass)

    mock_auth, mock_client = mock_migration_client_and_auth
    mock_auth.async_login = AsyncMock(side_effect=RuntimeError("Network error"))

    with (
        patch("custom_components.mytpu.MyTPUAuth", return_value=mock_auth),
        patch("custom_components.mytpu.MyTPUClient", return_value=mock_client),
        pytest.raises(ConfigEntryAuthFailed, match="Failed to migrate config"),
    ):
        await async_setup_entry(hass, config_entry)


@pytest.mark.asyncio
async def test_async_unload_entry(hass: HomeAssistant, mock_config_entry):
    """Test unloading a config entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.client.close = AsyncMock()

    # Create a real asyncio task that can be cancelled and awaited
    async def dummy_task():
        try:
            await asyncio.sleep(3600)  # Sleep for a long time
        except asyncio.CancelledError:
            raise  # Re-raise so the test can verify cancellation handling

    mock_refresh_task = asyncio.create_task(dummy_task())

    hass.data[DOMAIN] = {
        mock_config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "refresh_task": mock_refresh_task,
        }
    }

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=True
    ) as mock_unload:
        result = await async_unload_entry(hass, mock_config_entry)

        assert result is True
        mock_unload.assert_called_once()
        mock_coordinator.client.close.assert_called_once()
        assert mock_config_entry.entry_id not in hass.data[DOMAIN]


class TestTPUDataUpdateCoordinator:
    """Test TPUDataUpdateCoordinator class."""

    def test_init_with_both_services(self, hass: HomeAssistant, mock_config_entry):
        """Test coordinator initialization with both services."""
        mock_client = MagicMock()

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, mock_config_entry)

        assert coordinator.client is mock_client
        assert coordinator.config_entry is mock_config_entry
        assert coordinator.power_service is not None
        assert coordinator.power_service.meter_number == "MOCK_POWER_METER"
        assert coordinator.water_service is not None
        assert coordinator.water_service.meter_number == "MOCK_WATER_METER"

    def test_init_power_only(self, hass: HomeAssistant, make_config_entry):
        """Test coordinator initialization with power service only."""
        mock_client = MagicMock()
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        assert coordinator.power_service is not None
        assert coordinator.water_service is None

    @pytest.mark.asyncio
    async def test_async_update_data_success(
        self,
        hass: HomeAssistant,
        mock_power_service,
        mock_water_service,
        mock_config_entry,
    ):
        """Test successful data update."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock()
        mock_client.get_token_data = MagicMock(return_value=None)

        power_readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2, tzinfo=UTC),
                consumption=28.3,
                unit="kWh",
            ),
        ]
        water_readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=1.5,
                unit="CCF",
            ),
        ]

        # Combine readings, or adjust mock if get_usage handles service types internally
        def mock_get_usage_side_effect(service, *args, **kwargs):
            if service.service_type == ServiceType.POWER:
                return power_readings
            if service.service_type == ServiceType.WATER:
                return water_readings
            return []

        mock_client.get_usage = AsyncMock(side_effect=mock_get_usage_side_effect)

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, mock_config_entry)

        with (
            patch("custom_components.mytpu.get_last_statistics", return_value={}),
            patch.object(
                coordinator, "_import_statistics", new=AsyncMock()
            ) as mock_import,
        ):
            data = await coordinator._async_update_data()

            assert "power" in data
            assert data["power"]["consumption"] == 28.3  # Latest reading
            assert data["power"]["date"] == datetime(2026, 1, 2, tzinfo=UTC)
            assert data["power"]["unit"] == "kWh"

            assert "water" in data
            assert data["water"]["consumption"] == 1.5
            assert data["water"]["unit"] == "CCF"

            # Verify statistics import was called
            assert mock_import.call_count == 2

    @pytest.mark.asyncio
    async def test_async_update_data_no_readings(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test data update with no readings."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock()
        mock_client.get_usage = AsyncMock(return_value=[])
        mock_client.get_token_data = MagicMock(return_value=None)
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with patch("custom_components.mytpu.get_last_statistics", return_value={}):
            data = await coordinator._async_update_data()

        assert data == {}

    @pytest.mark.asyncio
    async def test_async_update_data_error(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test data update with error."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(side_effect=Exception("API Error"))
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with pytest.raises(
            UpdateFailed, match="Unexpected error communicating with TPU: API Error"
        ):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_auth_error(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test data update with authentication error."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.mytpu.auth import AuthError

        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(side_effect=AuthError("Token expired"))
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_mytpu_error(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test data update with MyTPU API error."""
        from custom_components.mytpu.client import MyTPUError

        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(
            side_effect=MyTPUError("API request failed")
        )
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with pytest.raises(UpdateFailed, match="API request failed"):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_server_error_no_credentials(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test server error with no stored password triggers reauth immediately."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.mytpu.auth import ServerError

        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(
            side_effect=ServerError("MyTPU server error: 500")
        )
        # Entry has no stored password
        config_entry = make_config_entry(include_power=True)
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_server_error_relogin_success(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test server error triggers re-login, then retries data fetch successfully."""
        from custom_components.mytpu.auth import ServerError

        mock_client = AsyncMock()
        # First call raises ServerError, second (after re-login) succeeds
        mock_client.get_account_info = AsyncMock(side_effect=[ServerError("500"), {}])
        mock_client.get_usage = AsyncMock(return_value=[])
        mock_client.get_token_data = MagicMock(return_value=None)
        mock_client.async_login = AsyncMock()
        config_entry = make_config_entry(
            include_power=True, include_stored_password=True
        )
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with patch("custom_components.mytpu.get_last_statistics", return_value={}):
            data = await coordinator._async_update_data()

        mock_client.async_login.assert_called_once_with("user", "testpass")
        assert data == {}

    @pytest.mark.asyncio
    async def test_async_update_data_server_error_relogin_fails(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test server error where re-login fails triggers reauth."""
        from homeassistant.exceptions import ConfigEntryAuthFailed

        from custom_components.mytpu.auth import AuthError, ServerError

        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(
            side_effect=ServerError("MyTPU server error: 500")
        )
        mock_client.async_login = AsyncMock(side_effect=AuthError("Bad password"))
        config_entry = make_config_entry(
            include_power=True, include_stored_password=True
        )
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_save_token_data(self, hass: HomeAssistant, mock_config_entry):
        """Test that token data is saved to config entry."""
        import time

        mock_client = AsyncMock()
        token_data = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_at": time.time() + 3600,
            "customer_id": "CUST123",
        }
        mock_client.get_token_data = MagicMock(return_value=token_data)

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, mock_config_entry)

        # Mock async_update_entry
        with patch.object(
            hass.config_entries, "async_update_entry", new=MagicMock()
        ) as mock_update:
            await coordinator._save_token_data()

            # Should update config entry with new token data
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args.args[0] == mock_config_entry
            assert CONF_TOKEN_DATA in call_args.kwargs["data"]
            assert call_args.kwargs["data"][CONF_TOKEN_DATA] == token_data

    @pytest.mark.asyncio
    async def test_save_token_data_no_change(
        self, hass: HomeAssistant, mock_token_data
    ):
        """Test that token data is not saved if unchanged."""
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        config_entry = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            data={
                CONF_USERNAME: "user",
                CONF_TOKEN_DATA: mock_token_data,
            },
            unique_id="test_no_change",
            title="Test",
        )

        mock_client = AsyncMock()
        # Return same token data
        mock_client.get_token_data = MagicMock(return_value=mock_token_data)

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        with patch.object(
            hass.config_entries, "async_update_entry", new=MagicMock()
        ) as mock_update:
            await coordinator._save_token_data()

            # Should not update if data is unchanged
            mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_statistics_new_data(
        self, hass: HomeAssistant, mock_power_service, make_config_entry
    ):
        """Test importing new statistics."""
        mock_client = AsyncMock()
        config_entry = make_config_entry()
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2, tzinfo=UTC),
                consumption=28.3,
                unit="kWh",
            ),
        ]

        with (
            patch("custom_components.mytpu.get_last_statistics", return_value={}),
            patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats,
        ):
            await coordinator._import_statistics(mock_power_service, readings, "energy")

            mock_add_stats.assert_called_once()
            # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
            # call_args.args gives us the tuple of positional arguments
            args = mock_add_stats.call_args.args
            metadata = args[1]  # Second positional arg (metadata)
            statistics = args[2]  # Third positional arg (statistics)

            # Verify metadata (metadata is a dict)
            assert metadata["statistic_id"] == f"{DOMAIN}:p_mock_power_meter_energy"
            assert metadata["has_sum"] is True
            assert "TPU Energy" in metadata["name"]

            # Verify statistics (statistics items are dicts)
            # Now includes baseline statistic at the beginning
            assert len(statistics) == 3
            assert statistics[0]["state"] == 0.0
            assert statistics[0]["sum"] == 0.0  # Baseline
            assert statistics[1]["state"] == 25.5
            assert statistics[1]["sum"] == 25.5  # Cumulative
            assert statistics[2]["state"] == 28.3
            assert statistics[2]["sum"] == 53.8  # 25.5 + 28.3

    @pytest.mark.asyncio
    async def test_import_statistics_with_previous_data(
        self, hass: HomeAssistant, mock_power_service, make_config_entry
    ):
        """Test importing statistics with existing data."""
        mock_client = AsyncMock()
        config_entry = make_config_entry()
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 3, tzinfo=UTC),
                consumption=30.0,
                unit="kWh",
            ),
        ]

        # Mock existing statistics
        # start is returned as a Unix timestamp (float)
        last_stat_time = dt_util.as_utc(datetime(2026, 1, 2)).timestamp()
        mock_last_stats = {
            f"{DOMAIN}:p_mock_power_meter_energy": [
                {
                    "sum": 100.0,
                    "start": last_stat_time,
                }
            ]
        }

        with (
            patch(
                "custom_components.mytpu.get_last_statistics",
                return_value=mock_last_stats,
            ),
            patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats,
        ):
            await coordinator._import_statistics(mock_power_service, readings, "energy")

            mock_add_stats.assert_called_once()
            # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
            args = mock_add_stats.call_args.args
            statistics = args[2]  # Third positional arg (statistics)

            # Should only have 1 new statistic
            assert len(statistics) == 1
            # Sum should continue from previous (statistics items are dicts)
            assert statistics[0]["sum"] == 130.0  # 100.0 + 30.0

    @pytest.mark.asyncio
    async def test_import_statistics_skip_duplicates(
        self, hass: HomeAssistant, mock_power_service, make_config_entry
    ):
        """Test that duplicate dates are skipped."""
        mock_client = AsyncMock()
        config_entry = make_config_entry()
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2, tzinfo=UTC),
                consumption=28.3,
                unit="kWh",
            ),
        ]

        # Mock that we already have data up to Jan 2
        # start is returned as a Unix timestamp (float)
        last_stat_time = dt_util.as_utc(datetime(2026, 1, 2)).timestamp()
        mock_last_stats = {
            f"{DOMAIN}:p_mock_power_meter_energy": [
                {
                    "sum": 100.0,
                    "start": last_stat_time,
                }
            ]
        }

        with (
            patch(
                "custom_components.mytpu.get_last_statistics",
                return_value=mock_last_stats,
            ),
            patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats,
        ):
            await coordinator._import_statistics(mock_power_service, readings, "energy")

            # Should not add any statistics (all duplicates)
            mock_add_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_statistics_water(
        self, hass: HomeAssistant, mock_water_service, make_config_entry
    ):
        """Test importing water statistics."""
        mock_client = AsyncMock()
        config_entry = make_config_entry()
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=1.5,
                unit="CCF",
            ),
        ]

        with (
            patch("custom_components.mytpu.get_last_statistics", return_value={}),
            patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats,
        ):
            await coordinator._import_statistics(mock_water_service, readings, "water")

            mock_add_stats.assert_called_once()
            # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
            # call_args.args gives us the tuple of positional arguments
            args = mock_add_stats.call_args.args
            metadata = args[1]  # Second positional arg (metadata)
            args[2]  # Third positional arg (statistics)

            # Verify metadata for water (metadata is a dict)
            assert metadata["statistic_id"] == f"{DOMAIN}:w_mock_water_meter_water"
            assert "TPU Water" in metadata["name"]
            assert metadata["unit_class"] == "volume"

    @pytest.mark.asyncio
    async def test_import_statistics_meter_id_sanitization(
        self, hass: HomeAssistant, make_config_entry
    ):
        """Test that meter IDs with hyphens are sanitized."""
        mock_client = AsyncMock()
        config_entry = make_config_entry()
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config_entry)

        service = Service(
            service_id="123",
            service_number="SVC",
            meter_number="MTR-123-ABC",
            display_meter_number="MTR-123-ABC",
            service_type=ServiceType.POWER,
        )

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1, tzinfo=UTC),
                consumption=10.0,
                unit="kWh",
            ),
        ]

        with (
            patch("custom_components.mytpu.get_last_statistics", return_value={}),
            patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats,
        ):
            await coordinator._import_statistics(service, readings, "energy")

            # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
            # call_args.args gives us the tuple of positional arguments
            args = mock_add_stats.call_args.args
            metadata = args[1]  # Second positional arg (metadata)

            # Hyphens should be replaced with underscores and lowercased (metadata is a dict)
            assert metadata["statistic_id"] == f"{DOMAIN}:p_mtr_123_abc_energy"
