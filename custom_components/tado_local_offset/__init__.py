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

# Service schemas
SERVICE_FORCE_COMPENSATION_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})
SERVICE_RESET_LEARNING_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})
SERVICE_SET_PREHEAT_SCHEMA = vol.Schema({
    vol.Required(ATTR_ENTITY_ID): cv.entity_id,
    vol.Required(ATTR_TARGET_TIME): cv.time,
    vol.Required(ATTR_TARGET_TEMPERATURE): vol.Coerce(float),
})

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado Local Offset from a config entry."""

    def get_setting(key: str, default: Any) -> Any:
        return entry.options.get(key, entry.data.get(key, default))

    # 1. Erstellung des Coordinators
    coordinator = TadoLocalOffsetCoordinator(hass, entry)

    # 2. Alle Attribute zuweisen (Identisch zu deiner coordinator.py Struktur)
    coordinator.room_name = entry.data[CONF_ROOM_NAME]
    coordinator.tado_device = entry.data[CONF_TADO_DEVICE]
    coordinator.tado_climate_entity = entry.data[CONF_TADO_CLIMATE_ENTITY]
    coordinator.tado_temp_sensor = entry.data[CONF_TADO_TEMP_SENSOR]
    coordinator.tado_humidity_sensor = entry.data.get(CONF_TADO_HUMIDITY_SENSOR)
    coordinator.external_temp_sensor = entry.data[CONF_EXTERNAL_TEMP_SENSOR]
    
    coordinator.tolerance = get_setting(CONF_TOLERANCE, DEFAULT_TOLERANCE)
    coordinator.backoff_minutes = get_setting(CONF_BACKOFF_MINUTES, DEFAULT_BACKOFF_MINUTES)
    coordinator.enable_battery_saver = get_setting(CONF_ENABLE_BATTERY_SAVER, True)
    coordinator.enable_window_detection = get_setting(CONF_ENABLE_WINDOW_DETECTION, False)
    coordinator.window_sensor = get_setting(CONF_WINDOW_SENSOR, [])
    coordinator.enable_temp_drop_detection = get_setting(CONF_ENABLE_TEMP_DROP_DETECTION, False)
    coordinator.temp_drop_threshold = get_setting(CONF_TEMP_DROP_THRESHOLD, DEFAULT_TEMP_DROP_THRESHOLD)
    coordinator.enable_preheat = get_setting(CONF_ENABLE_PREHEAT, False)
    coordinator.learning_buffer = get_setting(CONF_LEARNING_BUFFER, DEFAULT_LEARNING_BUFFER)
    coordinator.min_preheat_minutes = get_setting(CONF_MIN_PREHEAT_MINUTES, DEFAULT_MIN_PREHEAT_MINUTES)
    coordinator.max_preheat_minutes = get_setting(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)

    # 3. Initialisierung der gelernten Daten aus dem JSON-Speicher
    await coordinator.async_load_data()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- SERVICE HANDLER ---
    async def handle_force_compensation(call: ServiceCall) -> None:
        """Erzwinge sofortige Berechnung."""
        _LOGGER.debug("Service force_compensation called")
        for entry_id in hass.data[DOMAIN]:
            coord = hass.data[DOMAIN][entry_id]
            # Aufruf der korrekten Methode in deiner coordinator.py (Zeile 356)
            await coord.async_force_compensation()
            await coord.async_request_refresh()

    async def handle_reset_learning(call: ServiceCall) -> None:
        """Löscht die historische Heizrate und startet das Lernen neu."""
        _LOGGER.warning("Service reset_learning called - Clearing history")
        for entry_id in hass.data[DOMAIN]:
            coord = hass.data[DOMAIN][entry_id]
            # Aufruf der korrekten Methode in deiner coordinator.py (Zeile 365)
            await coord.async_reset_learning()
            await coord.async_request_refresh()

    async def handle_set_preheat(call: ServiceCall) -> None:
        """Komplexe Vorheiz-Logik basierend auf der gelernten Heizrate."""
        entity_id = call.data[ATTR_ENTITY_ID]
        target_time_only = call.data[ATTR_TARGET_TIME]
        target_temperature = call.data[ATTR_TARGET_TEMPERATURE]
        
        ent_reg = er.async_get(hass)
        entry_data = ent_reg.async_get(entity_id)
        
        if not entry_data or entry_data.config_entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Entity %s not found in Tado Local Offset", entity_id)
            return

        coordinator = hass.data[DOMAIN][entry_data.config_entry_id]
        
        # Berechnung der Ziel-Zeit
        now = dt_util.now()
        target_datetime = datetime.combine(now.date(), target_time_only).replace(tzinfo=now.tzinfo)
        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        # Nutzt die interne Logik deines Coordinators (Zeile 330)
        preheat_minutes = coordinator._calculate_preheat_minutes()
        preheat_start = target_datetime - timedelta(minutes=preheat_minutes)
        
        # Den Planer im Coordinator setzen
        coordinator.data.next_preheat_start = preheat_start
        coordinator.data.next_preheat_temp = target_temperature # Falls dieses Attribut existiert
        
        time_until = (target_datetime - now).total_seconds() / 60

        if preheat_minutes >= time_until:
            coordinator.data.next_preheat_start = None
            # Direkter Aufruf der Heiz-Methode (Zeile 240)
            await coordinator.async_set_desired_temperature(target_temperature)
            _LOGGER.info("Starting immediate pre-heat for %s", coordinator.room_name)
        else:
            _LOGGER.info("Pre-heat for %s scheduled for %s", coordinator.room_name, preheat_start)

        await coordinator.async_request_refresh()

    # Services registrieren
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_COMPENSATION):
        hass.services.async_register(DOMAIN, SERVICE_FORCE_COMPENSATION, handle_force_compensation, schema=SERVICE_FORCE_COMPENSATION_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_RESET_LEARNING):
        hass.services.async_register(DOMAIN, SERVICE_RESET_LEARNING, handle_reset_learning, schema=SERVICE_RESET_LEARNING_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_PREHEAT):
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