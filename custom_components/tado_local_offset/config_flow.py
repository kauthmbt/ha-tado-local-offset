"""Config flow for Tado Local Offset integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_BACKOFF_MINUTES,
    CONF_ENABLE_BATTERY_SAVER,
    CONF_ENABLE_PREHEAT,
    CONF_ENABLE_TEMP_DROP_DETECTION,
    CONF_ENABLE_WINDOW_DETECTION,
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_LEARNING_BUFFER,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_MIN_PREHEAT_MINUTES,
    CONF_ROOM_NAME,
    CONF_TADO_CLIMATE_ENTITY,
    CONF_TADO_DEVICE,
    CONF_TADO_HUMIDITY_SENSOR,
    CONF_TADO_TEMP_SENSOR,
    CONF_TEMP_DROP_THRESHOLD,
    CONF_TOLERANCE,
    CONF_WINDOW_SENSOR,
    DEFAULT_BACKOFF_MINUTES,
    DEFAULT_LEARNING_BUFFER,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DEFAULT_MIN_PREHEAT_MINUTES,
    DEFAULT_TEMP_DROP_THRESHOLD,
    DEFAULT_TOLERANCE,
    DOMAIN,
    MAX_BACKOFF,
    MAX_TOLERANCE,
    MIN_BACKOFF,
    MIN_TOLERANCE,
)

_LOGGER = logging.getLogger(__name__)

class TadoLocalOffsetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tado Local Offset."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Discovery-Logik zur automatischen Identifizierung der Tado-Entitäten
            dr_reg = dr.async_get(self.hass)
            er_reg = er.async_get(self.hass)
            device = dr_reg.async_get(user_input[CONF_TADO_DEVICE])

            if device:
                entities = er.async_entries_for_device(er_reg, device.id)
                climate = next((e for e in entities if e.domain == "climate"), None)
                temp = next((e for e in entities if e.domain == "sensor" and e.original_device_class == "temperature"), None)
                
                if climate and temp:
                    user_input[CONF_TADO_CLIMATE_ENTITY] = climate.entity_id
                    user_input[CONF_TADO_TEMP_SENSOR] = temp.entity_id
                    
                    await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_ROOM_NAME].lower().replace(' ', '_')}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=user_input[CONF_ROOM_NAME], data=user_input)
                
                errors["base"] = "no_tado_entities"
            else:
                errors["base"] = "device_not_found"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_TADO_DEVICE): selector.DeviceSelector(),
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return TadoLocalOffsetOptionsFlow()


class TadoLocalOffsetOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Tado Local Offset."""
    # Keine __init__ Methode vorhanden -> Behebt AttributeError "no setter"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opt = self.config_entry.options
        dat = self.config_entry.data

        def get_val(key, default=None):
            return opt.get(key, dat.get(key, default))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR, default=get_val(CONF_EXTERNAL_TEMP_SENSOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(
                    CONF_WINDOW_SENSOR, 
                    default=get_val(CONF_WINDOW_SENSOR)
                ): vol.Maybe(
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")
                    )
                ),
                vol.Optional(CONF_ENABLE_BATTERY_SAVER, default=get_val(CONF_ENABLE_BATTERY_SAVER, True)): bool,
                vol.Optional(CONF_TOLERANCE, default=get_val(CONF_TOLERANCE, DEFAULT_TOLERANCE)): vol.All(
                    vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)
                ),
                vol.Optional(CONF_BACKOFF_MINUTES, default=get_val(CONF_BACKOFF_MINUTES, DEFAULT_BACKOFF_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)
                ),
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=get_val(CONF_ENABLE_WINDOW_DETECTION, False)): bool,
                vol.Optional(CONF_ENABLE_TEMP_DROP_DETECTION, default=get_val(CONF_ENABLE_TEMP_DROP_DETECTION, False)): bool,
                vol.Optional(CONF_TEMP_DROP_THRESHOLD, default=get_val(CONF_TEMP_DROP_THRESHOLD, DEFAULT_TEMP_DROP_THRESHOLD)): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=3.0)
                ),
                vol.Optional(CONF_ENABLE_PREHEAT, default=get_val(CONF_ENABLE_PREHEAT, False)): bool,
                vol.Optional(CONF_LEARNING_BUFFER, default=get_val(CONF_LEARNING_BUFFER, DEFAULT_LEARNING_BUFFER)): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=50)
                ),
                vol.Optional(CONF_MIN_PREHEAT_MINUTES, default=get_val(CONF_MIN_PREHEAT_MINUTES, DEFAULT_MIN_PREHEAT_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
                vol.Optional(CONF_MAX_PREHEAT_MINUTES, default=get_val(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=30, max=240)
                ),
            }),
        )