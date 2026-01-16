"""Data models for MyTPU API responses."""

import contextlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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
    high_temp: float | None = None
    low_temp: float | None = None
    demand_peak_time: datetime | None = None

    @classmethod
    def from_api_response(cls, data: dict) -> "UsageReading":
        """Create a UsageReading from API response data."""
        peak_time = None
        if data.get("demandPeakTime"):
            with contextlib.suppress(ValueError, TypeError):
                peak_time = datetime.strptime(data["demandPeakTime"], "%Y-%m-%d %H:%M")

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
    device_location: str
    service_type: ServiceType

    @classmethod
    def from_api_response(cls, data: dict) -> "Service":
        """Create a Service from API response data."""
        return cls(
            service_id=data.get("serviceId", ""),
            service_number=data.get("serviceNumber", ""),
            meter_number=data.get("meterNumber", ""),
            device_location=data.get("deviceLocation", ""),
            service_type=ServiceType(data.get("serviceType", "P")),
        )
