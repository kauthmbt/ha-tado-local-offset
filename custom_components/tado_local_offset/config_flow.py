"""Config flow for Tado Local Offset integration."""
from __future__ import annotations
import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_BACKOFF_MINUTES, CONF_ENABLE_BATTERY_SAVER, CONF_ENABLE_PREHEAT,
    CONF_ENABLE_TEMP_DROP_DETECTION, CONF_ENABLE_WINDOW_DETECTION,
    CONF_EXTERNAL_TEMP_SENSOR, CONF_LEARNING_BUFFER, CONF_MAX_PREHEAT_MINUTES,
    CONF_MIN_PREHEAT_MINUTES, CONF_ROOM_NAME, CONF_TADO_CLIMATE_ENTITY,
    CONF_TADO_DEVICE, CONF_TADO_HUMIDITY_SENSOR, CONF_TADO_TEMP_SENSOR,
    CONF_TEMP_DROP_THRESHOLD, CONF_TOLERANCE, CONF_WINDOW_SENSOR,
    DEFAULT_BACKOFF_MINUTES, DEFAULT_LEARNING_BUFFER, DEFAULT_MAX_PREHEAT_MINUTES,
    DEFAULT_MIN_PREHEAT_MINUTES, DEFAULT_TEMP_DROP_THRESHOLD, DEFAULT_TOLERANCE,
    DOMAIN, MAX_BACKOFF, MAX_TOLERANCE, MIN_BACKOFF, MIN_TOLERANCE, CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY
    
)

_LOGGER = logging.getLogger(__name__)

class TadoLocalOffsetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tado Local Offset."""
    VERSION = 1

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Erster Schritt: Raum und Basis-Geräte."""
        if user_input is not None:
            self.data.update(user_input)
            
            # Unique ID setzen, damit HA die Instanz erkennt
            unique_id = f"tado_local_offset_{user_input[CONF_ROOM_NAME].lower().replace(' ', '_')}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_TADO_DEVICE): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(
                        integration="homekit_controller",
                        manufacturer="tado",
                    )
                ),
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }),
        )

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Zweiter Schritt: Bestätigung der Tado-Entitäten (Fix für null-Sensoren)."""
        if user_input is not None:
            self.data.update(user_input)
            return self.async_create_entry(
                title=self.data[CONF_ROOM_NAME],
                data=self.data,
                options={
                    CONF_TOLERANCE: DEFAULT_TOLERANCE,
                    CONF_BACKOFF_MINUTES: DEFAULT_BACKOFF_MINUTES,
                    CONF_ENABLE_BATTERY_SAVER: True,
                }
            )

        ent_reg = er.async_get(self.hass)
        device_id = self.data[CONF_TADO_DEVICE]
        entities = er.async_entries_for_device(ent_reg, device_id)
        
        tado_climate = next((e.entity_id for e in entities if e.domain == "climate"), None)
        tado_temp = next((e.entity_id for e in entities if e.domain == "sensor" and "temperature" in (e.device_class or "")), None)
        if not tado_temp:
             tado_temp = next((e.entity_id for e in entities if e.domain == "sensor" and "temperature" in e.entity_id), None)

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema({
                vol.Required(CONF_TADO_CLIMATE_ENTITY, default=tado_climate): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_TADO_TEMP_SENSOR, default=tado_temp): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_TADO_HUMIDITY_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                ),
            }),
        )
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> TadoLocalOffsetOptionsFlowHandler:
        return TadoLocalOffsetOptionsFlowHandler(config_entry)


class TadoLocalOffsetOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        return await self.async_step_general_settings()

    async def async_step_general_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """General compensation settings."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_window_detection()

        return self.async_show_form(
            step_id="general_settings",
            data_schema=vol.Schema({
                vol.Required(CONF_TOLERANCE, default=self.options.get(CONF_TOLERANCE, DEFAULT_TOLERANCE)): vol.All(
                    vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)
                ),
                vol.Required(CONF_BACKOFF_MINUTES, default=self.options.get(CONF_BACKOFF_MINUTES, DEFAULT_BACKOFF_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)
                ),
                vol.Required(CONF_ENABLE_BATTERY_SAVER, default=self.options.get(CONF_ENABLE_BATTERY_SAVER, True)): bool,
            }),
        )

    async def async_step_window_detection(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Window detection settings."""
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_advanced_settings()

        return self.async_show_form(
            step_id="window_detection",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=self.options.get(CONF_ENABLE_WINDOW_DETECTION, False)): bool,
                vol.Optional(CONF_WINDOW_SENSOR, default=self.options.get(CONF_WINDOW_SENSOR, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor", device_class=["window", "door"], multiple=True)
                ),
                # UI Option
                vol.Optional(
                    CONF_WINDOW_OPEN_DELAY, 
                    default=self.options.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=600)),
                vol.Optional(CONF_ENABLE_TEMP_DROP_DETECTION, default=self.options.get(CONF_ENABLE_TEMP_DROP_DETECTION, False)): bool,
                vol.Optional(CONF_TEMP_DROP_THRESHOLD, default=self.options.get(CONF_TEMP_DROP_THRESHOLD, DEFAULT_TEMP_DROP_THRESHOLD)): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=3.0)
                ),
            }),
        )

    async def async_step_advanced_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Advanced and Preheat settings."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="advanced_settings",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_PREHEAT, default=self.options.get(CONF_ENABLE_PREHEAT, False)): bool,
                vol.Optional(CONF_LEARNING_BUFFER, default=self.options.get(CONF_LEARNING_BUFFER, DEFAULT_LEARNING_BUFFER)): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=50)
                ),
                vol.Optional(CONF_MIN_PREHEAT_MINUTES, default=self.options.get(CONF_MIN_PREHEAT_MINUTES, DEFAULT_MIN_PREHEAT_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
                vol.Optional(CONF_MAX_PREHEAT_MINUTES, default=self.options.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)): vol.All(
                    vol.Coerce(int), vol.Range(min=30, max=240)
                ),
            }),
        )