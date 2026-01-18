"""Pytest configuration and fixtures for mytpu tests."""

import json
from pathlib import Path

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mytpu.const import (
    CONF_POWER_SERVICE,
    CONF_WATER_SERVICE,
    DOMAIN,
)
from custom_components.mytpu.models import Service, ServiceType

# This fixture is required for all tests
pytest_plugins = "pytest_homeassistant_custom_component"


# Custom component fixtures
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_credentials():
    """Return mock credentials."""
    return {
        CONF_USERNAME: "test@example.com",
        CONF_PASSWORD: "testpassword123",
    }


@pytest.fixture
def mock_power_service():
    """Return a mock power service."""
    return Service(
        service_id="12345",
        service_number="SVC001",
        meter_number="MOCK_POWER_METER",
        display_meter_number="MOCK_POWER_METER",
        service_type=ServiceType.POWER,
        latitude="47.2529",
        longitude="-122.4443",
        contract_number="CNT001",
        totalizer=False,
    )


@pytest.fixture
def mock_water_service():
    """Return a mock water service."""
    return Service(
        service_id="67890",
        service_number="SVC002",
        meter_number="MOCK_WATER_METER",
        display_meter_number="MOCK_WATER_METER",
        service_type=ServiceType.WATER,
        latitude="47.2529",
        longitude="-122.4443",
        contract_number="CNT002",
        totalizer=False,
    )


@pytest.fixture
def mock_config_entry(mock_credentials, mock_power_service, mock_water_service):
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            **mock_credentials,
            CONF_POWER_SERVICE: json.dumps(
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
            ),
            CONF_WATER_SERVICE: json.dumps(
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
            ),
        },
        unique_id="test_unique_id",
        title="TPU - Test User",
    )


@pytest.fixture
def load_fixture():
    """Load a fixture from the fixtures directory."""

    def _load_fixture(filename):
        """Load a fixture."""
        path = Path(__file__).parent / "fixtures" / filename
        return path.read_text()

    return _load_fixture


@pytest.fixture
def mock_oauth_html():
    """Return mock HTML with main.js reference."""
    return """
    <html>
    <head>
        <script src="main.abc123def456.js"></script>
    </head>
    </html>
    """


@pytest.fixture
def mock_oauth_js():
    """Return mock JavaScript with OAuth Basic token."""
    return """
    var config = {
        headers: {
            "Authorization": "Basic dGVzdDp0ZXN0"
        }
    };
    """


@pytest.fixture
def mock_token_response():
    """Return mock OAuth token response."""
    return {
        "access_token": "test_access_token_12345",
        "refresh_token": "test_refresh_token_67890",
        "expires_in": 3600,
        "user": {
            "customerId": "CUST123",
            "email": "test@example.com",
        },
    }


@pytest.fixture
def mock_account_info():
    """Return mock account info response."""
    return {
        "accountContext": {
            "accountHolder": "Test User",
            "accountNumber": "ACC123",
        },
        "accountSummaryType": {
            "servicesForGraph": [
                {
                    "serviceId": "12345",
                    "serviceNumber": "SVC001",
                    "meterNumber": "MOCK_POWER_METER",
                    "exportMeterNum": "MOCK_POWER_METER",
                    "serviceType": "P",
                    "latitude": "47.2529",
                    "longitude": "-122.4443",
                    "serviceContract": "CNT001",
                    "totalizerMeter": "N",
                },
                {
                    "serviceId": "67890",
                    "serviceNumber": "SVC002",
                    "meterNumber": "MOCK_WATER_METER",
                    "exportMeterNum": "MOCK_WATER_METER",
                    "serviceType": "W",
                    "latitude": "47.2529",
                    "longitude": "-122.4443",
                    "serviceContract": "CNT002",
                    "totalizerMeter": "N",
                },
            ],
        },
    }


@pytest.fixture
def mock_usage_response():
    """Return mock usage data response."""
    return {
        "history": [
            {
                "usageDate": "2026-01-01",
                "usageConsumptionValue": 25.5,
                "uom": "kWh",
                "usageHighTemp": 45.0,
                "usageLowTemp": 32.0,
                "demandPeakTime": "2026-01-01 14:30",
            },
            {
                "usageDate": "2026-01-02",
                "usageConsumptionValue": 28.3,
                "uom": "kWh",
                "usageHighTemp": 48.0,
                "usageLowTemp": 35.0,
            },
        ],
    }
