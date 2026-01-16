"""OAuth2 authentication for MyTPU API."""

import re
import time
from dataclasses import dataclass

import aiohttp

BASE_URL = "https://myaccount.mytpu.org"


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


class AuthError(Exception):
    """Authentication error."""

    pass


class MyTPUAuth:
    """Handles OAuth2 authentication with MyTPU."""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._token: TokenInfo | None = None
        self._oauth_basic_token: str | None = None

    @property
    def customer_id(self) -> str | None:
        """Get the customer ID from the token."""
        return self._token.customer_id if self._token else None

    async def get_token(self, session: aiohttp.ClientSession) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._token is None or self._token.is_expired:
            await self._authenticate(session)
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

    async def _authenticate(self, session: aiohttp.ClientSession) -> None:
        """Authenticate with username/password to get tokens."""
        # First get the Basic auth token from the JS bundle
        basic_token = await self._get_oauth_basic_token(session)

        url = f"{BASE_URL}/rest/oauth/token"
        data = {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_token}",
        }

        async with session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise AuthError(f"Authentication failed: {resp.status} - {text}")

            result = await resp.json()

            if "access_token" not in result:
                raise AuthError(f"No access token in response: {result}")

            expires_in = result.get("expires_in", 3600)
            user_info = result.get("user", {})

            self._token = TokenInfo(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", ""),
                expires_at=time.time() + expires_in,
                customer_id=user_info.get("customerId", ""),
            )

    async def get_auth_header(self, session: aiohttp.ClientSession) -> dict:
        """Get the Authorization header for API requests."""
        token = await self.get_token(session)
        return {"Authorization": f"Bearer {token}"}
