"""Config flow for Tado Local Offset integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
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

    def __init__(self) -> None:
        """Initialize flow."""
        self.init_info: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Erster Schritt: Grundkonfiguration und automatische Entitätssuche."""
        errors = {}

        if user_input is not None:
            device_id = user_input[CONF_TADO_DEVICE]
            ent_reg = er.async_get(self.hass)
            
            # Alle Entitäten des gewählten Tado-Geräts finden
            entities = er.async_entries_for_device(ent_reg, device_id)
            
            tado_climate = next((e.entity_id for e in entities if e.domain == "climate"), None)
            tado_temp = next((e.entity_id for e in entities if e.domain == "sensor" and e.capabilities.get("device_class") == "temperature"), None)
            tado_humi = next((e.entity_id for e in entities if e.domain == "sensor" and e.capabilities.get("device_class") == "humidity"), None)

            if not tado_climate:
                errors["base"] = "no_climate_entity"
            else:
                user_input[CONF_TADO_CLIMATE_ENTITY] = tado_climate
                user_input[CONF_TADO_TEMP_SENSOR] = tado_temp
                user_input[CONF_TADO_HUMIDITY_SENSOR] = tado_humi
                
                self.init_info = user_input
                return await self.async_step_window_detection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_TADO_DEVICE): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(manufacturer="tado")
                ),
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }),
            errors=errors,
        )

    async def async_step_window_detection(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Zweiter Schritt: Fenster-Einstellungen."""
        if user_input is not None:
            self.init_info.update(user_input)
            return await self.async_step_advanced_settings()

        return self.async_show_form(
            step_id="window_detection",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=False): bool,
                vol.Optional(
                    CONF_WINDOW_SENSOR, 
                    default=[] # Wichtig: Default ist jetzt eine Liste
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", 
                        device_class=["window", "door"], # Erlaubt Fenster UND Türen
                        multiple=True # Erlaubt die Auswahl mehrerer Sensoren
                    )
                ),
                vol.Optional(CONF_ENABLE_TEMP_DROP_DETECTION, default=False): bool,
                vol.Optional(CONF_TEMP_DROP_THRESHOLD, default=DEFAULT_TEMP_DROP_THRESHOLD): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=3.0)
                ),
            })
        )

    async def async_step_advanced_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Dritter Schritt: Pre-heat und Batterie-Einstellungen."""
        if user_input is not None:
            self.init_info.update(user_input)
            return self.async_create_entry(
                title=self.init_info[CONF_ROOM_NAME],
                data=self.init_info
            )

        return self.async_show_form(
            step_id="advanced_settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_BATTERY_SAVER, default=True): bool,
                vol.Optional(CONF_TOLERANCE, default=DEFAULT_TOLERANCE): vol.All(
                    vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)
                ),
                vol.Optional(CONF_BACKOFF_MINUTES, default=DEFAULT_BACKOFF_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)
                ),
                vol.Optional(CONF_ENABLE_PREHEAT, default=False): bool,
                vol.Optional(CONF_LEARNING_BUFFER, default=DEFAULT_LEARNING_BUFFER): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=50)
                ),
                vol.Optional(CONF_MIN_PREHEAT_MINUTES, default=DEFAULT_MIN_PREHEAT_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
                vol.Optional(CONF_MAX_PREHEAT_MINUTES, default=DEFAULT_MAX_PREHEAT_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=60, max=240)
                ),
            })
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return TadoLocalOffsetOptionsFlowHandler(config_entry)


class TadoLocalOffsetOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for changing settings after creation."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def get_val(key, default):
            return self.config_entry.options.get(key, self.config_entry.data.get(key, default))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_TOLERANCE, default=get_val(CONF_TOLERANCE, DEFAULT_TOLERANCE)): vol.All(
                    vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)
                ),
                vol.Optional(CONF_BACKOFF_MINUTES, default=get_val(CONF_BACKOFF_MINUTES, DEFAULT_BACKOFF_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)
                ),
                vol.Optional(CONF_ENABLE_BATTERY_SAVER, default=get_val(CONF_ENABLE_BATTERY_SAVER, True)): bool,
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=get_val(CONF_ENABLE_WINDOW_DETECTION, False)): bool,
                # KORREKTUR HIER: Nur eine Klammer nach dem default, dann der Doppelpunkt
                vol.Optional(CONF_WINDOW_SENSOR, default=get_val(CONF_WINDOW_SENSOR, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", 
                        device_class=["window", "door"], 
                        multiple=True
                    )
                ),
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
                    vol.Coerce(int), vol.Range(min=60, max=240)
                ),
            }),
        )