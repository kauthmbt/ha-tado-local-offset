"""Data update coordinator for Tado Local Offset."""
# pyright: reportMissingImports=false, reportMissingModuleSource=false
from __future__ import annotations
import logging
from dataclasses import dataclass, field, KW_ONLY
from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util
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
    
    # Combined preheat attributes (no duplicates)
    preheat_minutes: int = 0
    is_preheating: bool = False
    preheat_order_target: float | None = None
    last_learning_rate: float | None = None
    
    compensation_enabled: bool = True
    battery_saver_enabled: bool = True
    window_override: bool = False
    target_time: Any | None = None
    target_temperature: float = 0.0
    
    # This is a special marker for Python 3.13.
    _: KW_ONLY 
    
    last_update: datetime = field(default_factory=dt_util.utcnow)
    heating_history: list[Any] = field(default_factory=list)
    # Using datetime for the timestamp as it's more robust
    next_preheat_start: datetime | None = field(default=None)

class TadoLocalOffsetCoordinator(DataUpdateCoordinator[TadoLocalOffsetData]):
    """Class to manage fetching Tado Local Offset data."""

    def __init__(self, hass: HomeAssistant, entry: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self._last_reported_mins = -1 # Initial value that ensures that an update is performed the first time

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
        self.backoff_minutes = entry.options.get(CONF_BACKOFF_MINUTES, entry.data.get(CONF_BACKOFF_MINUTES, 15))
        self.min_preheat_minutes = entry.options.get(CONF_MIN_PREHEAT_MINUTES, entry.data.get(CONF_MIN_PREHEAT_MINUTES, 15))
        self.max_preheat_minutes = entry.options.get(CONF_MAX_PREHEAT_MINUTES, entry.data.get(CONF_MAX_PREHEAT_MINUTES, 120))
        
        # Boolean Values 
        self.enable_temp_drop_detection = entry.options.get(CONF_ENABLE_TEMP_DROP_DETECTION, entry.data.get(CONF_ENABLE_TEMP_DROP_DETECTION, False))
        self.enable_preheat = entry.options.get(CONF_ENABLE_PREHEAT, entry.data.get(CONF_ENABLE_PREHEAT, False))
        from .const import DEFAULT_TEMP_DROP_THRESHOLD, DEFAULT_TOLERANCE, DEFAULT_LEARNING_BUFFER
        
        self.temp_drop_threshold = entry.options.get(CONF_TEMP_DROP_THRESHOLD, entry.data.get(CONF_TEMP_DROP_THRESHOLD, DEFAULT_TEMP_DROP_THRESHOLD))
        self.tolerance = entry.options.get(CONF_TOLERANCE, entry.data.get(CONF_TOLERANCE, DEFAULT_TOLERANCE))
        self.learning_buffer = entry.options.get(CONF_LEARNING_BUFFER, entry.data.get(CONF_LEARNING_BUFFER, DEFAULT_LEARNING_BUFFER))
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
        
    async def _async_update_data(self) -> TadoLocalOffsetData:
        """Fetch data from sensors and calculate compensation."""
        try:
            if not self.data.heating_history:
                await self.async_load_data()
            if not self.external_temp_sensor or not self.tado_temp_sensor or not self.tado_climate_entity:
                _LOGGER.debug("Sensors for %s not yet fully initialized", self.room_name)
                return self.data
                
            # --- NEW: Remember current window state ---
            old_window_state = self.data.window_open
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
                _LOGGER.info("[%s] Temperatures updated for Tado %s (External %s)", 
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
            # --- Live-Learning ---
            current_hvac = self.data.hvac_action
            if current_hvac == "heating":
                if self._heating_start_time is None:
                    self._heating_start_time = dt_util.utcnow()
                    self._heating_start_temp = self.data.external_temp 
                    _LOGGER.info("[%s] Heating cycle learning started at %.2f°C (External)", self.room_name, self.data.external_temp)
                else:
                    # We only call the function. 
                    # It takes care of the list, the average, and saving internally.
                    self._calculate_instant_heating_rate(self.data.external_temp)
            else:
                if self._heating_start_time is not None:
                    _LOGGER.info("[%s] Heating cycle completed. Data has been processed.", self.room_name)
                self._heating_start_time = None
                self._heating_start_temp = None
            # Calculate offset
            self.data.offset = external_temp - tado_temp

            # Detect external target temperature changes (schedules, manual, app)
            # and sync back to desired_temp before compensation runs
            external_change = self._detect_external_target_change()

            # Update temperature history for drop detection
            self._update_temp_history(external_temp)

            # Check window status
            #self.data.window_open = self._check_window_open()
            # --- WINDOW LOGIC START ---
            old_window_state = self.data.window_open
            self.data.window_open = self._check_window_open()

            # ACTION 1: Window just OPENED -> Set Tado to 5.0°C (Frost Protection)
            if self.data.window_open and not old_window_state:
                _LOGGER.info("[%s] Window buffer expired. Setting Tado to 5.0°C frost protection.", self.room_name)
                await self.hass.services.async_call(
                    "climate", "set_temperature",
                    {"entity_id": self.tado_climate_entity, "temperature": 5.0},
                    blocking=False
                )
                return self.data # End cycle

            # ACTION 2: Window just CLOSED -> Restore heating immediately
            elif not self.data.window_open and old_window_state:
                _LOGGER.info("[%s] Window closed. Heating will be restored immediately.", self.room_name)
                await self.async_calculate_and_apply_compensation(force=True)
                return self.data # End cycle
            # --- WINDOW LOGIC END ---
            # Calculate pre-heat time and trigger if necessary
            if self.enable_preheat:
                now = dt_util.now()
                
                # 1. Fetch outside temperature (Your specific sensor)
                outside_temp = None
                outside_temp_state = self.hass.states.get("sensor.aussentemperatur_heizungskontrolle")
                
                if outside_temp_state and outside_temp_state.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
                    try:
                        outside_temp = float(outside_temp_state.state)
                    except ValueError:
                        _LOGGER.warning("[%s] Invalid outside temperature: %s", self.room_name, outside_temp_state.state)

                # 2. Proceed if target_time order exists
                if self.data.target_time is not None:
                    # FIX: Handle potential UTC/Local timestamp issues exactly as required
                    target_dt = datetime.combine(now.date(), self.data.target_time)
                    target_dt = dt_util.as_local(target_dt)
                    
                    # Calculate base preheat minutes using historical data
                    preheat_mins = self._calculate_preheat_minutes(
                        self.data.target_temperature if self.data.target_temperature > 0 else None
                    )
                

                    
                    # Calculate preheat minutes using the new unified function
                    preheat_mins = self._calculate_preheat_minutes(
                        self.data.target_temperature if self.data.target_temperature > 0 else None
                    )

                    self.data.preheat_minutes = preheat_mins
                    start_time = target_dt - timedelta(minutes=preheat_mins)
                    self.data.next_preheat_start = start_time
                    self.data.preheat_order_target = self.data.target_temperature # THIS ATRRIBUTE


                    # --- STATE DECISION (THE RESET FIX) ---

                    # CASE A: Target reached -> RESET ORDER (Prevents weekend/rollover issue)
                    if now >= target_dt:
                        _LOGGER.info("[%s] Pre-heat target reached. Resetting order to None.", self.room_name)
                        self.data.is_preheating = False
                        self.data.target_time = None  # The Fix: Clears the order
                        self.data.next_preheat_start = None
                        self.data.target_temperature = 0
                        self.data.preheat_order_target = None
                    
                    # CASE B: Within window -> ACTIVATE
                    elif now >= start_time:
                        if not self.data.window_open:
                            if not self.data.is_preheating:
                                _LOGGER.info("[%s] Pre-heat phase started. Target: %.1f°C", self.room_name, self.data.target_temperature)
                            self.data.is_preheating = True
                            self.data.desired_temp = self.data.target_temperature
                        else:
                            # Window open: track that we should preheat, but don't set temperature
                            self.data.is_preheating = False
                    
                    # CASE C: Outside of window
                    else:
                        self.data.is_preheating = False
                else:
                    # No order active
                    self.data.is_preheating = False
                    self.data.next_preheat_start = None

            # --- COMPENSATION & EXTERNAL CHANGE (ORIGINAL LOGIC) ---
            if external_change:
                _LOGGER.debug("[%s] External change detected, re-applying compensation", self.room_name)
                await self.async_calculate_and_apply_compensation()
            elif not self.data.window_open:
                await self.async_calculate_and_apply_compensation()

        except Exception as err:
            _LOGGER.error("[%s] Error updating data: %s", self.room_name, err)
            raise UpdateFailed(f"Error communicating with Tado: {err}") from err

        return self.data

    def _detect_external_target_change(self) -> bool:
        """Detects changes to the Tado thermostat (app, schedule, settings)."""
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


    def _calculate_preheat_minutes(self, target_temp: float | None = None) -> int:
        """Calculate minutes needed to reach desired temperature."""
        # 1. Determine the relevant target temperature
        check_temp = target_temp if target_temp is not None else self.data.desired_temp
        
        # 2. GET CURRENT ROOM TEMPERATURE (With safety fallback)
        room_now = self.data.external_temp 
        # Fallback to internal sensor if precision sensor is unavailable or delivers outside temps
        if room_now is None or room_now < 15.0:
            room_now = self.data.tado_temp

        # 3. EXIT CONDITIONS (The "Eco-Filter")
        # Stop calculation if:
        # - No target temperature is set
        # - Target is below 7°C (System Off/Frost protection)
        if check_temp is None or check_temp < 7.0:
            self._last_reported_mins = 0
            return 0
            
        # Calculate the actual heating demand
        room_delta = check_temp - room_now
        
        # STOP if we are already warm enough or the gap is too small (e.g. 19°C Eco mode)
        # This prevents "nervous" jumping when sensors fluctuate by 0.1°C
        if room_delta <= 0.2:
            if self._last_reported_mins != 0:
                self._last_reported_mins = 0
            return 0

        # 4. WEATHER FACTOR CALCULATION (Isolated from room delta)
        weather_factor = 1.0
        out_state = self.hass.states.get("sensor.aussentemperatur_heizungskontrolle")
        
        if out_state and out_state.state not in ["unknown", "unavailable"]:
            try:
                out_temp = float(out_state.state)
                diff_outside = max(0.0, 18.0 - out_temp)
                # Apply room-specific cooling sensitivity
                r_rate = 0.05 if any(k in self.room_name.lower() for k in ["office", "büro", "keller"]) else 0.03
                weather_factor = 1.0 + (diff_outside * r_rate)
            except (ValueError, TypeError):
                weather_factor = 1.0

        # 5. CORE DURATION CALCULATION
        # Use learned heating rate, or fallback to 1.5 °C/h for new rooms
        safe_heating_rate = self.data.heating_rate if self.data.heating_rate > 0.1 else 1.5
        
        minutes_raw = (room_delta / safe_heating_rate) * 60 * weather_factor
        buffered = minutes_raw * (1 + self.learning_buffer / 100)
        
        # Apply min/max limits from configuration
        new_val = int(max(self.min_preheat_minutes, min(self.max_preheat_minutes, buffered)))

        # 6. SPAM FILTER & LOGGING
        # Only report if change is significant (>= 2 min) or state jumps to/from zero
        if (abs(new_val - self._last_reported_mins) >= 2) or \
           (new_val > 0 and self._last_reported_mins <= 0) or \
           (new_val == 0 and self._last_reported_mins > 0):
            
            self._last_reported_mins = new_val
            _LOGGER.info(
                "PREHEAT-ADJUST [%s]: Delta %.2f°C (Target %.1f) -> Weather-Factor %.2f -> %s Min", 
                self.room_name, room_delta, check_temp, weather_factor, new_val
            )
            return new_val

        return self._last_reported_mins
    
    async def async_set_desired_temperature(self, temperature: float) -> None:
        """Set desired temperature and trigger compensation immediately."""
        self.data.desired_temp = max(MIN_TEMP, min(MAX_TEMP, temperature))
        # Mandatory compensation update
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
            raw_target = self.data.desired_temp - self.data.offset
            compensated_target = round(raw_target * 2) / 2
            force_send_due_to_target_reached = False
            
            _LOGGER.debug("%s: Heating active. Target: %.1f, Offset: %.1f -> Compensated: %.1f",
                         self.room_name, self.data.desired_temp, self.data.offset, compensated_target)

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
        """Calculates the heating rate based on the external sensor (immune to offset jumps)."""
        if self._heating_start_time is None or self._heating_start_temp is None:
            return None

        # --- Lockout period after window closure (calming phase)  ---
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
        duration_hrs = (now - self._heating_start_time).total_seconds() / 3600
        
        # 1. DEFINE VARIABLES
        temp_diff = current_external_temp - self._heating_start_temp
        instant_rate = temp_diff / duration_hrs
        duration_mins = duration_hrs * 60

        # 2. FILTER (to prevent too small/wrong numbers)
        if duration_hrs < 0.25 or temp_diff < 0.2 or instant_rate < 0.4:
            _LOGGER.debug(
                "%s: Cycle ignored - Duration: %.2fh, Delta: %.2f°C, Rate: %.2f°C/h (Thresholds not met)", 
                self.room_name, duration_hrs, temp_diff, instant_rate
            )
            return None

        # 3. SECURITY-FILTEER
        if instant_rate > MAX_HEATING_RATE:
            _LOGGER.info(
                "Ignore outliers in  %s: %.2f °C/h (Max: %.1f)", 
                self.room_name, instant_rate, MAX_HEATING_RATE
            )
            return None

        # 4. SAVE DATA (just one time!)
        self.data.heating_history.append(instant_rate)
        
        if len(self.data.heating_history) > MAX_HEATING_CYCLES:
            self.data.heating_history.pop(0)

        self.data.heating_rate = sum(self.data.heating_history) / len(self.data.heating_history)
        self.hass.async_create_task(self._async_save_data())

        return instant_rate

        
    async def async_load_data(self) -> None:
        """Loads the historical heating rate from JSON storage at start-up."""
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
        self.async_update_listeners()

    async def _async_save_data(self) -> None:
        """Saves the current history permanently to a JSON file."""
        await self._store.async_save({"history": self.data.heating_history})
    