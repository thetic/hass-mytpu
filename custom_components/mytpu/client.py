"""MyTPU API client."""

import logging
from datetime import datetime, timedelta

import aiohttp

from .auth import BASE_URL, MyTPUAuth
from .models import Service, UsageReading

_LOGGER = logging.getLogger(__name__)


class MyTPUError(Exception):
    """API error from MyTPU."""

    pass


class MyTPUClient:
    """Client for interacting with the MyTPU API."""

    def __init__(self, auth: MyTPUAuth):
        """Initialize the client with an authenticated auth handler.

        Args:
            auth: An initialized MyTPUAuth object.
        """
        self._auth = auth
        self._session: aiohttp.ClientSession | None = None
        self._account_context: dict | None = None
        self._services: list[Service] | None = None

    async def __aenter__(self) -> "MyTPUClient":
        """Enter async context."""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure we have an active session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self, method: str, endpoint: str, json_data: dict | None = None
    ) -> dict:
        """Make an authenticated API request."""
        session = await self._ensure_session()
        auth_header = await self._auth.get_auth_header(session)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **auth_header,
        }

        url = f"{BASE_URL}{endpoint}"

        async with session.request(
            method, url, json=json_data, headers=headers
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise MyTPUError(f"API request failed: {resp.status} - {text}")

            return await resp.json()

    async def get_account_info(self) -> dict:
        """Fetch account information and available services."""
        # customer_id is available from the auth handler after token acquisition
        customer_id = self._auth.customer_id
        if not customer_id:
            raise MyTPUError("Customer ID not available from authentication.")

        data = {
            "customerId": customer_id,
            "accountContext": None,
            "csrViewOnly": "N",
        }

        result = await self._request("POST", "/rest/account/customer/", data)
        self._account_context = result.get("accountContext", {})

        # Extract services from accountSummaryType.servicesForGraph
        # This contains the correct meter/service IDs needed for usage API
        account_summary = result.get("accountSummaryType", {})
        services_data = account_summary.get("servicesForGraph", [])
        _LOGGER.debug(
            "get_account_info: top-level keys=%s, accountSummaryType keys=%s, "
            "servicesForGraph count=%d",
            list(result.keys()),
            list(account_summary.keys()),
            len(services_data),
        )
        self._services = []
        for svc in services_data:
            _LOGGER.debug("get_account_info: service entry keys=%s", list(svc.keys()))
            self._services.append(Service.from_graph_response(svc))
        _LOGGER.debug("get_account_info: parsed %d service(s)", len(self._services))

        return result

    async def get_services(self) -> list[Service]:
        """Get list of services (meters) on the account."""
        if self._services is None:
            await self.get_account_info()
        return self._services or []

    async def get_usage(
        self,
        service: Service,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[UsageReading]:
        """Fetch usage data for a specific meter.

        Args:
            service: The Service object containing meter details
            from_date: Start date for data (default: 30 days ago)
            to_date: End date for data (default: today)

        Returns:
            List of UsageReading objects
        """
        if self._account_context is None:
            await self.get_account_info()

        if from_date is None:
            from_date = datetime.now() - timedelta(days=30)
        if to_date is None:
            to_date = datetime.now()

        data = {
            "customerId": self._auth.customer_id,
            "fromDate": from_date.strftime("%Y-%m-%d %H:%M"),
            "toDate": to_date.strftime("%Y-%m-%d %H:%M"),
            "meterNumber": service.meter_number,
            "serviceNumber": service.service_number,
            "serviceId": service.service_id,
            "serviceType": service.service_type.value,
            "accountContext": self._account_context,
            "meterIds": [service.service_id],
        }

        # Add optional fields if available
        if service.latitude:
            data["latitude"] = service.latitude
        if service.longitude:
            data["longitude"] = service.longitude
        if service.contract_number:
            data["contractNum"] = service.contract_number
        if service.totalizer:
            data["totalizerInd"] = "Y"

        result = await self._request("POST", "/rest/usage/month", data)

        history = result.get("history", [])
        readings = []
        for item in history:
            # Skip "M" (monthly) entries: these are unfinalized placeholders
            # with zero consumption that will be replaced by "D" (daily) entries
            # once the meter reading is confirmed.
            if item.get("usageDate") and item.get("usageCategory") != "M":
                readings.append(UsageReading.from_api_response(item))

        return readings

    async def async_login(self, username: str, password: str) -> None:
        """Perform a full login with username and password."""
        session = await self._ensure_session()
        await self._auth.async_login(username, password, session)

    async def async_refresh_token_if_expiring(
        self, min_remaining_seconds: float = 900
    ) -> bool:
        """Proactively refresh the token if it expires within min_remaining_seconds."""
        session = await self._ensure_session()
        return await self._auth.async_proactive_refresh(session, min_remaining_seconds)

    def get_token_data(self) -> dict | None:
        """Get current token data for storage."""
        return self._auth.get_token_data()

    async def close(self) -> None:
        """Close the client session."""
        if self._session:
            await self._session.close()
            self._session = None
