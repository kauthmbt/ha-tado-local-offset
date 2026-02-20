"""Constants for the Tado Local Offset integration."""
from datetime import timedelta
from typing import Final

# Integration domain
DOMAIN: Final = "tado_local_offset"

# Platforms
PLATFORMS: Final = ["climate", "sensor", "binary_sensor", "number", "switch"]

# Configuration keys
CONF_ROOM_NAME: Final = "room_name"
CONF_TADO_DEVICE: Final = "tado_device"
CONF_TADO_CLIMATE_ENTITY: Final = "tado_climate_entity"
CONF_TADO_TEMP_SENSOR: Final = "tado_temp_sensor"
CONF_TADO_HUMIDITY_SENSOR: Final = "tado_humidity_sensor"
CONF_EXTERNAL_TEMP_SENSOR: Final = "external_temp_sensor"
CONF_WINDOW_SENSOR: Final = "window_sensor"
CONF_ENABLE_WINDOW_DETECTION: Final = "enable_window_detection"
CONF_ENABLE_TEMP_DROP_DETECTION: Final = "enable_temp_drop_detection"
CONF_TEMP_DROP_THRESHOLD: Final = "temp_drop_threshold"
CONF_ENABLE_BATTERY_SAVER: Final = "enable_battery_saver"
CONF_TOLERANCE: Final = "tolerance"
CONF_BACKOFF_MINUTES: Final = "backoff_minutes"
CONF_ENABLE_PREHEAT: Final = "enable_preheat"
CONF_LEARNING_BUFFER: Final = "learning_buffer"
CONF_MIN_PREHEAT_MINUTES: Final = "min_preheat_minutes"
CONF_MAX_PREHEAT_MINUTES: Final = "max_preheat_minutes"

# Default values
DEFAULT_TEMP_DROP_THRESHOLD: Final = 1.0
DEFAULT_TOLERANCE: Final = 0.3
DEFAULT_BACKOFF_MINUTES: Final = 15
DEFAULT_LEARNING_BUFFER: Final = 10
DEFAULT_MIN_PREHEAT_MINUTES: Final = 15
DEFAULT_MAX_PREHEAT_MINUTES: Final = 120
DEFAULT_DESIRED_TEMP: Final = 20.0
DEFAULT_HEATING_RATE: Final = 0.5  # °C per hour

# Update intervals
UPDATE_INTERVAL: Final = timedelta(seconds=30)
HISTORY_CHECK_INTERVAL: Final = timedelta(minutes=5)

# Limits
MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 25.0
MIN_TOLERANCE: Final = 0.1
MAX_TOLERANCE: Final = 2.0
MIN_BACKOFF: Final = 5
MAX_BACKOFF: Final = 60
MAX_OFFSET: Final = 5.0  # Maximum allowed offset to prevent invalid targets
MIN_HEATING_RATE: Final = 0.1
MAX_HEATING_RATE: Final = 2.5
MAX_HEATING_CYCLES: Final = 20  # Keep last 20 cycles for learning

# Temperature drop detection
TEMP_DROP_WINDOW_MINUTES: Final = 5
TEMP_DROP_RATE_THRESHOLD: Final = 0.15  # °C per minute

# Window detection delays
WINDOW_CLOSE_DELAY_SECONDS: Final = 120  # 2 minutes

# Attribute names
ATTR_OFFSET: Final = "temperature_offset"
ATTR_COMPENSATED_TARGET: Final = "compensated_target"
ATTR_HEATING_RATE: Final = "heating_rate"
ATTR_PREHEAT_MINUTES: Final = "preheat_minutes"
ATTR_LAST_COMPENSATION: Final = "last_compensation"
ATTR_WINDOW_OPEN: Final = "window_open"
ATTR_COMPENSATION_ACTIVE: Final = "compensation_active"

# Service names
SERVICE_FORCE_COMPENSATION: Final = "force_compensation"
SERVICE_RESET_LEARNING: Final = "reset_learning"
SERVICE_SET_PREHEAT: Final = "set_preheat"

# Service parameters
ATTR_TARGET_TIME: Final = "target_time"
ATTR_TARGET_TEMPERATURE: Final = "target_temperature"

# Storage keys
STORAGE_KEY: Final = f"{DOMAIN}_storage"
STORAGE_VERSION: Final = 1

# Device info
MANUFACTURER: Final = "Tado Local Offset"
MODEL: Final = "Virtual Thermostat"
