"""Sensor platform for Tacoma Public Utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TPUDataUpdateCoordinator
from .const import (
    CONF_POWER_SERVICE,
    CONF_WATER_SERVICE,
    DOMAIN,
    TPU_POWER_SENSOR_ID_SUFFIX,
    TPU_WATER_SENSOR_ID_SUFFIX,
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


class TPUSensor(CoordinatorEntity[TPUDataUpdateCoordinator], SensorEntity):
    """Base class for TPU sensors."""

    _attr_has_entity_name = True
    _attr_name = None  # Name is derived from translation key

    def __init__(
        self,
        coordinator: TPUDataUpdateCoordinator,
        entry: ConfigEntry,
        unique_id_suffix: str,
        service_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}{unique_id_suffix}"
        self._entry = entry
        self._service_type = service_type

    @property
    def native_value(self) -> float | None:
        """Return the latest daily consumption."""
        if self.coordinator.data and self._service_type in self.coordinator.data:
            return self.coordinator.data[self._service_type]["consumption"]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        attrs = {}
        if self.coordinator.data and self._service_type in self.coordinator.data:
            data = self.coordinator.data[self._service_type]
            attrs["last_reading_date"] = data["date"].isoformat()
            attrs["unit"] = data["unit"]
        return attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Tacoma Public Utilities",
            manufacturer="Tacoma Public Utilities",
            model=self._entry.data.get("account_id"),
            configuration_url="https://www.mytpu.org/",
        )


class TPUEnergySensor(TPUSensor):
    """Sensor for TPU power/energy consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_translation_key = "energy_consumption"

    def __init__(
        self,
        coordinator: TPUDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            TPU_POWER_SENSOR_ID_SUFFIX,
            "power",
        )


class TPUWaterSensor(TPUSensor):
    """Sensor for TPU water consumption."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CENTUM_CUBIC_FEET
    _attr_translation_key = "water_consumption"

    def __init__(
        self,
        coordinator: TPUDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            TPU_WATER_SENSOR_ID_SUFFIX,
            "water",
        )
