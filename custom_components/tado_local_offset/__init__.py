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
    ATTR_TARGET_TEMPERATURE,
    ATTR_TARGET_TIME,
    DOMAIN,
    PLATFORMS,
    SERVICE_FORCE_COMPENSATION,
    SERVICE_RESET_LEARNING,
    SERVICE_SET_PREHEAT,
)
from .coordinator import TadoLocalOffsetCoordinator

_LOGGER = logging.getLogger(__name__)

# Service schemas
SERVICE_FORCE_COMPENSATION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

SERVICE_RESET_LEARNING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

SERVICE_SET_PREHEAT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_TARGET_TIME): cv.time,  # Geändert von datetime auf time
        vol.Required(ATTR_TARGET_TEMPERATURE): vol.Coerce(float),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado Local Offset from a config entry."""
    # Create coordinator
    coordinator = TadoLocalOffsetCoordinator(hass, entry)

    # 2. Die gespeicherten JSON-Daten laden, bevor die Sensoren erstellt werden
    await coordinator.async_load_data()
    # ---------------------------
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_COMPENSATION):
        async_register_services(hass)

    # Register update listener for options
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove coordinator
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def handle_force_compensation(call: ServiceCall) -> None:
        """Handle force compensation service call."""
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        ent_reg = er.async_get(hass) # Registry laden
        
        # Wenn keine entity_ids angegeben wurden, nehmen wir alle Coordinatoren dieser Domain
        if not entity_ids:
            coordinators = list(hass.data[DOMAIN].values())
        else:
            coordinators = []
            for ent_id in entity_ids:
                entry = ent_reg.async_get(ent_id)
                if entry and entry.config_entry_id in hass.data[DOMAIN]:
                    coordinators.append(hass.data[DOMAIN][entry.config_entry_id])
                else:
                    _LOGGER.warning("Entity %s gehört nicht zu Tado Local Offset", ent_id)

        for coordinator in coordinators:
            await coordinator.async_force_compensation()
            await coordinator.async_request_refresh()

    async def handle_reset_learning(call: ServiceCall) -> None:
        """Handle reset learning service call."""
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        ent_reg = er.async_get(hass) # Registry laden

        if not entity_ids:
            coordinators = list(hass.data[DOMAIN].values())
        else:
            coordinators = []
            for ent_id in entity_ids:
                entry = ent_reg.async_get(ent_id)
                if entry and entry.config_entry_id in hass.data[DOMAIN]:
                    coordinators.append(hass.data[DOMAIN][entry.config_entry_id])

        for coordinator in coordinators:
            await coordinator.async_reset_learning()
            await coordinator.async_request_refresh()

    async def handle_set_preheat(call: ServiceCall) -> None:
        """Handle set_preheat service call."""
        # Wir holen uns die Entity Registry von HA
        ent_reg = er.async_get(hass)
        
        # Entity ID aus dem Call (kann eine Liste oder ein String sein)
        entity_id = call.data[ATTR_ENTITY_ID]
        target_time_only = call.data[ATTR_TARGET_TIME]
        target_temperature = call.data[ATTR_TARGET_TEMPERATURE]

        # 1. Finde den Registry-Eintrag für die aufgerufene Entity
        entry_data = ent_reg.async_get(entity_id)
        
        if not entry_data:
            _LOGGER.error("Entity %s not found in registry", entity_id)
            return

        # 2. Hole die Entry ID (die Verknüpfung zur Instanz der Integration)
        entry_id = entry_data.config_entry_id
        
        # 3. Den Coordinator aus den HA-Daten fischen
        coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN].get(entry_id)

        if not coordinator:
            _LOGGER.error("No coordinator found for entity %s (Entry ID: %s)", entity_id, entry_id)
            return

        # --- AB HIER FOLGT DEINE BESTEHENDE LOGIK ---
        now = dt_util.now()
        # Kombiniere heutiges Datum mit der Ziel-Uhrzeit
        # target_datetime = datetime.combine(now.date(), target_time_only, now.tzinfo)
        target_datetime = datetime.combine(now.date(), target_time_only).replace(tzinfo=now.tzinfo)

        # Falls Uhrzeit bereits vorbei ist, plane es für morgen ein
        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        time_until = (target_datetime - now).total_seconds() / 60
        preheat_minutes = coordinator._calculate_preheat_minutes()
        
        # --- NEU: Startzeit berechnen und im Coordinator speichern ---
        preheat_start = target_datetime - timedelta(minutes=preheat_minutes)
        coordinator.data.next_preheat_start = preheat_start
        # --------------------------------------------------------------

        if preheat_minutes >= time_until:
            # Wenn es sofort losgeht, können wir den Planer-Eintrag wieder leeren
            coordinator.data.next_preheat_start = None
            
            await coordinator.async_set_desired_temperature(target_temperature)
            _LOGGER.info(
                "Started pre-heat for %s to reach %.1f°C by %s",
                coordinator.room_name,
                target_temperature,
                target_time_only,
            )
        else:
            _LOGGER.info(
                "Pre-heat for %s scheduled: Start at %s (in %.0f minutes)",
                coordinator.room_name,
                preheat_start.strftime("%H:%M:%S"),
                time_until - preheat_minutes,
            )

        # Den Coordinator zwingen, die Sensoren in der UI sofort zu aktualisieren
        await coordinator.async_request_refresh()

    # Register services
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_COMPENSATION, handle_force_compensation, schema=SERVICE_FORCE_COMPENSATION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_LEARNING, handle_reset_learning, schema=SERVICE_RESET_LEARNING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PREHEAT, handle_set_preheat, schema=SERVICE_SET_PREHEAT_SCHEMA
    )