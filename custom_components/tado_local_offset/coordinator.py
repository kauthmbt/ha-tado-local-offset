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

        # Entity IDs - Sicherer Zugriff auf Data ODER Options
        def get_conf(key, default=None):
            return entry.options.get(key, entry.data.get(key, default))
            
        self.tado_climate_entity = get_conf(CONF_TADO_CLIMATE_ENTITY)
        self.tado_temp_sensor = get_conf(CONF_TADO_TEMP_SENSOR)
        self.tado_humidity_sensor = get_conf(CONF_TADO_HUMIDITY_SENSOR)
        self.external_temp_sensor = get_conf(CONF_EXTERNAL_TEMP_SENSOR)

        # Sicherheits-Check: Wenn Pflicht-Sensoren fehlen, Setup abbrechen
        if not self.tado_climate_entity or not self.external_temp_sensor:
            _LOGGER.warning(
                "Konfiguration für Raum '%s' unvollständig oder Sensoren noch nicht bereit. Setup wird fortgesetzt.", 
                self.room_name
            )
            # Hier darf KEIN 'raise UpdateFailed' stehen

        # Configuration
        self.enable_temp_drop_detection = entry.data.get(CONF_ENABLE_TEMP_DROP_DETECTION, False)
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

        # --- Fenster-Sensor Initialisierung (verbessert) ---
        conf_window = entry.options.get(
            CONF_WINDOW_SENSOR, 
            entry.data.get(CONF_WINDOW_SENSOR, [])
        )
        
        # Falls None zurückkommt (bei leerer Auswahl), setze eine leere Liste
        if conf_window is None:
            self.window_sensor = []
        elif isinstance(conf_window, str):
            # Falls nur ein einzelner String kommt, packe ihn in eine Liste
            self.window_sensor = [conf_window]
        else:
            self.window_sensor = conf_window
        
        # Sicherheits-Check: Falls noch ein alter einzelner String gespeichert ist, 
        # wandle ihn in eine Liste um.
        if isinstance(self.window_sensor, str):
            if self.window_sensor == "":
                self.window_sensor = []
            else:
                self.window_sensor = [self.window_sensor]
        
        # Sicherstellen, dass die Flags korrekt gesetzt sind
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
            # --- NEU: Sicherheitsprüfung der IDs, bevor hass.states.get aufgerufen wird ---
            if not self.external_temp_sensor or not self.tado_temp_sensor or not self.tado_climate_entity:
                _LOGGER.debug("Sensoren für %s noch nicht vollständig initialisiert", self.room_name)
                # Wir geben die aktuellen Daten einfach zurück, ohne abzubrechen
                return self.data
                
            # Get current sensor states
            external_temp_state = self.hass.states.get(self.external_temp_sensor)
            tado_temp_state = self.hass.states.get(self.tado_temp_sensor)
            tado_climate_state = self.hass.states.get(self.tado_climate_entity)

            # Validate states
            # 1. Prüfen, ob die Entitäten in HA überhaupt registriert sind
            if not external_temp_state or not tado_temp_state or not tado_climate_state:
                _LOGGER.warning("Setup-Warten: Sensoren in HA noch nicht gefunden (Extern: %s, Tado: %s)", 
                                self.external_temp_sensor, self.tado_temp_sensor)
                return self.data

            # 2. Prüfen, ob die Werte der Entitäten gültig sind (nicht unknown/unavailable)
            # Wir nutzen hier nur return, niemals 'raise', damit das Setup nicht abbricht.
            if (tado_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or 
                external_temp_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or
                tado_climate_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
                
                _LOGGER.debug("Einer der Sensoren liefert noch keine Werte (Status: unknown/unavailable)")
                return self.data

            # Parse temperatures
            try:
                external_temp = float(external_temp_state.state)
                tado_temp = float(tado_temp_state.state)
                
                # Plausibilitäts-Filter: HomeKit liefert oft 0.0 beim Start.
                # Wir loggen den Erhalt der Werte zur Diagnose.
                if tado_temp < 5.0 or external_temp < 5.0:
                    _LOGGER.warning("Unplausible Werte für %s erhalten (Tado: %.1f, Extern: %.1f)", 
                                    self.room_name, tado_temp, external_temp)
                    return self.data

                # WICHTIG: Zuweisung muss VOR den Berechnungen (Offset/Learning) erfolgen
                self.data.external_temp = external_temp
                self.data.tado_temp = tado_temp
                _LOGGER.info("Temperaturen für %s aktualisiert: %.1f (Extern: %.1f)", 
                             self.room_name, tado_temp, external_temp)
                    
            except (ValueError, TypeError) as err:
                _LOGGER.error("Fehler beim Parsen der Temperatur für %s: %s", self.room_name, err)
                return self.data

            # Update data
            self.data.external_temp = external_temp
            self.data.tado_temp = tado_temp
            self.data.tado_target = float(tado_climate_state.attributes.get("temperature", DEFAULT_DESIRED_TEMP))
            # HVAC-Mode Normalisierung (Wichtig für HomeKit)
            # Wir lesen den State (z.B. 'heat', 'idle', 'unknown')
            raw_state = str(tado_climate_state.state).lower()
            
            if raw_state == "off":
                self.data.hvac_mode = "off"
            else:
                # HomeKit meldet oft 'idle' als State, wenn nicht geheizt wird.
                # In HA muss der HVAC_MODE aber 'heat' bleiben, damit der Regler
                # aktiv bleibt. 'idle' gehört in die 'hvac_action'.
                self.data.hvac_mode = "heat"
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
        """Check if any window is open via sensors or temperature drop."""
        # 1. Physikalische Sensoren prüfen
        if self.enable_window_detection and self.window_sensor:
            # Wir stellen sicher, dass wir immer eine Liste haben
            sensors = self.window_sensor
            if isinstance(sensors, str):
                sensors = [sensors]

            for sensor_id in sensors:
                window_state = self.hass.states.get(sensor_id)
                if window_state and window_state.state == STATE_ON:
                    _LOGGER.debug("Fenster offen erkannt durch Sensor: %s", sensor_id)
                    return True

        # 2. Temperatursturz-Erkennung prüfen
        if self.enable_temp_drop_detection:
            # Wenn der Sturz erkannt wurde, geben wir True zurück
            if self._detect_temperature_drop():
                _LOGGER.debug("Fenster offen erkannt durch Temperatursturz")
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

        # 1. Vorab-Prüfung: Sollte überhaupt etwas gesendet werden?
        if not force:
            # Kompensation generell deaktiviert?
            if not self.data.compensation_enabled:
                return
            
            # Fenster offen? (Prüft alle Sensoren aus deiner neuen Liste)
            if self.data.window_open and not self.data.window_override:
                _LOGGER.debug("Kompensation übersprungen: Fenster/Tür ist offen")
                return

            # Battery Saver: Backoff-Zeit (Wartezeit) prüfen
            if self.data.battery_saver_enabled and self._last_compensation_time:
                if now < self._last_compensation_time + timedelta(minutes=self.backoff_minutes):
                    _LOGGER.debug("Battery Saver: Wartezeit noch nicht abgelaufen")
                    return

        # 2. Zielwert berechnen (LOGIK-UPDATE)
        # Wir prüfen: Ist es im Raum bereits so warm wie gewünscht?
        if self.data.external_temp >= self.data.desired_temp:
            # ZIEL ERREICHT: Wir senden nur noch den nackten Wunschwert.
            # Da Tado intern (durch den Offset) die höhere Temp sieht, schaltet es ab.
            raw_target = self.data.desired_temp
            _LOGGER.debug("%s: Ziel erreicht (%.1f >= %.1f). Sende Basis-Sollwert.", 
                         self.room_name, self.data.external_temp, self.data.desired_temp)
        else:
            # NOCH ZU KALT: Wir addieren den Offset, damit Tado weiter heizt.
            raw_target = self.data.desired_temp + self.data.offset
        
        # WICHTIG: Tado/HomeKit akzeptiert meist nur 0,5°C Schritte.
        # Wir runden hier kaufmännisch auf die nächste 0,5er Stelle.
        compensated_target = round(raw_target * 2) / 2
        
        # Sicherheitsgrenzen: Tado erlaubt meist 5°C bis 25°C
        compensated_target = max(5.0, min(25.0, compensated_target))

        # 3. Toleranzprüfung (Vergleich mit dem Ist-Zustand am Thermostat)
        current_tado_target = self.data.tado_target
        diff = abs(compensated_target - current_tado_target)
        
        # Nur senden, wenn die Änderung größer als deine eingestellte Toleranz ist
        if not force and diff < self.tolerance:
            _LOGGER.debug(
                "Änderung zu klein (%.2f < %.2f), sende kein Update an Tado", 
                diff, self.tolerance
            )
            return

        # 4. Der eigentliche Befehl an das Thermostat
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self.tado_climate_entity,
                    "temperature": compensated_target,
                },
                blocking=False, # GEÄNDERT auf False
            )
            self._last_sent_compensated_target = compensated_target
            self._last_compensation_time = now
            self.data.compensated_target = compensated_target
        except Exception as err:
            _LOGGER.error("Fehler beim Senden an Tado (%s): %s", self.room_name, err)
            
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
    
