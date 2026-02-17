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

    def __init__(self) -> None:
        """Initialize config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step - room name and device selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data[CONF_ROOM_NAME] = user_input[CONF_ROOM_NAME]
            self._data[CONF_TADO_DEVICE] = user_input[CONF_TADO_DEVICE]
            self._data[CONF_EXTERNAL_TEMP_SENSOR] = user_input[CONF_EXTERNAL_TEMP_SENSOR]

            # Discovery Logik für Tado-Entitäten
            device_registry = dr.async_get(self.hass)
            entity_registry = er.async_get(self.hass)
            device = device_registry.async_get(user_input[CONF_TADO_DEVICE])

            if not device:
                errors["base"] = "device_not_found"
            else:
                entities = er.async_entries_for_device(entity_registry, device.id)
                climate_entity = next((e for e in entities if e.domain == "climate"), None)
                temp_sensor = next((e for e in entities if e.domain == "sensor" and e.original_device_class == "temperature"), None)
                humidity_sensor = next((e for e in entities if e.domain == "sensor" and e.original_device_class == "humidity"), None)

                if not climate_entity:
                    errors["base"] = "no_climate_entity"
                elif not temp_sensor:
                    errors["base"] = "no_temp_sensor"
                else:
                    self._data[CONF_TADO_CLIMATE_ENTITY] = climate_entity.entity_id
                    self._data[CONF_TADO_TEMP_SENSOR] = temp_sensor.entity_id
                    if humidity_sensor:
                        self._data[CONF_TADO_HUMIDITY_SENSOR] = humidity_sensor.entity_id

                    await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_ROOM_NAME].lower().replace(' ', '_')}")
                    self._abort_if_unique_id_configured()
                    return await self.async_step_window_detection()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_TADO_DEVICE): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration="homekit_controller", manufacturer="tado")
                ),
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
            }),
            errors=errors,
        )

    async def async_step_window_detection(self, user_input=None):
        """Step for window detection settings."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery_saver()
        return self.async_show_form(
            step_id="window_detection",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=False): bool,
                vol.Optional(CONF_WINDOW_SENSOR, default=get_val(CONF_WINDOW_SENSOR,"")): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")),
                vol.Optional(CONF_ENABLE_TEMP_DROP_DETECTION, default=False): bool,
                vol.Optional(CONF_TEMP_DROP_THRESHOLD, default=DEFAULT_TEMP_DROP_THRESHOLD): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=3.0)),
            }),
        )

    async def async_step_battery_saver(self, user_input=None):
        """Step for battery saver settings."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_preheat()
        return self.async_show_form(
            step_id="battery_saver",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_BATTERY_SAVER, default=True): bool,
                vol.Optional(CONF_TOLERANCE, default=DEFAULT_TOLERANCE): vol.All(vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)),
                vol.Optional(CONF_BACKOFF_MINUTES, default=DEFAULT_BACKOFF_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)),
            }),
        )

    async def async_step_preheat(self, user_input=None):
        """Step for pre-heat settings."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_ROOM_NAME], data=self._data)
        return self.async_show_form(
            step_id="preheat",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_PREHEAT, default=False): bool,
                vol.Optional(CONF_LEARNING_BUFFER, default=DEFAULT_LEARNING_BUFFER): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
                vol.Optional(CONF_MIN_PREHEAT_MINUTES, default=DEFAULT_MIN_PREHEAT_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
                vol.Optional(CONF_MAX_PREHEAT_MINUTES, default=DEFAULT_MAX_PREHEAT_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=30, max=240)),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get the options flow for this handler."""
        return TadoLocalOffsetOptionsFlow()


class TadoLocalOffsetOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Tado Local Offset."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Verwende self.config_entry (Property der Basisklasse)
        opt = self.config_entry.options
        dat = self.config_entry.data
        def g(k, d=None): return opt.get(k, dat.get(k, d))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_EXTERNAL_TEMP_SENSOR, default=g(CONF_EXTERNAL_TEMP_SENSOR)): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature")),
                vol.Optional(CONF_WINDOW_SENSOR, default=g(CONF_WINDOW_SENSOR)): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor", device_class="window")),
                vol.Optional(CONF_ENABLE_BATTERY_SAVER, default=g(CONF_ENABLE_BATTERY_SAVER, True)): bool,
                vol.Optional(CONF_TOLERANCE, default=g(CONF_TOLERANCE, DEFAULT_TOLERANCE)): vol.All(vol.Coerce(float), vol.Range(min=MIN_TOLERANCE, max=MAX_TOLERANCE)),
                vol.Optional(CONF_BACKOFF_MINUTES, default=g(CONF_BACKOFF_MINUTES, DEFAULT_BACKOFF_MINUTES)): vol.All(vol.Coerce(int), vol.Range(min=MIN_BACKOFF, max=MAX_BACKOFF)),
                vol.Optional(CONF_ENABLE_WINDOW_DETECTION, default=g(CONF_ENABLE_WINDOW_DETECTION, False)): bool,
                vol.Optional(CONF_ENABLE_TEMP_DROP_DETECTION, default=g(CONF_ENABLE_TEMP_DROP_DETECTION, False)): bool,
                vol.Optional(CONF_TEMP_DROP_THRESHOLD, default=g(CONF_TEMP_DROP_THRESHOLD, DEFAULT_TEMP_DROP_THRESHOLD)): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=3.0)),
                vol.Optional(CONF_ENABLE_PREHEAT, default=g(CONF_ENABLE_PREHEAT, False)): bool,
                vol.Optional(CONF_LEARNING_BUFFER, default=g(CONF_LEARNING_BUFFER, DEFAULT_LEARNING_BUFFER)): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
                vol.Optional(CONF_MIN_PREHEAT_MINUTES, default=g(CONF_MIN_PREHEAT_MINUTES, DEFAULT_MIN_PREHEAT_MINUTES)): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
                vol.Optional(CONF_MAX_PREHEAT_MINUTES, default=g(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)): vol.All(vol.Coerce(int), vol.Range(min=30, max=240)),
            }),
        )
