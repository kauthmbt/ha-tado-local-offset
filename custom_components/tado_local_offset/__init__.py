"""The Tado Local Offset integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_TARGET_TEMPERATURE, ATTR_TARGET_TIME, CONF_BACKOFF_MINUTES,
    CONF_ENABLE_BATTERY_SAVER, CONF_ENABLE_PREHEAT, CONF_ENABLE_TEMP_DROP_DETECTION,
    CONF_ENABLE_WINDOW_DETECTION, CONF_EXTERNAL_TEMP_SENSOR, CONF_LEARNING_BUFFER,
    CONF_MAX_PREHEAT_MINUTES, CONF_MIN_PREHEAT_MINUTES, CONF_ROOM_NAME,
    CONF_TADO_CLIMATE_ENTITY, CONF_TADO_DEVICE, CONF_TADO_HUMIDITY_SENSOR,
    CONF_TADO_TEMP_SENSOR, CONF_TEMP_DROP_THRESHOLD, CONF_TOLERANCE,
    CONF_WINDOW_SENSOR, DEFAULT_BACKOFF_MINUTES, DEFAULT_LEARNING_BUFFER,
    DEFAULT_MAX_PREHEAT_MINUTES, DEFAULT_MIN_PREHEAT_MINUTES,
    DEFAULT_TEMP_DROP_THRESHOLD, DEFAULT_TOLERANCE, DOMAIN, PLATFORMS,
    SERVICE_FORCE_COMPENSATION, SERVICE_RESET_LEARNING, SERVICE_SET_PREHEAT,
)
from .coordinator import TadoLocalOffsetCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_FORCE_COMPENSATION_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
})

SERVICE_RESET_LEARNING_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.comp_entity_ids,
})

SERVICE_SET_PREHEAT_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Required(ATTR_TARGET_TIME): cv.time,
    vol.Required(ATTR_TARGET_TEMPERATURE): vol.Coerce(float),
})

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado Local Offset from a config entry."""
    coordinator = TadoLocalOffsetCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Help function to identify the right coordinators ---
    def get_coordinators_from_call(call: ServiceCall) -> list[TadoLocalOffsetCoordinator]:
        target_entity_ids = call.data.get(ATTR_ENTITY_ID)
        
        # If no entity_id is choosen, use ALL
        if not target_entity_ids:
            return list(hass.data[DOMAIN].values())
            
        # Convert to list if it is only a string
        if isinstance(target_entity_ids, str):
            target_entity_ids = [target_entity_ids]
            
        ent_reg = er.async_get(hass)
        coordinators = []
        for entity_id in target_entity_ids:
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.config_entry_id in hass.data[DOMAIN]:
                coordinators.append(hass.data[DOMAIN][entity_entry.config_entry_id])
        return coordinators

    # --- SERVICE HANDLER ---

    async def handle_force_compensation(call: ServiceCall) -> None:
        """Erzwingt ein Update für die gewählten Entitäten."""
        for coordinator in get_coordinators_from_call(call):
            _LOGGER.info("Forcing compensation for %s", coordinator.room_name)
            await coordinator.async_force_compensation()
            await coordinator.async_request_refresh()

    async def handle_reset_learning(call: ServiceCall) -> None:
        """Löscht die Historie gezielt für die gewählten Entitäten."""
        for coordinator in get_coordinators_from_call(call):
            _LOGGER.warning("Resetting learning for %s", coordinator.room_name)
            await coordinator.async_reset_learning()
            await coordinator.async_request_refresh()

    async def handle_set_preheat(call: ServiceCall) -> None:
        """Setzt die Pre-heat Parameter und lässt den Coordinator entscheiden."""
        # Since set_preheat only allows one entity according to the schema:
        entity_id = call.data[ATTR_ENTITY_ID]
        ent_reg = er.async_get(hass)
        entity_entry = ent_reg.async_get(entity_id)

        if entity_entry and entity_entry.config_entry_id in hass.data[DOMAIN]:
            coordinator = hass.data[DOMAIN][entity_entry.config_entry_id]
            
            # Here, only the data is transferred; the logic is handled by the coordinator
            coordinator.data.target_time = call.data[ATTR_TARGET_TIME]
            coordinator.data.target_temperature = call.data[ATTR_TARGET_TEMPERATURE]
            
            _LOGGER.info(
                "Pre-heat for %s set to %s at %.1f°C",
                coordinator.room_name,
                coordinator.data.target_time,
                coordinator.data.target_temperature
            )
            # Trigger immediate update so that the coordinator can check whether it needs to start NOW
            await coordinator.async_request_refresh()

    # Register the services/actions
    hass.services.async_register(DOMAIN, SERVICE_FORCE_COMPENSATION, handle_force_compensation, schema=SERVICE_FORCE_COMPENSATION_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_LEARNING, handle_reset_learning, schema=SERVICE_RESET_LEARNING_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_PREHEAT, handle_set_preheat, schema=SERVICE_SET_PREHEAT_SCHEMA)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok