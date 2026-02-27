"""Data update coordinator for Tado Local Offset."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field, KW_ONLY
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN, SERVICE_SET_TEMPERATURE
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
# ------------------------------------
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_OFFSET,
    ATTR_COMPENSATED_TARGET,
    ATTR_HEATING_RATE,
    ATTR_PREHEAT_MINUTES,
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
    CONF_TADO_HUMIDITY_SENSOR,
    CONF_TADO_TEMP_SENSOR,
    CONF_TEMP_DROP_THRESHOLD,
    CONF_TOLERANCE,
    CONF_WINDOW_SENSOR,
    DEFAULT_DESIRED_TEMP,
    DEFAULT_HEATING_RATE,
    DOMAIN,
    MAX_HEATING_CYCLES,
    MAX_HEATING_RATE,
    MAX_OFFSET,
    MAX_TEMP,
    MIN_HEATING_RATE,
    MIN_TEMP,
    TEMP_DROP_RATE_THRESHOLD,
    TEMP_DROP_WINDOW_MINUTES,
    UPDATE_INTERVAL,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_OPEN_DELAY,
)

STORAGE_KEY = f"{DOMAIN}_storage"
STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__) 
# ---------------------
@dataclass
#class HeatingCycle:
#    """Represents a single heating cycle for learning."""
#
#    start_time: datetime
#    end_time: datetime
#    start_temp: float
#    end_temp: float
#    duration_minutes: float
#    temp_rise: float
#    rate: float  # °C per minute

@dataclass
class TadoLocalOffsetData:
    """Data structure for coordinator."""

    external_temp: float | None = None
    tado_temp: float | None = None
    tado_target: float = DEFAULT_DESIRED_TEMP
    desired_temp: float = DEFAULT_DESIRED_TEMP
    offset: float = 0.0
    compensated_target: float = DEFAULT_DESIRED_TEMP
    hvac_mode: str = "off"
    hvac_action: str = "idle"
    window_open: bool = False
    heating_rate: float = DEFAULT_HEATING_RATE
    preheat_minutes: int = 0
    compensation_enabled: bool = True
    battery_saver_enabled: bool = True
    window_override: bool = False
    
    # This is a special marker for Python 3.13.
    _: KW_ONLY 
    
    last_update: datetime = field(default_factory=dt_util.utcnow)
    heating_history: list[Any] = field(default_factory=list)
    next_preheat_start: datetime | None = field(default=None)


class TadoLocalOffsetCoordinator(DataUpdateCoordinator[TadoLocalOffsetData]):
    """Class to manage fetching Tado Local Offset data."""

    def __init__(self, hass: HomeAssistant, entry: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_ROOM_NAME]}",
            update_interval=UPDATE_INTERVAL,
        )

        self.entry = entry
        self.room_name = entry.data[CONF_ROOM_NAME]

        def get_conf(key, default=None):
            return entry.options.get(key, entry.data.get(key, default))
            
        self.tado_climate_entity = get_conf(CONF_TADO_CLIMATE_ENTITY)
        self.tado_temp_sensor = get_conf(CONF_TADO_TEMP_SENSOR)
        self.tado_humidity_sensor = get_conf(CONF_TADO_HUMIDITY_SENSOR)
        self.external_temp_sensor = get_conf(CONF_EXTERNAL_TEMP_SENSOR)

        if not self.tado_climate_entity or not self.external_temp_sensor:
            _LOGGER.warning(
                "Configuration for room ‘%s’ incomplete or sensors not yet ready. Setup will continue.", 
                self.room_name
            )

        
        # Configuration - First check Options (UI change), then Data (initial setup), then Default
        self.tolerance = entry.options.get(CONF_TOLERANCE, entry.data.get(CONF_TOLERANCE, 0.3))
        self.backoff_minutes = entry.options.get(CONF_BACKOFF_MINUTES, entry.data.get(CONF_BACKOFF_MINUTES, 15))
        self.learning_buffer = entry.options.get(CONF_LEARNING_BUFFER, entry.data.get(CONF_LEARNING_BUFFER, 10))
        self.min_preheat_minutes = entry.options.get(CONF_MIN_PREHEAT_MINUTES, entry.data.get(CONF_MIN_PREHEAT_MINUTES, 15))
        self.max_preheat_minutes = entry.options.get(CONF_MAX_PREHEAT_MINUTES, entry.data.get(CONF_MAX_PREHEAT_MINUTES, 120))
        
        # Boolean Values 
        self.enable_temp_drop_detection = entry.options.get(CONF_ENABLE_TEMP_DROP_DETECTION, entry.data.get(CONF_ENABLE_TEMP_DROP_DETECTION, False))
        self.enable_preheat = entry.options.get(CONF_ENABLE_PREHEAT, entry.data.get(CONF_ENABLE_PREHEAT, False))

        # Internal state
        self._last_compensation_time: datetime | None = None
        self._last_sent_compensated_target: float | None = None
        self._heating_start_time: datetime | None = None
        self._heating_start_temp: float | None = None
        self._heating_external_start_temp: float | None = None 
        self._temp_history: list[tuple[datetime, float]] = []
        self._is_heating = False 

        # Cooldown after compensation to let HomeKit state propagate (seconds)
        self._external_change_cooldown: float = 90.0

        # Initialize data
        self.data = TadoLocalOffsetData()

        # --- Window-Sensor ---
        conf_window = entry.options.get(
            CONF_WINDOW_SENSOR, 
            entry.data.get(CONF_WINDOW_SENSOR, [])
        )
        
        if conf_window is None:
            self.window_sensor = []
        elif isinstance(conf_window, str):
            self.window_sensor = [conf_window]
        else:
            self.window_sensor = conf_window
        
        if isinstance(self.window_sensor, str):
            if self.window_sensor == "":
                self.window_sensor = []
            else:
                self.window_sensor = [self.window_sensor]

        self.enable_window_detection = entry.options.get(
            CONF_ENABLE_WINDOW_DETECTION,
            entry.data.get(CONF_ENABLE_WINDOW_DETECTION, False)
        )
        self.enable_temp_drop_detection = entry.options.get(
            CONF_ENABLE_TEMP_DROP_DETECTION,
            entry.data.get(CONF_ENABLE_TEMP_DROP_DETECTION, False)
        )
        
    async def _async_update_data(self) -> TadoLocalOffsetData:
        """Fetch data from sensors and calculate compensation."""
        try:
            if not self.external_temp_sensor or not self.tado_temp_sensor or not self.tado_climate_entity:
                _LOGGER.debug("Sensors for %s not yet fully initialized", self.room_name)
                return self.data
                
            # Get current sensor states
            external_temp_state = self.hass.states.get(self.external_temp_sensor)
            tado_temp_state = self.hass.states.get(self.tado_temp_sensor)
            tado_climate_state = self.hass.states.get(self.tado_climate_entity)

            # Validate states
            if not external_temp_state or not tado_temp_state or not tado_climate_state:
                _LOGGER.warning("[%s] Setup pending: Sensors not yet found in HA (External: %s, Tado: %s)", 
                                self.room_name, self.external_temp_sensor, self.tado_temp_sensor)
                return self.data

            if (tado_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or 
                external_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or
                tado_climate_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
                
                _LOGGER.debug("One of the sensors is not yet providing any values (status: unknown/unavailable).")
                return self.data

            # Parse temperatures
            try:
                external_temp = float(external_temp_state.state)
                tado_temp = float(tado_temp_state.state)
                
                if tado_temp < 5.0 or external_temp < 5.0:
                    _LOGGER.warning("Received implausible values for %s (Tado: %.1f, External: %.1f)", 
                                    self.room_name, tado_temp, external_temp)
                    return self.data

                self.data.external_temp = external_temp
                self.data.tado_temp = tado_temp
                _LOGGER.info("[%s] Temperatures updated for Tado %s (Extern %s)", 
                             self.room_name, tado_temp, external_temp)
                    
            except (ValueError, TypeError) as err:
                _LOGGER.error("Error parsing temperature for %s: %s", self.room_name, err)
                return self.data

            # Update data
            self.data.external_temp = external_temp
            self.data.tado_temp = tado_temp
            self.data.tado_target = float(tado_climate_state.attributes.get("temperature", DEFAULT_DESIRED_TEMP))
            raw_state = str(tado_climate_state.state).lower()
            
            if raw_state == "off":
                self.data.hvac_mode = "off"
            else:
                self.data.hvac_mode = "heat"
            self.data.hvac_action = tado_climate_state.attributes.get("hvac_action", "idle")
            self.data.last_update = dt_util.utcnow()
            # --- NEW: Live-Learning ---
            current_hvac = self.data.hvac_action
            if current_hvac == "heating":
                if self._heating_start_time is None:
                    self._heating_start_time = dt_util.utcnow()
                    self._heating_start_temp = self.data.external_temp 
                    _LOGGER.info("Heating cycle learning started at %.2f°C (External)", self.data.external_temp)
                else:
                    # We only call the function. 
                    # It takes care of the list, the average, and saving internally.
                    self._calculate_instant_heating_rate(self.data.external_temp)
            else:
                if self._heating_start_time is not None:
                    _LOGGER.info("[%s] Heating cycle completed. Data has been processed.", self.room_name)
                self._heating_start_time = None
                self._heating_start_temp = None
            # --- END NEW ---
            # Calculate offset
            self.data.offset = external_temp - tado_temp

            # Detect external target temperature changes (schedules, manual, app)
            # and sync back to desired_temp before compensation runs
            external_change = self._detect_external_target_change()

            # Update temperature history for drop detection
            self._update_temp_history(external_temp)

            # Check window status
            self.data.window_open = self._check_window_open()

            # Track heating cycles for learning
            # self._track_heating_cycle()

            # Calculate pre-heat time if enabled
            if self.enable_preheat:
                self.data.preheat_minutes = self._calculate_preheat_minutes()

            # If an external change was detected, re-apply compensation
            # so the offset adjustment targets the new desired temperature
            if external_change:
                await self.async_calculate_and_apply_compensation()

            return self.data

        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error updating Tado Local Offset data: {err}") from err

    def _detect_external_target_change(self) -> bool:
        """Erkennt Änderungen am Tado-Thermostat (App, Zeitplan, Drehrad)."""
        tado_target = self.data.tado_target

        # Check cooling time after making your own changes
        if self._last_compensation_time:
            elapsed = (dt_util.utcnow() - self._last_compensation_time).total_seconds()
            if elapsed < self._external_change_cooldown:
                return False

        # Initial synchronization at startup
        if self._last_sent_compensated_target is None:
            if abs(self.data.desired_temp - tado_target) > 0.1:
                self.data.desired_temp = round(tado_target - self.data.offset, 1)
            return False

        # Detection of an external change (threshold value 0.4°C)
        if abs(tado_target - self._last_sent_compensated_target) > 0.4:
            # IMPORTANT: Subtract the offset to obtain the true new target value.
            new_desired = round(tado_target - self.data.offset, 1)
            
            _LOGGER.info(
                "External change for %s: Tado target=%.1f°C -> New target: %.1f°C",
                self.room_name, tado_target, new_desired
            )
            
            self.data.desired_temp = new_desired
            self._last_sent_compensated_target = None 
            return True

        return False

    def _update_temp_history(self, current_temp: float) -> None:
        """Update temperature history for drop detection."""
        now = dt_util.utcnow()
        self._temp_history.append((now, current_temp))

        # Remove old entries (older than drop window)
        cutoff_time = now - timedelta(minutes=TEMP_DROP_WINDOW_MINUTES)
        self._temp_history = [
            (time, temp) for time, temp in self._temp_history
            if time > cutoff_time
        ]

    def _check_window_open(self) -> bool:
        """Check if any window is open via sensors or temperature drop."""
        # 1. Check physical sensors
        if self.enable_window_detection and self.window_sensor:
            sensors = self.window_sensor
            if isinstance(sensors, str):
                sensors = [sensors]
            
            from .const import CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY
            
            # Get value from options or use default
            open_delay = self.config_entry.options.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)
            
            now = dt_util.utcnow()

            for sensor_id in sensors:
                window_state = self.hass.states.get(sensor_id)
                if window_state and window_state.state == STATE_ON:
                    open_duration = (now - window_state.last_changed).total_seconds()
                    
                    if open_duration >= open_delay:
                        _LOGGER.debug("[%s] Window open detected (duration: %.0fs): %s", 
                                     self.room_name, open_duration, sensor_id)
                        return True
                    else:
                        _LOGGER.debug("[%s] Window open but waiting for delay (%.0fs/%.0fs)", 
                                     self.room_name, open_duration, float(open_delay))

        # 2. Temperature drop detection
        if self.enable_temp_drop_detection:
            # Wenn der Sturz erkannt wurde, geben wir True zurück
            if self._detect_temperature_drop():
                _LOGGER.debug("Window open detected by drop in temperature")
                return True

        return False

    def _detect_temperature_drop(self) -> bool:
        """Detect window opening via sudden temperature drop."""
        if len(self._temp_history) < 2:
            return False

        # Only detect when heating
        if self.data.hvac_action != "heating":
            return False

        # Get oldest temperature in window
        oldest_temp = self._temp_history[0][1]
        current_temp = self.data.external_temp

        # Calculate drop
        temp_drop = oldest_temp - current_temp

        # Calculate drop rate (°C per minute)
        time_diff_minutes = TEMP_DROP_WINDOW_MINUTES
        drop_rate = temp_drop / time_diff_minutes if time_diff_minutes > 0 else 0

        # Trigger conditions
        return (
            temp_drop > self.temp_drop_threshold and
            drop_rate > TEMP_DROP_RATE_THRESHOLD
        )


    def _calculate_preheat_minutes(self) -> int:
        """Calculate minutes needed to reach desired temperature."""
        if self.data.desired_temp <= self.data.external_temp:
            return 0

        if self.data.heating_rate <= 0:
            return 45  # Conservative default

        temp_rise_needed = self.data.desired_temp - self.data.external_temp
        minutes_needed = temp_rise_needed / self.data.heating_rate

        # Add safety buffer
        buffered = minutes_needed * (1 + self.learning_buffer / 100)

        # Clamp to configured range
        return int(max(self.min_preheat_minutes, min(self.max_preheat_minutes, buffered)))

    async def async_set_desired_temperature(self, temperature: float) -> None:
        """Set desired temperature and trigger compensation immediately."""
        self.data.desired_temp = max(MIN_TEMP, min(MAX_TEMP, temperature))
        # Sofortige Kompensation erzwingen
        await self.async_calculate_and_apply_compensation(force=True)

    async def async_calculate_and_apply_compensation(self, force: bool = False) -> None:
        """Berechnet die Temperaturkorrektur und sendet sie gerundet an Tado."""
        now = dt_util.utcnow()

        # 1. Preliminary check: Should anything be sent at all?
        if not force:
            if not self.data.compensation_enabled:
                return

            if self.data.window_open and not self.data.window_override:
                _LOGGER.debug("Compensation skipped: Window/door is open")
                return

            if self.data.battery_saver_enabled and self._last_compensation_time:
                if now < self._last_compensation_time + timedelta(minutes=self.backoff_minutes):
                    _LOGGER.debug("Battery Saver: Waiting period not yet expired")
                    return

        # 2. Calculate target value with “hard braking”
        if self.data.external_temp >= self.data.desired_temp:
            compensated_target = float(self.data.desired_temp)
            _LOGGER.debug("%s: Target reached (%.1f >= %.1f). Fix at %.1f", 
                         self.room_name, self.data.external_temp, self.data.desired_temp, compensated_target)
            
            force_send_due_to_target_reached = True
        else:
            raw_target = self.data.desired_temp + self.data.offset
            compensated_target = round(raw_target * 2) / 2
            force_send_due_to_target_reached = False

        compensated_target = max(5.0, min(25.0, compensated_target))

        # 2. Tolerance check
        current_tado_target = self.data.tado_target
        diff = abs(compensated_target - current_tado_target)

        if not force and not force_send_due_to_target_reached and diff < self.tolerance:
            _LOGGER.debug("Change too small (%.2f < %.2f), no update necessary", diff, self.tolerance)
            return

        # 4. The actual command to the thermostat
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self.tado_climate_entity,
                    "temperature": compensated_target,
                },
                blocking=False, # CHANGED to False
            )
            self._last_sent_compensated_target = compensated_target
            self._last_compensation_time = now
            self.data.compensated_target = compensated_target
        except Exception as err:
            _LOGGER.error("Error sending to Tado (%s): %s", self.room_name, err)
            
    def _should_compensate(self) -> bool:
        """Determine if compensation should be applied."""
        # Compensation disabled?
        if not self.data.compensation_enabled:
            return False

        # Window open (and not overridden)?
        if self.data.window_open and not self.data.window_override:
            return False

        # Tolerance check - don't compensate if offset is small
        if abs(self.data.offset) <= self.tolerance:
            return False

        # Battery saver checks
        if self.data.battery_saver_enabled:
            # Backoff timer
            if self._last_compensation_time:
                time_since_last = (dt_util.utcnow() - self._last_compensation_time).total_seconds()
                if time_since_last < self.backoff_minutes * 60:
                    return False

            # HVAC action awareness - don't interrupt active heating/cooling
            compensated = self.data.desired_temp + self.data.offset

            if self.data.hvac_action == "heating" and compensated <= self.data.tado_target:
                # Already heating to higher temp, don't lower it
                return False

            if self.data.hvac_action == "idle" and compensated >= self.data.tado_target:
                # Already idle with lower target, no need to raise
                return False

        return True

    async def async_force_compensation(self) -> None:
        """Force compensation, bypassing all checks except window."""
        # Still respect window detection unless overridden
        if self.data.window_open and not self.data.window_override:
            self.logger.info("[%s] Cannot force compensation: window is open", self.room_name)
            return

        await self.async_calculate_and_apply_compensation(force=True)

    async def async_reset_learning(self) -> None:
        """Reset heating cycle history and learning data."""
        self.data.heating_history.clear()
        self.data.heating_rate = DEFAULT_HEATING_RATE
        self._heating_start_time = None
        self._heating_start_temp = None
        self.logger.info("Reset learning data for %s", self.room_name)

    def set_compensation_enabled(self, enabled: bool) -> None:
        """Enable or disable compensation."""
        self.data.compensation_enabled = enabled

    def set_battery_saver(self, enabled: bool) -> None:
        """Enable or disable battery saver mode."""
        self.data.battery_saver_enabled = enabled

    def set_window_override(self, override: bool) -> None:
        """Set window detection override."""
        self.data.window_override = override

    def _calculate_instant_heating_rate(self, current_external_temp: float) -> float | None:
        """Berechnet die Heizrate basierend auf dem externen Sensor (immun gegen Offset-Sprünge)."""
        if self._heating_start_time is None or self._heating_start_temp is None:
            return None

        # --- NEW: Lockout period after window closure (calming phase)  ---
        now = dt_util.utcnow()
        if self.window_sensor:
            for sensor_id in self.window_sensor:
                state = self.hass.states.get(sensor_id)
                if state and state.state == "off":
                    # Check how long the window has been closed
                    time_since_close = (now - state.last_changed).total_seconds() / 60
                    if time_since_close < 15:
                        _LOGGER.debug(
                            "%s: Learning paused (window closed less than %.0f min ago)", 
                            self.room_name, time_since_close
                        )
                        return None
        # --- End of new logic ---
        duration_hrs = (now - self._heating_start_time).total_seconds() / 3600
        
        # IMPORTANT: temp_diff is based on the external sensor value here. 
        temp_diff = current_external_temp - self._heating_start_temp

        # Filter for stable learning: 
        # Min. 6 min runtime (0.1h) and 0.1°C increase at the EXTERNAL sensor.
        if duration_hrs < 0.1 or temp_diff < 0.1:
            _LOGGER.debug("%s: Cycle too short or delta too small for learning (%.2fh, %.2f°C)", 
                         self.room_name, duration_hrs, temp_diff)
            return None

        instant_rate = temp_diff / duration_hrs
        
        self.data.heating_history.append(instant_rate)
        
        from .const import MAX_HEATING_CYCLES, MIN_HEATING_RATE, MAX_HEATING_RATE
        if len(self.data.heating_history) > MAX_HEATING_CYCLES:
            self.data.heating_history.pop(0)

        self.data.heating_rate = sum(self.data.heating_history) / len(self.data.heating_history)

        self.hass.async_create_task(self._async_save_data())

        if MIN_HEATING_RATE <= instant_rate <= MAX_HEATING_RATE:
            return instant_rate
            
        return None

    async def async_load_data(self) -> None:
        """Lädt die historische Heizrate beim Start aus dem JSON-Speicher."""
        stored_data = await self._store.async_load()
        if stored_data and "history" in stored_data:
            self.data.heating_history = stored_data["history"]
            # --- NEW: Calculate the average immediately upon loading ---
            if self.data.heating_history:
                self.data.heating_rate = sum(self.data.heating_history) / len(self.data.heating_history)
                
            _LOGGER.info(
                "Historical heating data for %s loaded. Current rate: %.4f °C/h", 
                self.room_name, self.data.heating_rate
            )


    async def _async_save_data(self) -> None:
        """Speichert die aktuelle Historie dauerhaft in eine JSON-Datei."""
        await self._store.async_save({"history": self.data.heating_history})
    