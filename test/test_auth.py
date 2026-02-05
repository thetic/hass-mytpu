"""Tests for mytpu authentication."""

import time

import aiohttp
import pytest
from aioresponses import aioresponses
from freezegun import freeze_time

from custom_components.mytpu.auth import (
    BASE_URL,
    AuthError,
    MyTPUAuth,
    TokenInfo,
)


class TestTokenInfo:
    """Test TokenInfo dataclass."""

    @freeze_time("2026-01-17 12:00:00")
    def test_token_not_expired(self):
        """Test token that is not expired."""
        token = TokenInfo(
            access_token="test",
            refresh_token="refresh",
            expires_at=time.time() + 3600,  # 1 hour from now
            customer_id="123",
        )
        assert not token.is_expired

    @freeze_time("2026-01-17 12:00:00")
    def test_token_expired(self):
        """Test token that is expired."""
        token = TokenInfo(
            access_token="test",
            refresh_token="refresh",
            expires_at=time.time() - 100,  # Past
            customer_id="123",
        )
        assert token.is_expired

    @freeze_time("2026-01-17 12:00:00")
    def test_token_expiring_soon(self):
        """Test token within 60s buffer is considered expired."""
        token = TokenInfo(
            access_token="test",
            refresh_token="refresh",
            expires_at=time.time() + 30,  # 30s from now (within 60s buffer)
            customer_id="123",
        )
        assert token.is_expired

    @freeze_time("2026-01-17 12:00:00")
    def test_token_exactly_at_buffer(self):
        """Test token at exactly 60s buffer edge."""
        token = TokenInfo(
            access_token="test",
            refresh_token="refresh",
            expires_at=time.time() + 60,  # Exactly 60s from now
            customer_id="123",
        )
        # Should be expired because of >= check with buffer
        assert token.is_expired

    @freeze_time("2026-01-17 12:00:00")
    def test_token_to_dict(self):
        """Test TokenInfo serialization to dict."""
        token = TokenInfo(
            access_token="test_access",
            refresh_token="test_refresh",
            expires_at=time.time() + 3600,
            customer_id="CUST123",
        )

        token_dict = token.to_dict()

        assert token_dict["access_token"] == "test_access"
        assert token_dict["refresh_token"] == "test_refresh"
        assert token_dict["expires_at"] == time.time() + 3600
        assert token_dict["customer_id"] == "CUST123"

    @freeze_time("2026-01-17 12:00:00")
    def test_token_from_dict(self):
        """Test TokenInfo deserialization from dict."""
        token_dict = {
            "access_token": "test_access",
            "refresh_token": "test_refresh",
            "expires_at": time.time() + 3600,
            "customer_id": "CUST123",
        }

        token = TokenInfo.from_dict(token_dict)

        assert token.access_token == "test_access"
        assert token.refresh_token == "test_refresh"
        assert token.expires_at == time.time() + 3600
        assert token.customer_id == "CUST123"

    @freeze_time("2026-01-17 12:00:00")
    def test_token_round_trip(self):
        """Test TokenInfo serialization and deserialization round trip."""
        original = TokenInfo(
            access_token="test_access",
            refresh_token="test_refresh",
            expires_at=time.time() + 3600,
            customer_id="CUST123",
        )

        token_dict = original.to_dict()
        restored = TokenInfo.from_dict(token_dict)

        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert restored.expires_at == original.expires_at
        assert restored.customer_id == original.customer_id


