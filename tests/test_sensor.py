"""Tests for mytpu sensor platform."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant

from custom_components.mytpu.const import CONF_POWER_SERVICE, CONF_WATER_SERVICE, DOMAIN
from custom_components.mytpu.sensor import (
    TPUEnergySensor,
    TPUWaterSensor,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_async_setup_entry_both_services(hass: HomeAssistant, mock_config_entry):
    """Test setting up sensors for both power and water."""
    mock_coordinator = MagicMock()
    hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}

    entities = []

    def mock_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass,mock_config_entry, mock_add_entities)

    assert len(entities) == 2
    assert isinstance(entities[0], TPUEnergySensor)
    assert isinstance(entities[1], TPUWaterSensor)


@pytest.mark.asyncio
async def test_async_setup_entry_power_only(hass: HomeAssistant, mock_power_service):
    """Test setting up sensor for power only."""
    import json
    from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Create config entry with only power service
    power_only_entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword123",
            CONF_POWER_SERVICE: json.dumps(
                {
                    "service_id": mock_power_service.service_id,
                    "service_number": mock_power_service.service_number,
                    "meter_number": mock_power_service.meter_number,
                    "display_meter_number": mock_power_service.display_meter_number,
                    "service_type": mock_power_service.service_type.value,
                }
            ),
        },
        unique_id="test_power_only",
        title="TPU - Power Only",
    )

    mock_coordinator = MagicMock()
    hass.data[DOMAIN] = {power_only_entry.entry_id: mock_coordinator}

    entities = []

    def mock_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass,power_only_entry, mock_add_entities)

    assert len(entities) == 1
    assert isinstance(entities[0], TPUEnergySensor)


@pytest.mark.asyncio
async def test_async_setup_entry_water_only(hass: HomeAssistant, mock_water_service):
    """Test setting up sensor for water only."""
    import json
    from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    # Create config entry with only water service
    water_only_entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_USERNAME: "test@example.com",
            CONF_PASSWORD: "testpassword123",
            CONF_WATER_SERVICE: json.dumps(
                {
                    "service_id": mock_water_service.service_id,
                    "service_number": mock_water_service.service_number,
                    "meter_number": mock_water_service.meter_number,
                    "display_meter_number": mock_water_service.display_meter_number,
                    "service_type": mock_water_service.service_type.value,
                }
            ),
        },
        unique_id="test_water_only",
        title="TPU - Water Only",
    )

    mock_coordinator = MagicMock()
    hass.data[DOMAIN] = {water_only_entry.entry_id: mock_coordinator}

    entities = []

    def mock_add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass,water_only_entry, mock_add_entities)

    assert len(entities) == 1
    assert isinstance(entities[0], TPUWaterSensor)


class TestTPUEnergySensor:
    """Test TPUEnergySensor class."""

    def test_sensor_attributes(self, mock_config_entry):
        """Test sensor static attributes."""
        mock_coordinator = MagicMock()
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        assert sensor.device_class == SensorDeviceClass.ENERGY
        assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
        assert sensor.has_entity_name is True
        assert sensor.name == "Energy Consumption"
        assert sensor.unique_id == f"{mock_config_entry.entry_id}_energy"

    def test_native_value_with_data(self, mock_config_entry):
        """Test native_value returns consumption from coordinator data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "power": {
                "consumption": 25.5,
                "date": datetime(2026, 1, 15),
                "unit": "kWh",
            }
        }
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value == 25.5

    def test_native_value_no_data(self, mock_config_entry):
        """Test native_value returns None when no data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = None
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value is None

    def test_native_value_no_power_key(self, mock_config_entry):
        """Test native_value returns None when power key missing."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {"water": {"consumption": 1.5}}
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value is None

    def test_extra_state_attributes_with_data(self, mock_config_entry):
        """Test extra_state_attributes returns proper attributes."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "power": {
                "consumption": 25.5,
                "date": datetime(2026, 1, 15, 12, 0, 0),
                "unit": "kWh",
            }
        }
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        attrs = sensor.extra_state_attributes

        assert "last_reading_date" in attrs
        assert attrs["last_reading_date"] == "2026-01-15T12:00:00"
        assert attrs["unit"] == "kWh"

    def test_extra_state_attributes_no_data(self, mock_config_entry):
        """Test extra_state_attributes returns empty dict when no data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = None
        sensor = TPUEnergySensor(mock_coordinator, mock_config_entry)

        attrs = sensor.extra_state_attributes

        assert attrs == {}


class TestTPUWaterSensor:
    """Test TPUWaterSensor class."""

    def test_sensor_attributes(self, mock_config_entry):
        """Test sensor static attributes."""
        mock_coordinator = MagicMock()
        sensor = TPUWaterSensor(mock_coordinator, mock_config_entry)

        assert sensor.device_class == SensorDeviceClass.WATER
        assert sensor.native_unit_of_measurement == UnitOfVolume.CENTUM_CUBIC_FEET
        assert sensor.has_entity_name is True
        assert sensor.name == "Water Consumption"
        assert sensor.unique_id == f"{mock_config_entry.entry_id}_water"

    def test_native_value_with_data(self, mock_config_entry):
        """Test native_value returns consumption from coordinator data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "water": {
                "consumption": 1.5,
                "date": datetime(2026, 1, 15),
                "unit": "CCF",
            }
        }
        sensor = TPUWaterSensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value == 1.5

    def test_native_value_no_data(self, mock_config_entry):
        """Test native_value returns None when no data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = None
        sensor = TPUWaterSensor(mock_config_entry, mock_config_entry)

        assert sensor.native_value is None

    def test_native_value_no_water_key(self, mock_config_entry):
        """Test native_value returns None when water key missing."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {"power": {"consumption": 25.5}}
        sensor = TPUWaterSensor(mock_coordinator, mock_config_entry)

        assert sensor.native_value is None

    def test_extra_state_attributes_with_data(self, mock_config_entry):
        """Test extra_state_attributes returns proper attributes."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "water": {
                "consumption": 1.5,
                "date": datetime(2026, 1, 15, 12, 0, 0),
                "unit": "CCF",
            }
        }
        sensor = TPUWaterSensor(mock_coordinator, mock_config_entry)

        attrs = sensor.extra_state_attributes

        assert "last_reading_date" in attrs
        assert attrs["last_reading_date"] == "2026-01-15T12:00:00"
        assert attrs["unit"] == "CCF"

    def test_extra_state_attributes_no_data(self, mock_config_entry):
        """Test extra_state_attributes returns empty dict when no data."""
        mock_coordinator = MagicMock()
        mock_coordinator.data = None
        sensor = TPUWaterSensor(mock_coordinator, mock_config_entry)

        attrs = sensor.extra_state_attributes

        assert attrs == {}
