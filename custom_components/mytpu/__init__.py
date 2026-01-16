"""Tacoma Public Utilities integration for Home Assistant."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

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
        """Fetch data from TPU."""
        try:
            # Ensure we have account context
            await self.client.get_account_info()

            data: dict[str, Any] = {}

            # Fetch power usage if configured
            if self.power_service:
                power_readings = await self.client.get_power_usage(self.power_service)
                if power_readings:
                    # Get the most recent complete day's reading
                    # (today's reading may be incomplete)
                    latest = power_readings[-1]
                    if len(power_readings) > 1:
                        yesterday = power_readings[-2]
                        data["power"] = {
                            "consumption": yesterday.consumption,
                            "date": yesterday.date,
                            "unit": yesterday.unit,
                            "total": sum(r.consumption for r in power_readings),
                        }
                    else:
                        data["power"] = {
                            "consumption": latest.consumption,
                            "date": latest.date,
                            "unit": latest.unit,
                            "total": latest.consumption,
                        }

            # Fetch water usage if configured
            if self.water_service:
                water_readings = await self.client.get_water_usage(self.water_service)
                if water_readings:
                    latest = water_readings[-1]
                    if len(water_readings) > 1:
                        yesterday = water_readings[-2]
                        data["water"] = {
                            "consumption": yesterday.consumption,
                            "date": yesterday.date,
                            "unit": yesterday.unit,
                            "total": sum(r.consumption for r in water_readings),
                        }
                    else:
                        data["water"] = {
                            "consumption": latest.consumption,
                            "date": latest.date,
                            "unit": latest.unit,
                            "total": latest.consumption,
                        }

            return data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with TPU: {err}") from err
