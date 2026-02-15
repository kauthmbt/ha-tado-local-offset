"""Number platform for Tado Local Offset."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ROOM_NAME,
    DEFAULT_DESIRED_TEMP,
    DOMAIN,
    MANUFACTURER,
    MAX_BACKOFF,
    MAX_TEMP,
    MAX_TOLERANCE,
    MIN_BACKOFF,
    MIN_TEMP,
    MIN_TOLERANCE,
    MODEL,
)
from .coordinator import TadoLocalOffsetCoordinator


@dataclass(frozen=True, kw_only=True)
class TadoLocalOffsetNumberDescription(NumberEntityDescription):
    """Describes Tado Local Offset number entity."""

    set_fn: Callable[[TadoLocalOffsetCoordinator, float], None]
    get_fn: Callable[[TadoLocalOffsetCoordinator], float]


NUMBERS: tuple[TadoLocalOffsetNumberDescription, ...] = (
    TadoLocalOffsetNumberDescription(
        key="desired_temperature",
        name="Desired Temperature",
        icon="mdi:thermometer",
        native_min_value=MIN_TEMP,
        native_max_value=MAX_TEMP,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        set_fn=lambda coord, value: setattr(coord.data, "desired_temp", value),
        get_fn=lambda coord: coord.data.desired_temp,
    ),
    TadoLocalOffsetNumberDescription(
        key="tolerance",
        name="Tolerance",
        icon="mdi:thermometer-lines",
        entity_category=EntityCategory.CONFIG,
        native_min_value=MIN_TOLERANCE,
        native_max_value=MAX_TOLERANCE,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        set_fn=lambda coord, value: setattr(coord, "tolerance", value),
        get_fn=lambda coord: coord.tolerance,
    ),
    TadoLocalOffsetNumberDescription(
        key="backoff_minutes",
        name="Backoff Minutes",
        icon="mdi:timer-sand",
        entity_category=EntityCategory.CONFIG,
        native_min_value=MIN_BACKOFF,
        native_max_value=MAX_BACKOFF,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        set_fn=lambda coord, value: setattr(coord, "backoff_minutes", int(value)),
        get_fn=lambda coord: float(coord.backoff_minutes),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado Local Offset numbers from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TadoLocalOffsetNumber(coordinator, entry, description)
        for description in NUMBERS
    )


class TadoLocalOffsetNumber(CoordinatorEntity[TadoLocalOffsetCoordinator], NumberEntity):
    """Number entity for Tado Local Offset."""

    entity_description: TadoLocalOffsetNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoLocalOffsetCoordinator,
        entry: ConfigEntry,
        description: TadoLocalOffsetNumberDescription,
    ) -> None:
        """Initialize the number."""
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
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_description.get_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self.entity_description.set_fn(self.coordinator, value)

        # If setting desired temperature, trigger compensation
        if self.entity_description.key == "desired_temperature":
            await self.coordinator.async_calculate_and_apply_compensation()

        await self.coordinator.async_request_refresh()
