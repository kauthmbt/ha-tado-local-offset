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
        coordinators = hass.data[DOMAIN].values()

        if entity_ids:
            coordinators = [
                coord for coord in coordinators
                if f"climate.{coord.room_name.lower().replace(' ', '_')}_virtual" in entity_ids
            ]

        for coordinator in coordinators:
            await coordinator.async_force_compensation()
            await coordinator.async_request_refresh()

    async def handle_reset_learning(call: ServiceCall) -> None:
        """Handle reset learning service call."""
        entity_ids = call.data.get(ATTR_ENTITY_ID)
        coordinators = hass.data[DOMAIN].values()

        if entity_ids:
            coordinators = [
                coord for coord in coordinators
                if f"climate.{coord.room_name.lower().replace(' ', '_')}_virtual" in entity_ids
            ]

        for coordinator in coordinators:
            await coordinator.async_reset_learning()
            await coordinator.async_request_refresh()

    async def handle_set_preheat(call: ServiceCall) -> None:
        """Handle set preheat service call."""
        entity_id = call.data[ATTR_ENTITY_ID]
        target_time_only = call.data[ATTR_TARGET_TIME]
        target_temperature = call.data[ATTR_TARGET_TEMPERATURE]

        # Find coordinator for this entity
        coordinators = hass.data[DOMAIN].values()
        coordinator = next(
            (c for c in coordinators if f"climate.{c.room_name.lower().replace(' ', '_')}_virtual" == entity_id),
            None
        )

        if not coordinator:
            _LOGGER.error("No coordinator found for entity %s", entity_id)
            return

        # Logik für reine Uhrzeit: Berechne Zieldatum (heute oder morgen)
        now = dt_util.now()
        target_datetime = datetime.combine(now.date(), target_time_only)
        target_datetime = dt_util.as_local(target_datetime)

        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        # Umrechnung in Minuten bis zum Ziel
        time_until = (target_datetime - now).total_seconds() / 60

        # Calculate pre-heat start time basierend auf gelernter Heizrate
        preheat_minutes = coordinator._calculate_preheat_minutes()

        if preheat_minutes >= time_until:
            # Start sofort
            await coordinator.async_set_desired_temperature(target_temperature)
            _LOGGER.info(
                "Started pre-heat for %s to reach %.1f°C by %s (Uhrzeit erkannt als %s)",
                coordinator.room_name,
                target_temperature,
                target_time_only,
                target_datetime,
            )
        else:
            _LOGGER.info(
                "Pre-heat for %s will start in %.0f minutes (%.0f minutes before target %s)",
                coordinator.room_name,
                time_until - preheat_minutes,
                preheat_minutes,
                target_time_only,
            )

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