class TestMyTPUAuth:
    """Test MyTPUAuth class."""

    def test_init(self):
        """Test initialization."""
        auth = MyTPUAuth()
        assert auth._token is None
        assert auth._oauth_basic_token is None

    @freeze_time("2026-01-17 12:00:00")
    def test_init_with_token_data(self):
        """Test initialization with stored token data."""
        token_data = {
            "access_token": "stored_access",
            "refresh_token": "stored_refresh",
            "expires_at": time.time() + 3600,
            "customer_id": "CUST123",
        }

        auth = MyTPUAuth(token_data)

        assert auth._token is not None
        assert auth._token.access_token == "stored_access"
        assert auth._token.refresh_token == "stored_refresh"
        assert auth._token.customer_id == "CUST123"

    def test_init_with_invalid_token_data(self):
        """Test initialization with invalid token data."""
        invalid_token_data = {"invalid": "data"}

        auth = MyTPUAuth(invalid_token_data)

        # Should ignore invalid token data
        assert auth._token is None

    def test_get_token_data_none(self):
        """Test get_token_data when no token exists."""
        auth = MyTPUAuth()
        assert auth.get_token_data() is None

    @freeze_time("2026-01-17 12:00:00")
    def test_get_token_data_with_token(self):
        """Test get_token_data returns token dict."""
        auth = MyTPUAuth()
        auth._token = TokenInfo(
            access_token="test_access",
            refresh_token="test_refresh",
            expires_at=time.time() + 3600,
            customer_id="CUST123",
        )

        token_data = auth.get_token_data()

        assert token_data is not None
        assert token_data["access_token"] == "test_access"
        assert token_data["refresh_token"] == "test_refresh"
        assert token_data["customer_id"] == "CUST123"

    def test_customer_id_none_when_no_token(self):
        """Test customer_id returns None when no token."""
        auth = MyTPUAuth()
        assert auth.customer_id is None

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_success(self):
        """Test successful extraction of OAuth basic token."""
        html = '<script src="main.abc123def456.js"></script>'
        js = 'headers: {"Authorization": "Basic dGVzdDp0ZXN0"}'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123def456.js", status=200, body=js)

                token = await auth._get_oauth_basic_token(session)
                assert token == "dGVzdDp0ZXN0"

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_alternative_pattern(self):
        """Test extraction with alternative JS pattern."""
        html = '<head><script src="main.fed789abc123.js"></script></head>'
        js = 'Authorization:"Basic YWx0ZXJuYXRpdmU="'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.fed789abc123.js", status=200, body=js)

                token = await auth._get_oauth_basic_token(session)
                assert token == "YWx0ZXJuYXRpdmU="

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_caching(self):
        """Test that Basic token is cached after first fetch."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdA=="'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)

                token1 = await auth._get_oauth_basic_token(session)
                assert token1 == "dGVzdA=="

                # Second call should use cached value without making requests
                token2 = await auth._get_oauth_basic_token(session)
                assert token2 == "dGVzdA=="

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_no_main_js(self):
        """Test error when main.js not found in HTML."""
        html = '<script src="other.js"></script>'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)

                with pytest.raises(AuthError, match="Could not find main.js"):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_login_page_error(self):
        """Test error when login page fetch fails."""
        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=500)

                with pytest.raises(AuthError, match="Failed to fetch login page"):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_js_fetch_error(self):
        """Test error when JS bundle fetch fails."""
        html = '<script src="main.abc123.js"></script>'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=404)

                with pytest.raises(AuthError, match="Failed to fetch main.abc123.js"):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_no_token_in_js(self):
        """Test error when Basic token not found in JS."""
        html = '<script src="main.abc123.js"></script>'
        js = "var config = { headers: {} };"

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)

                with pytest.raises(
                    AuthError, match="Could not find Basic auth token in main.abc123.js"
                ):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_refresh_token_success(self):
        """Test successful token refresh."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        refresh_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "user": {"customerId": "CUST123"},
        }

        auth = MyTPUAuth()
        # Set an existing token with refresh_token
        auth._token = TokenInfo(
            access_token="old_access",
            refresh_token="old_refresh",
            expires_at=time.time() - 100,
            customer_id="CUST123",
        )

        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=refresh_response,
                )

                await auth._refresh_token(session)

                assert auth._token.access_token == "new_access_token"
                assert auth._token.refresh_token == "new_refresh_token"
                assert auth._token.customer_id == "CUST123"

    @pytest.mark.asyncio
    async def test_refresh_token_no_token(self):
        """Test refresh token fails when no token exists."""
        auth = MyTPUAuth()

        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError, match="No refresh token available"):
                await auth._refresh_token(session)

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token(self):
        """Test refresh token fails when refresh token is empty."""
        auth = MyTPUAuth()
        auth._token = TokenInfo(
            access_token="access",
            refresh_token="",
            expires_at=time.time() + 3600,
            customer_id="CUST123",
        )

        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError, match="No refresh token available"):
                await auth._refresh_token(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_refresh_token_api_error(self):
        """Test refresh token handles API errors."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth()
        auth._token = TokenInfo(
            access_token="old_access",
            refresh_token="old_refresh",
            expires_at=time.time() - 100,
            customer_id="CUST123",
        )

        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=400,
                    body='{"error": "invalid_grant"}',
                )

                with pytest.raises(AuthError, match="Token refresh failed: 400"):
                    await auth._refresh_token(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_none(self, mock_token_response):
        """Test get_token when no token exists."""
        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with pytest.raises(
                AuthError, match="No token available. A full login is required."
            ):
                await auth.get_token(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_expired_refresh_success(self):
        """Test get_token refreshes token when expired."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        refresh_response = {
            "access_token": "refreshed_access_token",
            "refresh_token": "refreshed_refresh_token",
            "expires_in": 3600,
            "user": {"customerId": "CUST123"},
        }

        auth = MyTPUAuth()
        # Set an expired token
        auth._token = TokenInfo(
            access_token="old_token",
            refresh_token="old_refresh",
            expires_at=time.time() - 100,
            customer_id="OLD123",
        )

        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                # Only one call to token endpoint (refresh, not full auth)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=refresh_response,
                )

                token = await auth.get_token(session)
                assert token == "refreshed_access_token"
                assert auth._token.refresh_token == "refreshed_refresh_token"
                assert auth._token.customer_id == "CUST123"

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_expired_refresh_fails(self):
        """Test get_token raises AuthError when refresh fails."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth()
        # Set an expired token
        auth._token = TokenInfo(
            access_token="old_token",
            refresh_token="old_refresh",
            expires_at=time.time() - 100,
            customer_id="OLD123",
        )

        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                # First call (refresh) fails
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=400,
                    body='{"error": "invalid_grant"}',
                )

                with pytest.raises(AuthError, match="Token refresh failed."):
                    await auth.get_token(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_valid(self):
        """Test get_token when token is still valid."""
        auth = MyTPUAuth()
        auth._token = TokenInfo(
            access_token="valid_token",
            refresh_token="valid_refresh",
            expires_at=time.time() + 3600,
            customer_id="VALID123",
        )

        async with aiohttp.ClientSession() as session:
            token = await auth.get_token(session)
            assert token == "valid_token"

    @pytest.mark.asyncio
    async def test_get_auth_header(self, mock_token_response):
        """Test get_auth_header returns proper header."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth()
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                # Mocks for _get_oauth_basic_token during async_login
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                # Mocks for token exchange during async_login
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=mock_token_response,
                )

                # Perform a login to populate the token
                await auth.async_login("testuser", "testpass", session)

                header = await auth.get_auth_header(session)
                assert header == {"Authorization": "Bearer test_access_token_12345"}
