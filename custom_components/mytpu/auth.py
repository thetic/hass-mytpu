"""OAuth2 authentication for MyTPU API."""

import logging
import time
from base64 import b64encode
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

    _oauth_basic_token: str = b64encode(b"webClientIdPassword:secret").decode("utf-8")

    def __init__(self, token_data: dict | None = None):
        """Initialize auth handler.

        Args:
            token_data: Previously stored token data (optional)
        """
        self._token: TokenInfo | None = None

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

        url = f"{BASE_URL}/rest/oauth/token"
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
        headers = {
            "Authorization": f"Basic {self._oauth_basic_token}",
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

    async def _refresh_token(self, session: aiohttp.ClientSession) -> None:
        """Refresh the access token using the refresh token."""
        if not self._token or not self._token.refresh_token:
            _LOGGER.error("No refresh token available for token refresh")
            raise AuthError("No refresh token available")

        remaining = self._token.seconds_remaining
        if remaining < 0:
            _LOGGER.debug("Refreshing token that expired %.0f seconds ago", -remaining)
        else:
            _LOGGER.debug(
                "Refreshing token with %.0f seconds still remaining", remaining
            )

        url = f"{BASE_URL}/rest/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._token.refresh_token,
        }
        headers = {
            "Authorization": f"Basic {self._oauth_basic_token}",
        }

        async with session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.debug(
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
