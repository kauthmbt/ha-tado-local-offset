"""Sensor platform for Tado Local Offset."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import TadoLocalOffsetCoordinator, TadoLocalOffsetData


@dataclass(frozen=True, kw_only=True)
class TadoLocalOffsetSensorDescription(SensorEntityDescription):
    """Describes Tado Local Offset sensor entity."""

    value_fn: Callable[[TadoLocalOffsetData], float | int | datetime | None]


SENSORS: tuple[TadoLocalOffsetSensorDescription, ...] = (
    TadoLocalOffsetSensorDescription(
        key="temperature_offset",
        name="Temperature Offset",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=2,
        icon="mdi:thermometer-plus",
        value_fn=lambda data: data.offset,
    ),
    TadoLocalOffsetSensorDescription(
        key="heating_rate",
        name="Heating Rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=f"{UnitOfTemperature.CELSIUS}/h",
        suggested_display_precision=3,
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.heating_rate,
    ),
    TadoLocalOffsetSensorDescription(
        key="preheat_time",
        name="Pre-heat Time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:clock-start",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.preheat_minutes,
    ),
    TadoLocalOffsetSensorDescription(
        key="compensated_target",
        name="Compensated Target",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        icon="mdi:thermometer-auto",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.compensated_target,
    ),
    TadoLocalOffsetSensorDescription(
        key="last_compensation",
        name="Last Compensation",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.last_update,
    ),
    TadoLocalOffsetSensorDescription(
        key="next_preheat",
        name="Next Pre-heat Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.next_preheat_start,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado Local Offset sensors from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TadoLocalOffsetSensor(coordinator, entry, description)
        for description in SENSORS
    )


class TadoLocalOffsetSensor(CoordinatorEntity[TadoLocalOffsetCoordinator], SensorEntity):
    """Sensor entity for Tado Local Offset."""

    entity_description: TadoLocalOffsetSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoLocalOffsetCoordinator,
        entry: ConfigEntry,
        description: TadoLocalOffsetSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._room_name = entry.data[CONF_ROOM_NAME]

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{self._room_name} Virtual Thermostat",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version="0.1.0",
        )

    @property
    def native_value(self) -> float | int | datetime | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
