"""MyTPU API client."""

from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from .auth import MyTPUAuth, BASE_URL
from .models import Service, ServiceType, UsageReading


class MyTPUError(Exception):
    """API error from MyTPU."""
    pass


class MyTPUClient:
    """Client for interacting with the MyTPU API."""

    def __init__(self, username: str, password: str):
        """Initialize the client with credentials.

        Args:
            username: MyTPU account username
            password: MyTPU account password
        """
        self._auth = MyTPUAuth(username, password)
        self._session: Optional[aiohttp.ClientSession] = None
        self._account_context: Optional[dict] = None
        self._services: Optional[list[Service]] = None

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

    async def _request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> dict:
        """Make an authenticated API request."""
        session = await self._ensure_session()
        auth_header = await self._auth.get_auth_header(session)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **auth_header,
        }

        url = f"{BASE_URL}{endpoint}"

        async with session.request(method, url, json=json_data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise MyTPUError(f"API request failed: {resp.status} - {text}")

            return await resp.json()

    async def get_account_info(self) -> dict:
        """Fetch account information and available services."""
        customer_id = self._auth.customer_id
        if not customer_id:
            # Need to authenticate first to get customer_id
            session = await self._ensure_session()
            await self._auth.get_token(session)
            customer_id = self._auth.customer_id

        data = {
            "customerId": customer_id,
            "accountContext": None,
            "csrViewOnly": "N",
        }

        result = await self._request("POST", "/rest/account/customer/", data)
        self._account_context = result.get("accountContext", {})

        # Extract services from response
        services_data = result.get("customerServices", [])
        self._services = []
        for svc in services_data:
            self._services.append(Service(
                service_id=svc.get("serviceId", ""),
                service_number=svc.get("serviceNumber", ""),
                meter_number=svc.get("meterNumber", ""),
                service_type=ServiceType(svc.get("serviceType", "P")),
                address=svc.get("serviceAddress", ""),
            ))

        return result

    async def get_services(self) -> list[Service]:
        """Get list of services (meters) on the account."""
        if self._services is None:
            await self.get_account_info()
        return self._services or []

    async def get_usage(
        self,
        service_type: ServiceType,
        meter_number: str,
        service_id: str,
        service_number: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[UsageReading]:
        """Fetch usage data for a specific meter.

        Args:
            service_type: Type of service (POWER or WATER)
            meter_number: The meter number
            service_id: The service ID
            service_number: The service number
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
            "meterNumber": meter_number,
            "serviceNumber": service_number,
            "serviceId": service_id,
            "serviceType": service_type.value,
            "accountContext": self._account_context,
        }

        result = await self._request("POST", "/rest/usage/month", data)

        history = result.get("history", [])
        readings = []
        for item in history:
            if item.get("usageDate"):
                readings.append(UsageReading.from_api_response(item))

        return readings

    async def get_power_usage(
        self,
        meter_number: str,
        service_id: str,
        service_number: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[UsageReading]:
        """Convenience method to fetch power usage."""
        return await self.get_usage(
            ServiceType.POWER,
            meter_number,
            service_id,
            service_number,
            from_date,
            to_date,
        )

    async def get_water_usage(
        self,
        meter_number: str,
        service_id: str,
        service_number: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> list[UsageReading]:
        """Convenience method to fetch water usage."""
        return await self.get_usage(
            ServiceType.WATER,
            meter_number,
            service_id,
            service_number,
            from_date,
            to_date,
        )

    async def close(self) -> None:
        """Close the client session."""
        if self._session:
            await self._session.close()
            self._session = None
