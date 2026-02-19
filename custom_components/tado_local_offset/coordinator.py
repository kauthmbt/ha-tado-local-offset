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
# persistente Speicherung des Lernens
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
)

# Neue Konstanten für den Speicher
STORAGE_KEY = f"{DOMAIN}_storage"
STORAGE_VERSION = 1

_LOGGER = logging.getLogger(__name__) # Falls er hier schon steht, einfach lassen
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

    external_temp: float = 0.0
    tado_temp: float = 0.0
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
    
    # Dies ist eine spezielle Markierung für Python 3.13
    _: KW_ONLY 
    
    last_update: datetime = field(default_factory=dt_util.utcnow)
    heating_history: list[Any] = field(default_factory=list)
    next_preheat_start: datetime | None = field(default=None)


class TadoLocalOffsetCoordinator(DataUpdateCoordinator[TadoLocalOffsetData]):
    """Class to manage fetching Tado Local Offset data."""

    def __init__(self, hass: HomeAssistant, entry: dict[str, Any]) -> None:
        """Initialize the coordinator."""
        # 1. Zuerst den Speicher initialisieren!
        # STORAGE_VERSION und STORAGE_KEY müssen oben in der Datei definiert sein
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")

        # 2. Dann den super().__init__ aufrufen
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_ROOM_NAME]}",
            update_interval=UPDATE_INTERVAL,
        )

        self.entry = entry
        self.room_name = entry.data[CONF_ROOM_NAME]

        # Entity IDs
        self.tado_climate_entity = entry.data[CONF_TADO_CLIMATE_ENTITY]
        self.tado_temp_sensor = entry.data[CONF_TADO_TEMP_SENSOR]
        self.tado_humidity_sensor = entry.data.get(CONF_TADO_HUMIDITY_SENSOR)
        self.external_temp_sensor = entry.data[CONF_EXTERNAL_TEMP_SENSOR]
        self.window_sensor = entry.data.get(CONF_WINDOW_SENSOR)

        # Configuration
        self.enable_window_detection = entry.data.get(CONF_ENABLE_WINDOW_DETECTION, False)
        self.enable_temp_drop_detection = entry.data.get(CONF_ENABLE_TEMP_DROP_DETECTION, False)
        self.temp_drop_threshold = entry.data.get(CONF_TEMP_DROP_THRESHOLD, 1.0)
        self.tolerance = entry.options.get(CONF_TOLERANCE, entry.data.get(CONF_TOLERANCE, 0.3))
        self.backoff_minutes = entry.options.get(CONF_BACKOFF_MINUTES, entry.data.get(CONF_BACKOFF_MINUTES, 15))
        self.enable_preheat = entry.data.get(CONF_ENABLE_PREHEAT, False)
        self.learning_buffer = entry.data.get(CONF_LEARNING_BUFFER, 10)
        self.min_preheat_minutes = entry.data.get(CONF_MIN_PREHEAT_MINUTES, 15)
        self.max_preheat_minutes = entry.data.get(CONF_MAX_PREHEAT_MINUTES, 120)

        # Internal state
        self._last_compensation_time: datetime | None = None
        self._last_sent_compensated_target: float | None = None
        self._heating_start_time: datetime | None = None
        self._heating_start_temp: float | None = None
        self._heating_external_start_temp: float | None = None # NEU
        self._temp_history: list[tuple[datetime, float]] = []
        self._is_heating = False # NEU: Damit wir wissen, ob wir gerade heizen

        # Cooldown after compensation to let HomeKit state propagate (seconds)
        self._external_change_cooldown: float = 90.0

        # Initialize data
        self.data = TadoLocalOffsetData()

    async def _async_update_data(self) -> TadoLocalOffsetData:
        """Fetch data from sensors and calculate compensation."""
        try:
            # Get current sensor states
            external_temp_state = self.hass.states.get(self.external_temp_sensor)
            tado_temp_state = self.hass.states.get(self.tado_temp_sensor)
            tado_climate_state = self.hass.states.get(self.tado_climate_entity)

            # Validate states
            if not external_temp_state or external_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                raise UpdateFailed(f"External temperature sensor {self.external_temp_sensor} unavailable")

            if not tado_temp_state or tado_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                raise UpdateFailed(f"Tado temperature sensor {self.tado_temp_sensor} unavailable")

            if not tado_climate_state or tado_climate_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                raise UpdateFailed(f"Tado climate entity {self.tado_climate_entity} unavailable")

            # Parse temperatures
            try:
                external_temp = float(external_temp_state.state)
                tado_temp = float(tado_temp_state.state)
            except (ValueError, TypeError) as err:
                raise UpdateFailed(f"Invalid temperature value: {err}") from err

            # Update data
            self.data.external_temp = external_temp
            self.data.tado_temp = tado_temp
            self.data.tado_target = float(tado_climate_state.attributes.get("temperature", DEFAULT_DESIRED_TEMP))
            self.data.hvac_mode = tado_climate_state.state
            self.data.hvac_action = tado_climate_state.attributes.get("hvac_action", "idle")
            self.data.last_update = dt_util.utcnow()
            # --- NEU: Live-Learning für 5-Minuten-Sensoren ---
            current_hvac = self.data.hvac_action
            if current_hvac == "heating":
                if self._heating_start_time is None:
                    # Zyklus-Start: Zeit und EXTERNE Temp festhalten
                    self._heating_start_time = dt_util.utcnow()
                    # WICHTIG: Wir speichern die externe Temperatur als Startpunkt, 
                    # da diese sich nicht durch Offset-Sprünge ändert.
                    self._heating_start_temp = self.data.external_temp 
                    _LOGGER.info("Heizzyklus-Lernen gestartet bei %.2f°C (Extern)", self.data.external_temp)
                else:
                    # Live-Berechnung während der Heizphase
                    # Wir übergeben die aktuelle externe Temperatur an die Berechnung
                    instant_rate = self._calculate_instant_heating_rate(self.data.external_temp)
                    
                    if instant_rate is not None:
                        # Glättung über den Learning-Buffer
                        alpha = self.learning_buffer / 100
                        # Berechnung erfolgt in °C pro Stunde
                        self.data.heating_rate = round((self.data.heating_rate * (1 - alpha)) + (instant_rate * alpha), 4)
            else:
                # Heizung aus oder idle: Startwerte zurücksetzen
                if self._heating_start_time is not None:
                     _LOGGER.info("Heizzyklus-Lernen beendet.")
                self._heating_start_time = None
                self._heating_start_temp = None
            # --- ENDE NEU ---
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

        # Abkühlzeit nach eigener Änderung prüfen
        if self._last_compensation_time:
            elapsed = (dt_util.utcnow() - self._last_compensation_time).total_seconds()
            if elapsed < self._external_change_cooldown:
                return False

        # Initialer Abgleich beim Start
        if self._last_sent_compensated_target is None:
            if abs(self.data.desired_temp - tado_target) > 0.1:
                # Wir ziehen den aktuellen Offset ab, um den echten Wunschwert zu finden
                self.data.desired_temp = round(tado_target - self.data.offset, 1)
            return False

        # Erkennung einer externen Änderung (Schwellenwert 0.4°C)
        if abs(tado_target - self._last_sent_compensated_target) > 0.4:
            # WICHTIG: Den Offset abziehen, um das wahre neue Soll zu erhalten
            new_desired = round(tado_target - self.data.offset, 1)
            
            _LOGGER.info(
                "Externe Änderung für %s: Tado Ziel=%.1f°C -> Neues Soll: %.1f°C",
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
        """Check if window is open via sensor or temperature drop."""
        # Check physical sensor first
        if self.enable_window_detection and self.window_sensor:
            window_state = self.hass.states.get(self.window_sensor)
            if window_state and window_state.state == STATE_ON:
                return True

        # Check temperature drop detection
        if self.enable_temp_drop_detection:
            return self._detect_temperature_drop()

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
        """Set desired temperature and trigger compensation."""
        self.data.desired_temp = max(MIN_TEMP, min(MAX_TEMP, temperature))
        await self.async_calculate_and_apply_compensation()

    async def async_calculate_and_apply_compensation(self, force: bool = False) -> None:
        """Calculate and apply temperature compensation."""
        # Check if compensation should run
        if not force and not self._should_compensate():
            return

        # Calculate compensated target
        offset = self.data.offset

        # Cap offset to prevent extreme values
        offset = max(-MAX_OFFSET, min(MAX_OFFSET, offset))

        compensated = self.data.desired_temp + offset

        # Clamp to valid range
        compensated = max(MIN_TEMP, min(MAX_TEMP, compensated))

        # Store compensated target
        self.data.compensated_target = compensated

        # Check if update is needed (0.1°C threshold to avoid unnecessary updates)
        if abs(self.data.tado_target - compensated) < 0.1:
            return

        # Apply compensation
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                {
                    ATTR_ENTITY_ID: self.tado_climate_entity,
                    ATTR_TEMPERATURE: compensated,
                },
                blocking=True,
            )

            # Record what we sent and when, for external change detection
            self._last_compensation_time = dt_util.utcnow()
            self._last_sent_compensated_target = compensated

            self.logger.info(
                "Compensated %s: desired=%.1f°C, offset=%.1f°C, set Tado to %.1f°C",
                self.room_name,
                self.data.desired_temp,
                offset,
                compensated,
            )

        except Exception as err:
            self.logger.error("Failed to apply compensation: %s", err)
            raise

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
            self.logger.warning("Cannot force compensation: window is open")
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

        now = dt_util.utcnow()
        duration_hrs = (now - self._heating_start_time).total_seconds() / 3600
        
        # WICHTIG: temp_diff basiert hier auf dem externen Sensorwert, 
        # der beim Heizstart in self._heating_start_temp eingefroren wurde.
        temp_diff = current_external_temp - self._heating_start_temp

        # Filter für stabiles Lernen: 
        # Mind. 20 Min Laufzeit (0.33h) und 0.1°C Anstieg am EXTERNEN Sensor.
        if duration_hrs < 0.33 or temp_diff < 0.1:
            return None

        # Die Rate ist nun Grad pro Stunde (°C/h)
        instant_rate = temp_diff / duration_hrs
        
        # 1. Den neuen Wert zur Historie hinzufügen
        self.data.heating_history.append(instant_rate)
        
        # 2. Die Liste auf die maximale Anzahl begrenzen (aus const.py)
        from .const import MAX_HEATING_CYCLES, MIN_HEATING_RATE, MAX_HEATING_RATE
        if len(self.data.heating_history) > MAX_HEATING_CYCLES:
            self.data.heating_history.pop(0)

        # 3. Den neuen Durchschnitt berechnen
        self.data.heating_rate = sum(self.data.heating_history) / len(self.data.heating_history)

        # 4. Persistent speichern (JSON)
        self.hass.async_create_task(self._async_save_data())

        # 5. Validierung gegen Grenzwerte
        if MIN_HEATING_RATE <= instant_rate <= MAX_HEATING_RATE:
            return instant_rate
            
        return None

    async def async_load_data(self) -> None:
        """Lädt die historische Heizrate beim Start aus dem JSON-Speicher."""
        stored_data = await self._store.async_load()
        if stored_data and "history" in stored_data:
            self.data.heating_history = stored_data["history"]
            _LOGGER.info("Historische Heizdaten für %s geladen", self.room_name)

    async def _async_save_data(self) -> None:
        """Speichert die aktuelle Historie dauerhaft in eine JSON-Datei."""
        await self._store.async_save({"history": self.data.heating_history})
    
    async def async_calculate_and_apply_compensation(self, force: bool = False) -> None:
        """Berechnet die Kompensation und sendet sie aktiv an das Tado-Gerät."""
        if self.data.window_open and not self.data.window_override:
            return

        now = dt_util.utcnow()
        
        # Backoff-Timer prüfen (außer bei force=True)
        if not force and self._last_compensation_time:
            if now < self._last_compensation_time + timedelta(minutes=self.backoff_minutes):
                return

        # Berechne das Ziel für Tado (Wunschtemp + berechneter Offset)
        compensated_target = round(self.data.desired_temp + self.data.offset, 1)
        
        # Toleranzprüfung
        current_tado_target = self.data.tado_target
        diff = abs(compensated_target - current_tado_target)
        
        if not force and diff < self.tolerance:
            _LOGGER.debug("Änderung zu klein (%.2f < %.2f)", diff, self.tolerance)
            return

        # --- DIESER BEFEHL STEUERT DAS ECHTE THERMOSTAT ---
        _LOGGER.info("Sende an %s: %.1f°C", self.room_name, compensated_target)

        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {
                "entity_id": self.tado_climate_entity,
                "temperature": compensated_target,
            },
            blocking=True,
        )

        self._last_sent_compensated_target = compensated_target
        self._last_compensation_time = now
        self.data.compensated_target = compensated_target

    async def async_set_desired_temperature(self, temperature: float) -> None:
        """Wird aufgerufen, wenn du den Regler in Home Assistant verschiebst."""
        self.data.desired_temp = temperature
        # Sofort senden ohne Wartezeit
        await self.async_calculate_and_apply_compensation(force=True)