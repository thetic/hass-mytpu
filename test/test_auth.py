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


class TestMyTPUAuth:
    """Test MyTPUAuth class."""

    def test_init(self):
        """Test initialization."""
        auth = MyTPUAuth("user@example.com", "password123")
        assert auth._username == "user@example.com"
        assert auth._password == "password123"
        assert auth._token is None
        assert auth._oauth_basic_token is None

    def test_customer_id_none_when_no_token(self):
        """Test customer_id returns None when no token."""
        auth = MyTPUAuth("user", "pass")
        assert auth.customer_id is None

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_success(self):
        """Test successful extraction of OAuth basic token."""
        html = '<script src="main.abc123def456.js"></script>'
        js = 'headers: {"Authorization": "Basic dGVzdDp0ZXN0"}'

        auth = MyTPUAuth("user", "pass")
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

        auth = MyTPUAuth("user", "pass")
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

        auth = MyTPUAuth("user", "pass")
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

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)

                with pytest.raises(AuthError, match="Could not find main.js"):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_login_page_error(self):
        """Test error when login page fetch fails."""
        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=500)

                with pytest.raises(AuthError, match="Failed to fetch login page"):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_get_oauth_basic_token_js_fetch_error(self):
        """Test error when JS bundle fetch fails."""
        html = '<script src="main.abc123.js"></script>'

        auth = MyTPUAuth("user", "pass")
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

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)

                with pytest.raises(
                    AuthError, match="Could not find Basic auth token in main.abc123.js"
                ):
                    await auth._get_oauth_basic_token(session)

    @pytest.mark.asyncio
    async def test_authenticate_success(self, mock_token_response):
        """Test successful authentication."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=mock_token_response,
                )

                await auth._authenticate(session)

                assert auth._token is not None
                assert auth._token.access_token == "test_access_token_12345"
                assert auth._token.refresh_token == "test_refresh_token_67890"
                assert auth._token.customer_id == "CUST123"
                assert auth.customer_id == "CUST123"

    @pytest.mark.asyncio
    async def test_authenticate_invalid_credentials(self):
        """Test authentication with invalid credentials."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth("user", "wrongpass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=401,
                    body='{"error": "invalid_grant"}',
                )

                with pytest.raises(AuthError, match="Authentication failed: 401"):
                    await auth._authenticate(session)

    @pytest.mark.asyncio
    async def test_authenticate_no_access_token_in_response(self):
        """Test authentication when response missing access_token."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'
        incomplete_response = {"refresh_token": "refresh"}

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=incomplete_response,
                )

                with pytest.raises(AuthError, match="No access token in response"):
                    await auth._authenticate(session)

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_none(self, mock_token_response):
        """Test get_token when no token exists."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=mock_token_response,
                )

                token = await auth.get_token(session)
                assert token == "test_access_token_12345"

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_expired(self, mock_token_response):
        """Test get_token when token is expired."""
        html = '<script src="main.abc123.js"></script>'
        js = 'Authorization:"Basic dGVzdDp0ZXN0"'

        auth = MyTPUAuth("user", "pass")
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
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=mock_token_response,
                )

                token = await auth.get_token(session)
                assert token == "test_access_token_12345"
                assert auth._token.customer_id == "CUST123"

    @pytest.mark.asyncio
    @freeze_time("2026-01-17 12:00:00")
    async def test_get_token_when_valid(self):
        """Test get_token when token is still valid."""
        auth = MyTPUAuth("user", "pass")
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

        auth = MyTPUAuth("user", "pass")
        async with aiohttp.ClientSession() as session:
            with aioresponses() as m:
                m.get(f"{BASE_URL}/eportal/", status=200, body=html)
                m.get(f"{BASE_URL}/eportal/main.abc123.js", status=200, body=js)
                m.post(
                    f"{BASE_URL}/rest/oauth/token",
                    status=200,
                    payload=mock_token_response,
                )

                header = await auth.get_auth_header(session)
                assert header == {"Authorization": "Bearer test_access_token_12345"}
