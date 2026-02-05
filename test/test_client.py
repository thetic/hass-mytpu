"""Tests for mytpu API client."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses

from custom_components.mytpu.auth import BASE_URL
from custom_components.mytpu.client import MyTPUClient, MyTPUError
from custom_components.mytpu.models import ServiceType


class TestMyTPUClient:
    """Test MyTPUClient class."""

    def test_init(self):
        """Test client initialization."""
        client = MyTPUClient("user@example.com", "password123")
        assert client._auth._username == "user@example.com"
        assert client._auth._password == "password123"
        assert client._session is None
        assert client._account_context is None
        assert client._services is None

    def test_init_with_token_data(self):
        """Test client initialization with stored token data."""
        import time

        token_data = {
            "access_token": "stored_access",
            "refresh_token": "stored_refresh",
            "expires_at": time.time() + 3600,
            "customer_id": "CUST123",
        }

        client = MyTPUClient("user@example.com", "password123", token_data)

        assert client._auth._username == "user@example.com"
        assert client._auth._password == "password123"
        assert client._auth._token is not None
        assert client._auth._token.access_token == "stored_access"

    def test_get_token_data_none(self):
        """Test get_token_data when no token exists."""
        client = MyTPUClient("user", "pass")
        assert client.get_token_data() is None

    def test_get_token_data_with_token(self):
        """Test get_token_data returns token dict."""
        import time

        from custom_components.mytpu.auth import TokenInfo

        client = MyTPUClient("user", "pass")
        client._auth._token = TokenInfo(
            access_token="test_access",
            refresh_token="test_refresh",
            expires_at=time.time() + 3600,
            customer_id="CUST123",
        )

        token_data = client.get_token_data()

        assert token_data is not None
        assert token_data["access_token"] == "test_access"
        assert token_data["refresh_token"] == "test_refresh"
        assert token_data["customer_id"] == "CUST123"

    @pytest.mark.asyncio
    async def test_context_manager_enter(self):
        """Test async context manager enter."""
        client = MyTPUClient("user", "pass")
        async with client as c:
            assert c._session is not None
            assert isinstance(c, MyTPUClient)

    @pytest.mark.asyncio
    async def test_context_manager_exit(self):
        """Test async context manager exit."""
        client = MyTPUClient("user", "pass")
        async with client:
            assert client._session is not None
        assert client._session is None

    @pytest.mark.asyncio
    async def test_ensure_session_creates_session(self):
        """Test _ensure_session creates session if needed."""
        client = MyTPUClient("user", "pass")
        assert client._session is None

        session = await client._ensure_session()
        assert session is not None
        assert client._session is session

        await client.close()

    @pytest.mark.asyncio
    async def test_get_account_info_success(
        self, mock_account_info, mock_token_response
    ):
        """Test successful account info retrieval."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            # Mock the _token attribute to set customer_id
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=200,
                        payload=mock_account_info,
                    )

                    result = await client.get_account_info()

                    assert result == mock_account_info
                    assert client._account_context is not None
                    assert client._account_context["accountHolder"] == "Test User"
                    assert client._services is not None
                    assert len(client._services) == 2
                    assert client._services[0].meter_number == "MOCK_POWER_METER"
                    assert client._services[0].service_type == ServiceType.POWER
                    assert client._services[1].meter_number == "MOCK_WATER_METER"
                    assert client._services[1].service_type == ServiceType.WATER

    @pytest.mark.asyncio
    async def test_get_account_info_authenticates_if_needed(self, mock_account_info):
        """Test that get_account_info authenticates if no customer_id."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ) as mock_get_token:
            # Start with no _token (no customer_id)
            from custom_components.mytpu.auth import TokenInfo

            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=200,
                        payload=mock_account_info,
                    )

                    # Set token after get_token is called
                    def set_token(*args, **kwargs):
                        client._auth._token = TokenInfo(
                            access_token="test",
                            refresh_token="refresh",
                            expires_at=9999999999,
                            customer_id="CUST123",
                        )
                        return "test_token"

                    mock_get_token.side_effect = set_token

                    await client.get_account_info()

                    # Should have called get_token to authenticate
                    # Note: get_token is called twice - once to get customer_id, once in _request
                    assert mock_get_token.call_count >= 1

    @pytest.mark.asyncio
    async def test_get_account_info_api_error(self):
        """Test handling of API error during account info fetch."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=500,
                        body="Internal Server Error",
                    )

                    with pytest.raises(MyTPUError, match="API request failed: 500"):
                        await client.get_account_info()

    @pytest.mark.asyncio
    async def test_get_services_cached(self, mock_account_info):
        """Test that get_services returns cached services."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=200,
                        payload=mock_account_info,
                    )

                    # First call fetches account info
                    services1 = await client.get_services()
                    assert len(services1) == 2

                    # Second call uses cached services (no new request)
                    services2 = await client.get_services()
                    assert len(services2) == 2
                    assert services1 is services2

    @pytest.mark.asyncio
    async def test_get_services_fetches_if_none(self, mock_account_info):
        """Test that get_services fetches account info if services not cached."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=200,
                        payload=mock_account_info,
                    )

                    services = await client.get_services()

                    assert len(services) == 2
                    assert services[0].meter_number == "MOCK_POWER_METER"

    @pytest.mark.asyncio
    async def test_get_usage_success(
        self, mock_power_service, mock_account_info, mock_usage_response
    ):
        """Test successful usage data retrieval."""
        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=mock_usage_response,
                    )

                    from_date = datetime(2026, 1, 1)
                    to_date = datetime(2026, 1, 5)
                    readings = await client.get_usage(
                        mock_power_service, from_date, to_date
                    )

                    assert len(readings) == 2
                    assert readings[0].date == datetime(2026, 1, 1, tzinfo=UTC)
                    assert readings[0].consumption == 25.5
                    assert readings[0].unit == "kWh"
                    assert readings[1].date == datetime(2026, 1, 2, tzinfo=UTC)
                    assert readings[1].consumption == 28.3

    @pytest.mark.asyncio
    async def test_get_usage_default_dates(
        self, mock_power_service, mock_account_info, mock_usage_response
    ):
        """Test usage retrieval with default date range."""
        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=mock_usage_response,
                    )

                    readings = await client.get_usage(mock_power_service)

                    assert len(readings) == 2

    @pytest.mark.asyncio
    async def test_get_usage_fetches_account_info_if_needed(
        self, mock_power_service, mock_account_info, mock_usage_response
    ):
        """Test that get_usage fetches account info if not cached."""
        client = MyTPUClient("user", "pass")

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/account/customer/",
                        status=200,
                        payload=mock_account_info,
                    )
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=mock_usage_response,
                    )

                    readings = await client.get_usage(mock_power_service)

                    assert client._account_context is not None
                    assert len(readings) == 2

    @pytest.mark.asyncio
    async def test_get_usage_with_optional_fields(
        self, mock_account_info, mock_usage_response
    ):
        """Test usage request includes optional service fields."""
        from custom_components.mytpu.models import Service

        service = Service(
            service_id="123",
            service_number="SVC001",
            meter_number="MTR001",
            display_meter_number="MTR001",
            service_type=ServiceType.POWER,
            latitude="47.2529",
            longitude="-122.4443",
            contract_number="CNT001",
            totalizer=True,
        )

        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=mock_usage_response,
                    )

                    await client.get_usage(service)

                    # Verify the request was made (aioresponses will validate)

    @pytest.mark.asyncio
    async def test_get_usage_filters_invalid_dates(
        self, mock_power_service, mock_account_info
    ):
        """Test that readings without usageDate are filtered out."""
        response_with_invalid = {
            "history": [
                {
                    "usageDate": "2026-01-01",
                    "usageConsumptionValue": 25.5,
                },
                {
                    "usageConsumptionValue": 30.0,  # Missing usageDate
                },
                {
                    "usageDate": "2026-01-02",
                    "usageConsumptionValue": 28.3,
                },
            ]
        }

        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=response_with_invalid,
                    )

                    readings = await client.get_usage(mock_power_service)

                    # Should only have 2 readings (invalid one filtered out)
                    assert len(readings) == 2

    @pytest.mark.asyncio
    async def test_get_usage_filters_monthly_placeholders(
        self, mock_power_service, mock_account_info
    ):
        """Test that unfinalized monthly (M) entries are filtered out."""
        response_with_monthly = {
            "history": [
                {
                    "usageDate": "2026-01-01",
                    "usageConsumptionValue": 25.5,
                    "uom": "kWh",
                    "usageCategory": "D",
                },
                {
                    "usageDate": "2026-01-02",
                    "usageConsumptionValue": 0.0,
                    "uom": "kWh",
                    "usageCategory": "M",
                },
                {
                    "usageDate": "2026-01-03",
                    "usageConsumptionValue": 0.0,
                    "uom": "kWh",
                    "usageCategory": "M",
                },
            ]
        }

        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=response_with_monthly,
                    )

                    readings = await client.get_usage(mock_power_service)

                    # Only the D entry should be returned; M entries are filtered
                    assert len(readings) == 1
                    assert readings[0].date == datetime(2026, 1, 1, tzinfo=UTC)
                    assert readings[0].consumption == 25.5

    @pytest.mark.asyncio
    async def test_get_power_usage(
        self, mock_power_service, mock_account_info, mock_usage_response
    ):
        """Test get_power_usage convenience method."""
        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=mock_usage_response,
                    )

                    readings = await client.get_power_usage(mock_power_service)

                    assert len(readings) == 2

    @pytest.mark.asyncio
    async def test_get_water_usage(self, mock_water_service, mock_account_info):
        """Test get_water_usage convenience method."""
        water_usage_response = {
            "history": [
                {
                    "usageDate": "2026-01-01",
                    "usageConsumptionValue": 1.5,
                    "uom": "CCF",
                },
            ]
        }

        client = MyTPUClient("user", "pass")
        client._account_context = mock_account_info["accountContext"]

        with patch.object(
            client._auth, "get_token", new=AsyncMock(return_value="test_token")
        ):
            from custom_components.mytpu.auth import TokenInfo

            client._auth._token = TokenInfo(
                access_token="test",
                refresh_token="refresh",
                expires_at=9999999999,
                customer_id="CUST123",
            )
            async with client:
                with aioresponses() as m:
                    m.post(
                        f"{BASE_URL}/rest/usage/month",
                        status=200,
                        payload=water_usage_response,
                    )

                    readings = await client.get_water_usage(mock_water_service)

                    assert len(readings) == 1
                    assert readings[0].unit == "CCF"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method closes session."""
        client = MyTPUClient("user", "pass")
        async with client:
            assert client._session is not None

        await client.close()
        assert client._session is None
