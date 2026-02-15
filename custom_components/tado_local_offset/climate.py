"""Climate platform for Tado Local Offset."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    SERVICE_SET_HVAC_MODE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ROOM_NAME,
    DEFAULT_DESIRED_TEMP,
    DOMAIN,
    MANUFACTURER,
    MAX_TEMP,
    MIN_TEMP,
    MODEL,
)
from .coordinator import TadoLocalOffsetCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado Local Offset climate from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([TadoLocalOffsetClimate(coordinator, entry)])


class TadoLocalOffsetClimate(CoordinatorEntity[TadoLocalOffsetCoordinator], ClimateEntity):
    """Virtual climate entity for Tado Local Offset."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
    )

    def __init__(
        self,
        coordinator: TadoLocalOffsetCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._room_name = entry.data[CONF_ROOM_NAME]

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{self._room_name} Virtual Thermostat",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version="0.1.0",
        )

        # Temperature limits
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        self._attr_target_temperature_step = 0.5

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature from external sensor."""
        return self.coordinator.data.external_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature (user's desired temperature)."""
        return self.coordinator.data.desired_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode from real Tado."""
        tado_mode = self.coordinator.data.hvac_mode

        # Map Tado states to HVAC modes
        if tado_mode == "heat":
            return HVACMode.HEAT
        elif tado_mode == "off":
            return HVACMode.OFF
        else:
            return HVACMode.AUTO

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return available HVAC modes."""
        return [HVACMode.HEAT, HVACMode.OFF, HVACMode.AUTO]

    @property
    def hvac_action(self) -> str | None:
        """Return current HVAC action from real Tado."""
        return self.coordinator.data.hvac_action

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "temperature_offset": round(self.coordinator.data.offset, 2),
            "compensated_target": round(self.coordinator.data.compensated_target, 1),
            "heating_rate": round(self.coordinator.data.heating_rate, 3),
            "preheat_minutes": self.coordinator.data.preheat_minutes,
            "window_open": self.coordinator.data.window_open,
            "compensation_enabled": self.coordinator.data.compensation_enabled,
            "battery_saver_enabled": self.coordinator.data.battery_saver_enabled,
            "tado_temperature": round(self.coordinator.data.tado_temp, 1),
            "tado_target": round(self.coordinator.data.tado_target, 1),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        # Store desired temperature and trigger compensation
        await self.coordinator.async_set_desired_temperature(temperature)

        # Request refresh to update UI
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode - proxy to real Tado."""
        # Map HVAC mode to Tado state
        if hvac_mode == HVACMode.HEAT:
            tado_mode = "heat"
        elif hvac_mode == HVACMode.OFF:
            tado_mode = "off"
        else:
            tado_mode = "auto"

        # Call real Tado climate entity
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self.coordinator.tado_climate_entity,
                ATTR_HVAC_MODE: tado_mode,
            },
            blocking=True,
        )

        # Request refresh
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on the climate entity."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn off the climate entity."""
        await self.async_set_hvac_mode(HVACMode.OFF)
