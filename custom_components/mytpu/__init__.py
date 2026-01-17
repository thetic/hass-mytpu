"""Tacoma Public Utilities integration for Home Assistant."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import MyTPUClient
from .const import CONF_POWER_SERVICE, CONF_WATER_SERVICE, DOMAIN, UPDATE_INTERVAL_HOURS
from .models import Service, ServiceType

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _service_from_config(config_json: str) -> Service:
    """Reconstruct a Service object from stored JSON config."""
    data = json.loads(config_json)
    return Service(
        service_id=data["service_id"],
        service_number=data["service_number"],
        meter_number=data["meter_number"],
        display_meter_number=data["display_meter_number"],
        service_type=ServiceType(data["service_type"]),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        contract_number=data.get("contract_number"),
        totalizer=data.get("totalizer", False),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tacoma Public Utilities from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = MyTPUClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    coordinator = TPUDataUpdateCoordinator(hass, client, entry.data)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()

    return unload_ok


class TPUDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching TPU data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: MyTPUClient,
        config: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )
        self.client = client
        self.config = config

        # Parse service configs from JSON
        self.power_service: Service | None = None
        self.water_service: Service | None = None
        if config.get(CONF_POWER_SERVICE):
            self.power_service = _service_from_config(config[CONF_POWER_SERVICE])
        if config.get(CONF_WATER_SERVICE):
            self.water_service = _service_from_config(config[CONF_WATER_SERVICE])

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TPU and update statistics."""
        try:
            # Ensure we have account context
            await self.client.get_account_info()

            data: dict[str, Any] = {}

            # Fetch and import power usage statistics
            if self.power_service:
                power_readings = await self.client.get_power_usage(self.power_service)
                if power_readings:
                    await self._import_statistics(
                        self.power_service, power_readings, "energy"
                    )
                    # Keep latest reading in data for sensor attributes
                    latest = power_readings[-1]
                    data["power"] = {
                        "consumption": latest.consumption,
                        "date": latest.date,
                        "unit": latest.unit,
                    }

            # Fetch and import water usage statistics
            if self.water_service:
                water_readings = await self.client.get_water_usage(self.water_service)
                if water_readings:
                    await self._import_statistics(
                        self.water_service, water_readings, "water"
                    )
                    # Keep latest reading in data for sensor attributes
                    latest = water_readings[-1]
                    data["water"] = {
                        "consumption": latest.consumption,
                        "date": latest.date,
                        "unit": latest.unit,
                    }

            return data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with TPU: {err}") from err

    async def _import_statistics(
        self, service: Service, readings: list, stat_type: str
    ) -> None:
        """Import historical usage data as statistics."""
        if not readings:
            return

        # Create statistic_id based on service
        # Sanitize to avoid validation errors: lowercase and replace hyphens
        meter_id = f"{service.service_type.value}_{service.meter_number}".replace(
            "-", "_"
        ).lower()
        statistic_id = f"{DOMAIN}:{meter_id}_{stat_type}"

        # Get the last imported statistic to avoid duplicates and calculate cumulative sum
        last_stats = await self.hass.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )

        # Start cumulative sum from last known value or 0
        cumulative_sum = 0.0
        last_stat_time = None
        if statistic_id in last_stats:
            last_stat = last_stats[statistic_id][0]
            cumulative_sum = last_stat.get("sum", 0.0)
            last_stat_time = last_stat.get("start")

        # Create metadata based on type
        if stat_type == "energy":
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"TPU Energy {service.display_meter_number}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class="energy",
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            )
        else:  # water
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"TPU Water {service.display_meter_number}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class="volume",
                unit_of_measurement=UnitOfVolume.CENTUM_CUBIC_FEET,
            )

        # Convert readings to StatisticData
        statistics: list[StatisticData] = []
        for reading in readings:
            # Convert date to UTC datetime at start of day
            start_time = dt_util.as_utc(reading.date)

            # Skip if we've already imported this date
            if last_stat_time and start_time <= last_stat_time:
                continue

            # Add consumption to cumulative sum
            cumulative_sum += reading.consumption

            statistics.append(
                StatisticData(
                    start=start_time,
                    state=reading.consumption,
                    sum=cumulative_sum,
                )
            )

        # Import the statistics
        if statistics:
            async_add_external_statistics(self.hass, metadata, statistics)
