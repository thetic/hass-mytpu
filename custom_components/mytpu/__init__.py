"""Tacoma Public Utilities integration for Home Assistant."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import MyTPUClient
from .const import (
    CONF_POWER_SERVICE,
    CONF_TOKEN_DATA,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_WATER_SERVICE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
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
        entry.data.get(CONF_TOKEN_DATA),
    )

    coordinator = TPUDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()

    return unload_ok


class TPUDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching TPU data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: MyTPUClient,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        update_interval_hours = config_entry.options.get(
            CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=update_interval_hours),
        )
        self.client = client
        self.config_entry = config_entry

        # Parse service configs from JSON
        self.power_service: Service | None = None
        self.water_service: Service | None = None
        if config_entry.data.get(CONF_POWER_SERVICE):
            self.power_service = _service_from_config(
                config_entry.data[CONF_POWER_SERVICE]
            )
        if config_entry.data.get(CONF_WATER_SERVICE):
            self.water_service = _service_from_config(
                config_entry.data[CONF_WATER_SERVICE]
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TPU and update statistics."""
        try:
            # Ensure we have account context
            await self.client.get_account_info()

            # Save updated token data to config entry if changed
            await self._save_token_data()

            data: dict[str, Any] = {}

            # Fetch and import power usage statistics
            if self.power_service:
                power_readings = await self.client.get_usage(self.power_service)
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
                water_readings = await self.client.get_usage(self.water_service)
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

    async def _save_token_data(self) -> None:
        """Save updated token data to config entry if changed."""
        token_data = self.client.get_token_data()
        if token_data and token_data != self.config_entry.data.get(CONF_TOKEN_DATA):
            new_data = {**self.config_entry.data, CONF_TOKEN_DATA: token_data}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

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
        last_stat_time: float | None = None
        if statistic_id in last_stats:
            last_stat = last_stats[statistic_id][0]
            cumulative_sum = last_stat.get("sum", 0.0)
            # start is returned as a Unix timestamp (float), not a datetime
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

        # If this is the first import (no previous statistics), add a baseline
        # statistic with sum=0 just before the first reading. This ensures the
        # Energy Dashboard correctly shows the first day's consumption instead
        # of the cumulative total.
        if cumulative_sum == 0.0 and readings:
            # readings[0].date is already UTC-aware from models.py
            first_reading_time = readings[0].date
            # Subtract 1 day to get previous day at midnight (valid hour boundary)
            baseline_time = first_reading_time - timedelta(days=1)
            statistics.append(
                StatisticData(
                    start=baseline_time,
                    state=0.0,
                    sum=0.0,
                )
            )

        for reading in readings:
            # reading.date is already UTC-aware from models.py
            start_time = reading.date

            # Skip if we've already imported this date
            # Compare using Unix timestamps like opower does
            if last_stat_time and start_time.timestamp() <= last_stat_time:
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
