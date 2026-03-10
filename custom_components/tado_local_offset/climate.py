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
    DOMAIN,
    MANUFACTURER,
    MAX_TEMP,
    MIN_TEMP,
    MODEL,
)
from .coordinator import TadoLocalOffsetCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Tado Local Offset climate from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TadoLocalOffsetClimate(coordinator, entry)])

class TadoLocalOffsetClimate(CoordinatorEntity[TadoLocalOffsetCoordinator], ClimateEntity):
    """Virtual climate entity for Tado Local Offset."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = 0.1  # Added to ensure correct decimal display in UI
    
    # Define supported features for modern HA versions
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE 
        | ClimateEntityFeature.TURN_OFF 
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(self, coordinator: TadoLocalOffsetCoordinator, entry: ConfigEntry) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        # Use a safe slug for the unique ID
        room_slug = str(coordinator.room_name).lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{room_slug}_climate"
        
        # SAFE ACCESS: Use .get() to avoid KeyError during initialization
        self._room_name = entry.data.get(CONF_ROOM_NAME, coordinator.room_name)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{self._room_name} Virtual Thermostat",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version="0.1.0",
        )
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        self._attr_target_temperature_step = 0.5
        self._attr_precision = 0.1 # Crucial for UI and internal float handling

    @property
    def current_temperature(self) -> float | None:
        """Return the current external temperature."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.external_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the desired target temperature."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.desired_temp

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current hvac mode - defaults to HEAT unless OFF is reported."""
        if not self.coordinator.data or self.coordinator.data.hvac_mode == "off":
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of supported hvac operation modes."""
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def hvac_action(self) -> str | None:
        """Return the current running hvac action."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.hvac_action

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes for analysis."""
        if not self.coordinator.data:
            return {}
            
        return {
            "preheat_order_target": self.coordinator.data.preheat_order_target,
            "next_preheat_start": self.coordinator.data.next_preheat_start,
            "preheat_minutes": self.coordinator.data.preheat_minutes,
            "last_learning_rate": self.coordinator.data.last_learning_rate
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode - proxy to real Tado."""
        tado_mode = "heat" if hvac_mode == HVACMode.HEAT else "off"

        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: self.coordinator.tado_climate_entity, ATTR_HVAC_MODE: tado_mode},
            blocking=False,
        )
        # Sofortige Spiegelung für UI-Stabilität
        self.coordinator.data.hvac_mode = tado_mode
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_set_desired_temperature(temperature)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)