"""Sensor platform for Tacoma Public Utilities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TPUDataUpdateCoordinator
from .const import (
    CONF_POWER_SERVICE,
    CONF_WATER_SERVICE,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TPU sensors from a config entry."""
    coordinator: TPUDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # Add power sensor if configured
    if entry.data.get(CONF_POWER_SERVICE):
        entities.append(TPUEnergySensor(coordinator, entry))

    # Add water sensor if configured
    if entry.data.get(CONF_WATER_SERVICE):
        entities.append(TPUWaterSensor(coordinator, entry))

    async_add_entities(entities)


class TPUEnergySensor(CoordinatorEntity[TPUDataUpdateCoordinator], SensorEntity):
    """Sensor for TPU power/energy consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True
    _attr_name = "Energy Consumption"

    def __init__(
        self,
        coordinator: TPUDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_energy"
        self._entry = entry

    @property
    def native_value(self) -> float | None:
        """Return the total energy consumption."""
        if self.coordinator.data and "power" in self.coordinator.data:
            return self.coordinator.data["power"]["total"]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        if self.coordinator.data and "power" in self.coordinator.data:
            power_data = self.coordinator.data["power"]
            attrs["last_reading_date"] = power_data["date"].isoformat()
            attrs["last_reading_consumption"] = power_data["consumption"]
        return attrs


class TPUWaterSensor(CoordinatorEntity[TPUDataUpdateCoordinator], SensorEntity):
    """Sensor for TPU water consumption."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CENTUM_CUBIC_FEET
    _attr_has_entity_name = True
    _attr_name = "Water Consumption"

    def __init__(
        self,
        coordinator: TPUDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_water"
        self._entry = entry

    @property
    def native_value(self) -> float | None:
        """Return the total water consumption."""
        if self.coordinator.data and "water" in self.coordinator.data:
            return self.coordinator.data["water"]["total"]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        if self.coordinator.data and "water" in self.coordinator.data:
            water_data = self.coordinator.data["water"]
            attrs["last_reading_date"] = water_data["date"].isoformat()
            attrs["last_reading_consumption"] = water_data["consumption"]
        return attrs
