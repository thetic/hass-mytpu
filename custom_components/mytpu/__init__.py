"""Tacoma Public Utilities integration for Home Assistant."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta
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
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import AuthError, MyTPUAuth, ServerError
from .client import MyTPUClient, MyTPUError
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

_SERVER_ERROR_REAUTH_THRESHOLD = 3


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


async def _background_token_refresh(
    hass: HomeAssistant, entry: ConfigEntry, client: MyTPUClient
) -> None:
    """Background task to proactively refresh tokens before they expire.

    Runs every 45 minutes. With a 1-hour token lifetime, this wakes up when
    ~15 minutes remain and refreshes while the token is still valid — the
    server may only accept refresh_token grants before the access_token expires.
    """
    _LOGGER.info("Starting background token refresh task (every 45 minutes)")

    while True:
        try:
            await asyncio.sleep(45 * 60)  # 45 minutes

            _LOGGER.debug("Background token refresh: checking if refresh needed")

            # Proactively refresh if the token expires within 15 minutes (900s).
            # This runs while the access_token is still valid, which may be
            # required by the MyTPU server (it returns 500 for already-expired tokens).
            refreshed = await client.async_refresh_token_if_expiring(
                min_remaining_seconds=900
            )

            if refreshed:
                token_data = client.get_token_data()
                if token_data and token_data != entry.data.get(CONF_TOKEN_DATA):
                    _LOGGER.info("Background token refresh: saving updated tokens")
                    new_data = {**entry.data, CONF_TOKEN_DATA: token_data}
                    hass.config_entries.async_update_entry(entry, data=new_data)
                else:
                    _LOGGER.debug(
                        "Background token refresh: token data unchanged after refresh"
                    )
            else:
                _LOGGER.debug(
                    "Background token refresh: token still fresh, no action needed"
                )

        except asyncio.CancelledError:
            _LOGGER.info("Background token refresh task cancelled")
            raise
        except AuthError as err:
            _LOGGER.warning(
                "Background token refresh failed (auth error): %s. "
                "User will need to reauth.",
                err,
            )
            # Don't raise - let the coordinator handle reauth on next update
        except ServerError as err:
            _LOGGER.warning(
                "Background token refresh failed (server error): %s. Will retry.", err
            )
        except Exception as err:
            _LOGGER.error(
                "Background token refresh encountered unexpected error: %s. Will retry.",
                err,
            )
            # Continue running despite errors


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tacoma Public Utilities from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    auth = MyTPUAuth(entry.data.get(CONF_TOKEN_DATA))
    client = MyTPUClient(auth)

    # Migrate old config format (password) to new format (token_data)
    if not entry.data.get(CONF_TOKEN_DATA) and CONF_PASSWORD in entry.data:
        _LOGGER.info("Migrating old config format to token-based authentication")
        try:
            async with client:
                if client._session is not None:
                    await auth.async_login(
                        entry.data[CONF_USERNAME],
                        entry.data[CONF_PASSWORD],
                        client._session,
                    )
                    token_data = auth.get_token_data()
                    if token_data:
                        # Save tokens and remove password
                        new_data = {**entry.data, CONF_TOKEN_DATA: token_data}
                        del new_data[CONF_PASSWORD]
                        hass.config_entries.async_update_entry(entry, data=new_data)
                        _LOGGER.info(
                            "Migration to token-based authentication successful"
                        )
        except AuthError as err:
            _LOGGER.error("Failed to migrate config - authentication failed: %s", err)
            raise ConfigEntryAuthFailed(
                f"Authentication failed during config migration: {err}"
            ) from err
        except Exception as err:
            _LOGGER.error("Failed to migrate config: %s", err)
            raise ConfigEntryAuthFailed(f"Failed to migrate config: {err}") from err

    coordinator = TPUDataUpdateCoordinator(hass, client, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await client.close()
        # During setup, a server error on token refresh means the token is likely
        # expired. MyTPU returns 500 for expired refresh tokens instead of 401,
        # so we must detect this and raise ConfigEntryAuthFailed to trigger reauth
        # rather than letting HA retry setup indefinitely via ConfigEntryNotReady.
        cause: BaseException | None = err.__cause__
        while cause is not None:
            if isinstance(cause, ServerError):
                _LOGGER.warning(
                    "Server error during setup (likely expired token) - requesting reauth"
                )
                raise ConfigEntryAuthFailed(
                    "Token refresh failed during setup - please re-authenticate"
                ) from err
            cause = cause.__cause__
        raise

    # Start background token refresh task to keep tokens fresh
    # MyTPU's refresh tokens only last 2 hours, so we refresh every 45 minutes
    refresh_task = hass.async_create_task(
        _background_token_refresh(hass, entry, client),
        name=f"mytpu_token_refresh_{entry.entry_id}",
    )

    # Store coordinator and refresh task
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "refresh_task": refresh_task,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Ensure refresh task is cancelled when entry is unloaded
    entry.async_on_unload(lambda: refresh_task.cancel())

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator = entry_data["coordinator"]
        refresh_task = entry_data["refresh_task"]

        # Cancel the background refresh task
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task

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
        self._consecutive_server_errors = 0

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
                power_statistic_id = (
                    f"{DOMAIN}:{self.power_service.service_type.value}_{self.power_service.meter_number}".replace(
                        "-", "_"
                    ).lower()
                    + "_energy"
                )
                last_power_stats = await self.hass.async_add_executor_job(
                    get_last_statistics, self.hass, 1, power_statistic_id, True, {"sum"}
                )
                last_power_stat_time: float | None = None
                if power_statistic_id in last_power_stats:
                    last_power_stat_time = last_power_stats[power_statistic_id][0].get(
                        "start"
                    )

                power_from_date: datetime | None = None
                if last_power_stat_time:
                    # Request data starting from the day after the last recorded statistic
                    # Convert the Unix timestamp (float) back to a datetime object
                    power_from_date = datetime.fromtimestamp(
                        last_power_stat_time
                    ) + timedelta(days=1)
                    # Set time to midnight UTC for consistency with how usageDate is parsed in models.py
                    power_from_date = power_from_date.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                power_readings = await self.client.get_usage(
                    self.power_service, from_date=power_from_date
                )
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
                water_statistic_id = (
                    f"{DOMAIN}:{self.water_service.service_type.value}_{self.water_service.meter_number}".replace(
                        "-", "_"
                    ).lower()
                    + "_water"
                )
                last_water_stats = await self.hass.async_add_executor_job(
                    get_last_statistics, self.hass, 1, water_statistic_id, True, {"sum"}
                )
                last_water_stat_time: float | None = None
                if water_statistic_id in last_water_stats:
                    last_water_stat_time = last_water_stats[water_statistic_id][0].get(
                        "start"
                    )

                water_from_date: datetime | None = None
                if last_water_stat_time:
                    # Request data starting from the day after the last recorded statistic
                    # Convert the Unix timestamp (float) back to a datetime object
                    water_from_date = datetime.fromtimestamp(
                        last_water_stat_time
                    ) + timedelta(days=1)
                    # Set time to midnight UTC for consistency with how usageDate is parsed in models.py
                    water_from_date = water_from_date.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                water_readings = await self.client.get_usage(
                    self.water_service, from_date=water_from_date
                )
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

            # Save token data again in case it was refreshed during usage fetching
            await self._save_token_data()

            self._consecutive_server_errors = 0
            return data

        except AuthError as err:
            # Trigger reauth flow so user is prompted to re-authenticate
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except ServerError as err:
            self._consecutive_server_errors += 1
            if self._consecutive_server_errors >= _SERVER_ERROR_REAUTH_THRESHOLD:
                _LOGGER.warning(
                    "Server error on token refresh for %d consecutive updates "
                    "(likely expired token) - requesting reauth",
                    self._consecutive_server_errors,
                )
                raise ConfigEntryAuthFailed(
                    "Token refresh consistently failing - please re-authenticate"
                ) from err
            _LOGGER.warning(
                "MyTPU server error (will retry, %d/%d): %s",
                self._consecutive_server_errors,
                _SERVER_ERROR_REAUTH_THRESHOLD,
                err,
            )
            raise UpdateFailed(f"MyTPU server error: {err}") from err
        except MyTPUError as err:
            raise UpdateFailed(f"API request failed: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error communicating with TPU")
            raise UpdateFailed(
                f"Unexpected error communicating with TPU: {err}"
            ) from err

    async def _save_token_data(self) -> None:
        """Save updated token data to config entry if changed."""
        token_data = self.client.get_token_data()
        if token_data and token_data != self.config_entry.data.get(CONF_TOKEN_DATA):
            _LOGGER.debug("Token data changed, saving to config entry")
            new_data = {**self.config_entry.data, CONF_TOKEN_DATA: token_data}
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            _LOGGER.info("Token data saved successfully")
        else:
            _LOGGER.debug("Token data unchanged, no save needed")

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
