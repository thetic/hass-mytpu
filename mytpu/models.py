"""Data models for MyTPU API responses."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ServiceType(Enum):
    """Type of utility service."""
    POWER = "P"
    WATER = "W"


@dataclass
class UsageReading:
    """A single usage reading from the meter."""
    date: datetime
    consumption: float
    unit: str
    high_temp: Optional[float] = None
    low_temp: Optional[float] = None
    demand_peak_time: Optional[datetime] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "UsageReading":
        """Create a UsageReading from API response data."""
        peak_time = None
        if data.get("demandPeakTime"):
            try:
                peak_time = datetime.strptime(data["demandPeakTime"], "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                pass

        return cls(
            date=datetime.strptime(data["usageDate"], "%Y-%m-%d"),
            consumption=data.get("usageConsumptionValue", 0.0),
            unit=data.get("uom", ""),
            high_temp=data.get("usageHighTemp"),
            low_temp=data.get("usageLowTemp"),
            demand_peak_time=peak_time,
        )


@dataclass
class Service:
    """A utility service (meter) on the account."""
    service_id: str
    service_number: str
    meter_number: str
    service_type: ServiceType
    address: str

    @classmethod
    def from_api_response(cls, data: dict) -> "Service":
        """Create a Service from API response data."""
        return cls(
            service_id=data.get("serviceId", ""),
            service_number=data.get("serviceNumber", ""),
            meter_number=data.get("meterNumber", ""),
            service_type=ServiceType(data.get("serviceType", "P")),
            address=data.get("serviceAddress", ""),
        )
