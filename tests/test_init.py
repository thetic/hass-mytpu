"""Tests for mytpu integration setup and coordinator."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.mytpu import (
    TPUDataUpdateCoordinator,
    _service_from_config,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.mytpu.const import (
    CONF_POWER_SERVICE,
    CONF_WATER_SERVICE,
    DOMAIN,
)
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

        with patch.object(
            TPUDataUpdateCoordinator, "async_config_entry_first_refresh"
        ) as mock_refresh:
            # Mock the platform forwarding since we're testing the setup logic
            with patch.object(
                hass.config_entries, "async_forward_entry_setups", return_value=None
            ) as mock_forward:
                result = await async_setup_entry(hass, mock_config_entry)

                assert result is True
                assert DOMAIN in hass.data
                assert mock_config_entry.entry_id in hass.data[DOMAIN]
                mock_refresh.assert_called_once()
                mock_forward.assert_called_once()


@pytest.mark.asyncio
async def test_async_unload_entry(hass: HomeAssistant, mock_config_entry):
    """Test unloading a config entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.client.close = AsyncMock()
    hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}

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

    def test_init_with_both_services(self, hass: HomeAssistant):
        """Test coordinator initialization with both services."""
        mock_client = MagicMock()
        config = {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": "123",
                    "service_number": "SVC001",
                    "meter_number": "MOCK_POWER_METER",
                    "display_meter_number": "MOCK_POWER_METER",
                    "service_type": "P",
                }
            ),
            CONF_WATER_SERVICE: json.dumps(
                {
                    "service_id": "456",
                    "service_number": "SVC002",
                    "meter_number": "MOCK_WATER_METER",
                    "display_meter_number": "MOCK_WATER_METER",
                    "service_type": "W",
                }
            ),
        }

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        assert coordinator.client is mock_client
        assert coordinator.power_service is not None
        assert coordinator.power_service.meter_number == "MOCK_POWER_METER"
        assert coordinator.water_service is not None
        assert coordinator.water_service.meter_number == "MOCK_WATER_METER"

    def test_init_power_only(self, hass: HomeAssistant):
        """Test coordinator initialization with power service only."""
        mock_client = MagicMock()
        config = {
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": "123",
                    "service_number": "SVC001",
                    "meter_number": "MOCK_POWER_METER",
                    "display_meter_number": "MOCK_POWER_METER",
                    "service_type": "P",
                }
            ),
        }

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        assert coordinator.power_service is not None
        assert coordinator.water_service is None

    @pytest.mark.asyncio
    async def test_async_update_data_success(
        self, hass: HomeAssistant, mock_power_service, mock_water_service
    ):
        """Test successful data update."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock()

        power_readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2),
                consumption=28.3,
                unit="kWh",
            ),
        ]
        water_readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=1.5,
                unit="CCF",
            ),
        ]

        mock_client.get_power_usage = AsyncMock(return_value=power_readings)
        mock_client.get_water_usage = AsyncMock(return_value=water_readings)

        config = {
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                }
            ),
            CONF_WATER_SERVICE: json.dumps(
                {
                    "service_id": mock_water_service.service_id,
                    "service_number": mock_water_service.service_number,
                    "meter_number": mock_water_service.meter_number,
                    "display_meter_number": mock_water_service.display_meter_number,
                    "service_type": mock_water_service.service_type.value,
                }
            ),
        }

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        with patch.object(
            coordinator, "_import_statistics", new=AsyncMock()
        ) as mock_import:
            data = await coordinator._async_update_data()

            assert "power" in data
            assert data["power"]["consumption"] == 28.3  # Latest reading
            assert data["power"]["date"] == datetime(2026, 1, 2)
            assert data["power"]["unit"] == "kWh"

            assert "water" in data
            assert data["water"]["consumption"] == 1.5
            assert data["water"]["unit"] == "CCF"

            # Verify statistics import was called
            assert mock_import.call_count == 2

    @pytest.mark.asyncio
    async def test_async_update_data_no_readings(
        self, hass: HomeAssistant, mock_power_service
    ):
        """Test data update with no readings."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock()
        mock_client.get_power_usage = AsyncMock(return_value=[])

        config = {
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                }
            ),
        }

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        data = await coordinator._async_update_data()

        assert data == {}

    @pytest.mark.asyncio
    async def test_async_update_data_error(self, hass: HomeAssistant, mock_power_service):
        """Test data update with error."""
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(side_effect=Exception("API Error"))

        config = {
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                }
            ),
        }

        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        with pytest.raises(UpdateFailed, match="Error communicating with TPU"):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_import_statistics_new_data(
        self, hass: HomeAssistant, mock_power_service
    ):
        """Test importing new statistics."""
        mock_client = AsyncMock()
        config = {}
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2),
                consumption=28.3,
                unit="kWh",
            ),
        ]

        with patch(
            "custom_components.mytpu.get_last_statistics", return_value={}
        ) as mock_get_stats:
            with patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats:
                await coordinator._import_statistics(
                    mock_power_service, readings, "energy"
                )

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
                assert len(statistics) == 2
                assert statistics[0]["state"] == 25.5
                assert statistics[0]["sum"] == 25.5  # Cumulative
                assert statistics[1]["state"] == 28.3
                assert statistics[1]["sum"] == 53.8  # 25.5 + 28.3

    @pytest.mark.asyncio
    async def test_import_statistics_with_previous_data(
        self, hass: HomeAssistant, mock_power_service
    ):
        """Test importing statistics with existing data."""
        mock_client = AsyncMock()
        config = {}
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 3),
                consumption=30.0,
                unit="kWh",
            ),
        ]

        # Mock existing statistics
        last_stat_time = dt_util.as_utc(datetime(2026, 1, 2))
        mock_last_stats = {
            f"{DOMAIN}:p_mock_power_meter_energy": [
                {
                    "sum": 100.0,
                    "start": last_stat_time,
                }
            ]
        }

        with patch(
            "custom_components.mytpu.get_last_statistics", return_value=mock_last_stats
        ):
            with patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats:
                await coordinator._import_statistics(
                    mock_power_service, readings, "energy"
                )

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
        self, hass: HomeAssistant, mock_power_service
    ):
        """Test that duplicate dates are skipped."""
        mock_client = AsyncMock()
        config = {}
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=25.5,
                unit="kWh",
            ),
            UsageReading(
                date=datetime(2026, 1, 2),
                consumption=28.3,
                unit="kWh",
            ),
        ]

        # Mock that we already have data up to Jan 2
        last_stat_time = dt_util.as_utc(datetime(2026, 1, 2))
        mock_last_stats = {
            f"{DOMAIN}:p_mock_power_meter_energy": [
                {
                    "sum": 100.0,
                    "start": last_stat_time,
                }
            ]
        }

        with patch(
            "custom_components.mytpu.get_last_statistics", return_value=mock_last_stats
        ):
            with patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats:
                await coordinator._import_statistics(
                    mock_power_service, readings, "energy"
                )

                # Should not add any statistics (all duplicates)
                mock_add_stats.assert_not_called()

    @pytest.mark.asyncio
    async def test_import_statistics_water(
        self, hass: HomeAssistant, mock_water_service
    ):
        """Test importing water statistics."""
        mock_client = AsyncMock()
        config = {}
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=1.5,
                unit="CCF",
            ),
        ]

        with patch(
            "custom_components.mytpu.get_last_statistics", return_value={}
        ):
            with patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats:
                await coordinator._import_statistics(
                    mock_water_service, readings, "water"
                )

                mock_add_stats.assert_called_once()
                # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
                # call_args.args gives us the tuple of positional arguments
                args = mock_add_stats.call_args.args
                metadata = args[1]  # Second positional arg (metadata)
                statistics = args[2]  # Third positional arg (statistics)

                # Verify metadata for water (metadata is a dict)
                assert metadata["statistic_id"] == f"{DOMAIN}:w_mock_water_meter_water"
                assert "TPU Water" in metadata["name"]
                assert metadata["unit_class"] == "volume"

    @pytest.mark.asyncio
    async def test_import_statistics_meter_id_sanitization(
        self, hass: HomeAssistant
    ):
        """Test that meter IDs with hyphens are sanitized."""
        mock_client = AsyncMock()
        config = {}
        coordinator = TPUDataUpdateCoordinator(hass, mock_client, config)

        service = Service(
            service_id="123",
            service_number="SVC",
            meter_number="MTR-123-ABC",
            display_meter_number="MTR-123-ABC",
            service_type=ServiceType.POWER,
        )

        readings = [
            UsageReading(
                date=datetime(2026, 1, 1),
                consumption=10.0,
                unit="kWh",
            ),
        ]

        with patch(
            "custom_components.mytpu.get_last_statistics", return_value={}
        ):
            with patch(
                "custom_components.mytpu.async_add_external_statistics"
            ) as mock_add_stats:
                await coordinator._import_statistics(service, readings, "energy")

                # Extract arguments: async_add_external_statistics(hass, metadata, statistics)
                # call_args.args gives us the tuple of positional arguments
                args = mock_add_stats.call_args.args
                metadata = args[1]  # Second positional arg (metadata)

                # Hyphens should be replaced with underscores and lowercased (metadata is a dict)
                assert metadata["statistic_id"] == f"{DOMAIN}:p_mtr_123_abc_energy"
