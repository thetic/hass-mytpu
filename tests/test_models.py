"""Tests for mytpu models."""

import pytest
from datetime import datetime

from custom_components.mytpu.models import Service, ServiceType, UsageReading


class TestServiceType:
    """Test ServiceType enum."""

    def test_power_type(self):
        """Test POWER service type."""
        assert ServiceType.POWER.value == "P"

    def test_water_type(self):
        """Test WATER service type."""
        assert ServiceType.WATER.value == "W"

    def test_enum_from_value(self):
        """Test creating enum from value."""
        assert ServiceType("P") == ServiceType.POWER
        assert ServiceType("W") == ServiceType.WATER


class TestUsageReading:
    """Test UsageReading model."""

    def test_from_api_response_complete(self):
        """Test creating UsageReading from complete API response."""
        data = {
            "usageDate": "2026-01-15",
            "usageConsumptionValue": 25.5,
            "uom": "kWh",
            "usageHighTemp": 45.0,
            "usageLowTemp": 32.0,
            "demandPeakTime": "2026-01-15 14:30",
        }
        reading = UsageReading.from_api_response(data)

        assert reading.date == datetime(2026, 1, 15)
        assert reading.consumption == 25.5
        assert reading.unit == "kWh"
        assert reading.high_temp == 45.0
        assert reading.low_temp == 32.0
        assert reading.demand_peak_time == datetime(2026, 1, 15, 14, 30)

    def test_from_api_response_minimal(self):
        """Test creating UsageReading from minimal API response."""
        data = {
            "usageDate": "2026-01-15",
        }
        reading = UsageReading.from_api_response(data)

        assert reading.date == datetime(2026, 1, 15)
        assert reading.consumption == 0.0
        assert reading.unit == ""
        assert reading.high_temp is None
        assert reading.low_temp is None
        assert reading.demand_peak_time is None

    def test_from_api_response_invalid_peak_time(self):
        """Test handling invalid peak time gracefully."""
        data = {
            "usageDate": "2026-01-15",
            "demandPeakTime": "invalid-datetime",
        }
        reading = UsageReading.from_api_response(data)

        assert reading.demand_peak_time is None

    def test_from_api_response_no_peak_time(self):
        """Test handling missing peak time."""
        data = {
            "usageDate": "2026-01-15",
            "usageConsumptionValue": 30.0,
        }
        reading = UsageReading.from_api_response(data)

        assert reading.demand_peak_time is None

    def test_from_api_response_with_temps(self):
        """Test reading with temperature data."""
        data = {
            "usageDate": "2026-01-15",
            "usageConsumptionValue": 20.0,
            "uom": "kWh",
            "usageHighTemp": 55.5,
            "usageLowTemp": 28.3,
        }
        reading = UsageReading.from_api_response(data)

        assert reading.high_temp == 55.5
        assert reading.low_temp == 28.3

    def test_from_api_response_zero_consumption(self):
        """Test reading with zero consumption."""
        data = {
            "usageDate": "2026-01-15",
            "usageConsumptionValue": 0.0,
            "uom": "CCF",
        }
        reading = UsageReading.from_api_response(data)

        assert reading.consumption == 0.0
        assert reading.unit == "CCF"


class TestService:
    """Test Service model."""

    def test_from_graph_response_power(self):
        """Test creating power Service from API response."""
        data = {
            "serviceId": "12345",
            "serviceNumber": "SVC001",
            "meterNumber": "MOCK_POWER_METER",
            "exportMeterNum": "MOCK_POWER_METER",
            "serviceType": "P",
            "latitude": "47.2529",
            "longitude": "-122.4443",
            "serviceContract": "CNT001",
            "totalizerMeter": "N",
        }
        service = Service.from_graph_response(data)

        assert service.service_id == "12345"
        assert service.service_number == "SVC001"
        assert service.meter_number == "MOCK_POWER_METER"
        assert service.display_meter_number == "MOCK_POWER_METER"
        assert service.service_type == ServiceType.POWER
        assert service.latitude == "47.2529"
        assert service.longitude == "-122.4443"
        assert service.contract_number == "CNT001"
        assert service.totalizer is False

    def test_from_graph_response_water_totalizer(self):
        """Test creating water Service with totalizer."""
        data = {
            "serviceId": "67890",
            "serviceNumber": "SVC002",
            "meterNumber": "MOCK_WATER_METER",
            "exportMeterNum": "MOCK_WATER_METER-DISPLAY",
            "serviceType": "W",
            "totalizerMeter": "Y",
        }
        service = Service.from_graph_response(data)

        assert service.service_type == ServiceType.WATER
        assert service.display_meter_number == "MOCK_WATER_METER-DISPLAY"
        assert service.totalizer is True
        assert service.latitude is None
        assert service.longitude is None

    def test_from_graph_response_minimal(self):
        """Test creating Service from minimal data."""
        data = {}
        service = Service.from_graph_response(data)

        assert service.service_id == ""
        assert service.service_number == ""
        assert service.meter_number == ""
        assert service.display_meter_number == ""
        assert service.service_type == ServiceType.POWER  # Default
        assert service.latitude is None
        assert service.longitude is None
        assert service.contract_number is None
        assert service.totalizer is False

    def test_from_graph_response_display_number_fallback(self):
        """Test display meter number falls back to meter number."""
        data = {
            "serviceId": "123",
            "serviceNumber": "SVC",
            "meterNumber": "MTR999",
            "serviceType": "P",
        }
        service = Service.from_graph_response(data)

        assert service.display_meter_number == "MTR999"

    def test_from_graph_response_totalizer_false(self):
        """Test totalizer is false when not Y."""
        data = {
            "serviceId": "123",
            "serviceNumber": "SVC",
            "meterNumber": "MTR",
            "serviceType": "P",
            "totalizerMeter": "N",
        }
        service = Service.from_graph_response(data)

        assert service.totalizer is False

    def test_from_graph_response_with_coordinates(self):
        """Test service with GPS coordinates."""
        data = {
            "serviceId": "123",
            "serviceNumber": "SVC",
            "meterNumber": "MTR",
            "serviceType": "W",
            "latitude": "47.2529",
            "longitude": "-122.4443",
        }
        service = Service.from_graph_response(data)

        assert service.latitude == "47.2529"
        assert service.longitude == "-122.4443"
