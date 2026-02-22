"""OAuth2 authentication for MyTPU API."""

import logging
import re
import time
from dataclasses import dataclass

import aiohttp

BASE_URL = "https://myaccount.mytpu.org"

_LOGGER = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    """OAuth2 token information."""

    access_token: str
    refresh_token: str
    expires_at: float
    customer_id: str

    @property
    def is_expired(self) -> bool:
        """Check if the token is expired (with 60s buffer)."""
        return time.time() >= (self.expires_at - 60)

    @property
    def seconds_remaining(self) -> float:
        """Seconds until token expires (negative if already expired)."""
        return self.expires_at - time.time()

    def to_dict(self) -> dict:
        """Serialize token info to dictionary for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "customer_id": self.customer_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        """Deserialize token info from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            customer_id=data["customer_id"],
        )


class AuthError(Exception):
    """Authentication error - credentials invalid or token expired."""

    pass


class ServerError(Exception):
    """Server error - temporary issue with MyTPU API."""

    pass


class MyTPUAuth:
    """Handles OAuth2 authentication with MyTPU."""

    def __init__(self, token_data: dict | None = None):
        """Initialize auth handler.

        Args:
            token_data: Previously stored token data (optional)
        """
        self._token: TokenInfo | None = None
        self._oauth_basic_token: str | None = None

        # Load stored token if available
        if token_data:
            try:
                self._token = TokenInfo.from_dict(token_data)
            except (KeyError, ValueError):
                # Invalid token data, will re-authenticate
                self._token = None

    @property
    def customer_id(self) -> str | None:
        """Get the customer ID from the token."""
        return self._token.customer_id if self._token else None

    def get_token_data(self) -> dict | None:
        """Get current token data for storage."""
        return self._token.to_dict() if self._token else None

    async def async_login(
        self, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        """Authenticate with username/password to get tokens."""
        _LOGGER.debug("Starting full login for user: %s", username)
        # First get the Basic auth token from the JS bundle
        basic_token = await self._get_oauth_basic_token(session)

        url = f"{BASE_URL}/rest/oauth/token"
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_token}",
        }

        async with session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error("Login failed with status %s: %s", resp.status, text)
                raise AuthError(f"Authentication failed: {resp.status} - {text}")

            result = await resp.json()

            if "access_token" not in result:
                raise AuthError(f"No access token in response: {result}")

            expires_in = result.get("expires_in", 3600)
            user_info = result.get("user", {})
            refresh_token = result.get("refresh_token", "")

            if not refresh_token:
                _LOGGER.warning(
                    "No refresh_token provided in login response. "
                    "Token refresh will not be possible."
                )

            self._token = TokenInfo(
                access_token=result["access_token"],
                refresh_token=refresh_token,
                expires_at=time.time() + expires_in,
                customer_id=user_info.get("customerId", ""),
            )
            _LOGGER.info(
                "Login successful. Token expires in %s seconds (at %s). "
                "Has refresh token: %s",
                expires_in,
                self._token.expires_at,
                bool(refresh_token),
            )

    async def get_token(self, session: aiohttp.ClientSession) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._token is None:
            _LOGGER.error("No token available - full login required")
            raise AuthError("No token available. A full login is required.")
        elif self._token.is_expired:
            _LOGGER.info(
                "Token expired (expires_at: %s, current: %s) - attempting refresh",
                self._token.expires_at,
                time.time(),
            )
            # Try to refresh the token
            try:
                await self._refresh_token(session)
            except ServerError:
                # Server error - let it propagate, coordinator will retry later
                raise
            except AuthError as err:
                # Auth error - token is invalid, need full re-authentication
                _LOGGER.error("Token refresh failed: %s", err)
                raise AuthError(
                    "Token refresh failed. A full login is required."
                ) from err
        assert self._token is not None
        return self._token.access_token

    async def _get_oauth_basic_token(self, session: aiohttp.ClientSession) -> str:
        """Extract the Basic auth token from TPU's JavaScript bundle.

        The OAuth endpoint requires a Basic auth header containing client credentials
        that are embedded in their minified JavaScript.
        """
        if self._oauth_basic_token:
            return self._oauth_basic_token

        # Step 1: Fetch the login page to find the main.js filename
        async with session.get(f"{BASE_URL}/eportal/") as resp:
            if resp.status != 200:
                raise AuthError(f"Failed to fetch login page: {resp.status}")
            html = await resp.text()

        # Find the main.js filename (e.g., main.16e8dec7eb52aa3d12ed.js)
        match = re.search(
            r'<script[^>]*src="(main\.[a-f0-9]+\.js)"[^>]*></script>',
            html,
        )
        if not match:
            raise AuthError("Could not find main.js on login page")

        main_js = match.group(1)

        # Step 2: Fetch the JS bundle and extract the Basic auth token
        async with session.get(f"{BASE_URL}/eportal/{main_js}") as resp:
            if resp.status != 200:
                raise AuthError(f"Failed to fetch {main_js}: {resp.status}")
            js_content = await resp.text()

        # Look for the Basic auth token in the JS
        match = re.search(
            r'["\']Authorization["\']:\s*["\']Basic ([A-Za-z0-9+/=]+)["\']',
            js_content,
        )
        if not match:
            # Try alternative pattern
            match = re.search(
                r'Authorization:"Basic ([A-Za-z0-9+/=]+)"',
                js_content,
            )
        if not match:
            raise AuthError(f"Could not find Basic auth token in {main_js}")

        self._oauth_basic_token = match.group(1)
        return self._oauth_basic_token

    async def async_proactive_refresh(
        self, session: aiohttp.ClientSession, min_remaining_seconds: float = 900
    ) -> bool:
        """Refresh the token if it expires within min_remaining_seconds.

        Unlike get_token(), this refreshes proactively before expiry rather than
        waiting until the token has already expired. Returns True if a refresh
        was attempted, False if the token is still fresh.
        """
        if self._token is None:
            _LOGGER.debug("Proactive refresh: no token available, skipping")
            return False

        remaining = self._token.seconds_remaining
        _LOGGER.debug(
            "Proactive refresh check: %.0f seconds remaining (threshold: %.0f s)",
            remaining,
            min_remaining_seconds,
        )

        if remaining < min_remaining_seconds:
            await self._refresh_token(session)
            return True

        return False

    async def _refresh_token(self, session: aiohttp.ClientSession) -> None:
        """Refresh the access token using the refresh token."""
        if not self._token or not self._token.refresh_token:
            _LOGGER.error("No refresh token available for token refresh")
            raise AuthError("No refresh token available")

        remaining = self._token.seconds_remaining
        if remaining < 0:
            _LOGGER.debug(
                "Refreshing token that expired %.0f seconds ago", -remaining
            )
        else:
            _LOGGER.debug(
                "Refreshing token with %.0f seconds still remaining", remaining
            )
        # Get the Basic auth token from the JS bundle
        basic_token = await self._get_oauth_basic_token(session)

        url = f"{BASE_URL}/rest/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_token}",
        }

        async with session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error(
                    "Token refresh failed with status %s: %s", resp.status, text
                )
                # Distinguish between client errors (auth issues) and server errors
                if resp.status >= 500:
                    # Server error - temporary issue, should retry later
                    raise ServerError(
                        f"MyTPU server error during token refresh: {resp.status} - {text}"
                    )
                else:
                    # Client error (401, 403, etc.) - invalid/expired token
                    raise AuthError(f"Token refresh failed: {resp.status} - {text}")

            result = await resp.json()

            if "access_token" not in result:
                _LOGGER.error("No access token in refresh response: %s", result)
                raise AuthError(f"No access token in refresh response: {result}")

            expires_in = result.get("expires_in", 3600)
            # Keep the same customer_id and refresh_token if not provided
            customer_id = result.get("user", {}).get(
                "customerId", self._token.customer_id
            )
            refresh_token = result.get("refresh_token", self._token.refresh_token)

            self._token = TokenInfo(
                access_token=result["access_token"],
                refresh_token=refresh_token,
                expires_at=time.time() + expires_in,
                customer_id=customer_id,
            )
            _LOGGER.info(
                "Token refresh successful. New token expires in %s seconds",
                expires_in,
            )

    async def get_auth_header(self, session: aiohttp.ClientSession) -> dict:
        """Get the Authorization header for API requests."""
        token = await self.get_token(session)
        return {"Authorization": f"Bearer {token}"}
