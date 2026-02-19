# Tado Local Offset - Custom Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/czepter/ha-tado-local-offset.svg)](https://github.com/czepter/ha-tado-local-offset/releases)
[![License](https://img.shields.io/github/license/czepter/ha-tado-local-offset.svg)](LICENSE)

A custom Home Assistant integration that provides temperature compensation for Tado Smart Radiator Thermostats controlled via the local HomeKit Controller integration.

## Why This Integration?

Tado's cloud API previously allowed setting temperature offsets to compensate for inaccurate built-in sensors. However, due to strict API rate limits, the cloud integration is no longer viable. The HomeKit Controller integration provides local control but doesn't expose offset adjustment.

This integration creates **virtual thermostats** that automatically compensate for sensor inaccuracies using external temperature sensors, while maintaining local control through HomeKit.

## Features

### Core Functionality
- ✅ **Virtual Thermostat Layer**: User-friendly climate entities that display true room temperature
- ✅ **Automatic Compensation**: Calculates and applies temperature offsets based on external sensors
- ✅ **UI Configuration**: Easy setup through Home Assistant's config flow (no YAML editing)
- ✅ **Multi-Room Support**: Configure multiple rooms independently

### Advanced Features
- 🪟 **Window Detection**: Automatic heating shutoff when windows open
  - Physical window sensors (binary_sensor)
  - Temperature drop detection (no sensor needed)
- 🔋 **Battery Saver Mode**: Intelligent update backoff to extend valve battery life
  - Configurable tolerance and update intervals
  - HVAC action awareness (don't interrupt active heating)
- 📊 **Adaptive Learning**: Learns your heating system's characteristics
  - Tracks heating cycles automatically
  - Calculates room-specific heating rates
- ⏰ **Pre-heat System**: Smart scheduling support
  - Predicts time needed to reach target temperature
  - Automatically starts heating before scheduled changes

## Installation

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select "Custom repositories"
4. Add repository URL: `https://github.com/czepter/ha-tado-local-offset`
5. Select category: "Integration"
6. Click "Add"
7. Find "Tado Local Offset" in HACS and click "Download"
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Extract the `custom_components/tado_local_offset` folder
3. Copy it to your Home Assistant's `custom_components` directory
4. Restart Home Assistant

## Configuration

### Prerequisites

Before configuring this integration, ensure you have:

1. **Tado Smart Radiator Thermostats** connected via HomeKit Controller integration
2. **External temperature sensors** (Zigbee/Z-Wave) placed in each room for accurate readings
3. **(Optional)** Window contact sensors for each room

### Setup via UI

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **"Tado Local Offset"**
4. Follow the configuration wizard:

#### Step 1: Device Selection
- **Room name**: Enter a name for the room (e.g., "Bedroom")
- **Tado device**: Select your Tado Smart Radiator Thermostat
  - The integration automatically discovers all related entities
- **External temperature sensor**: Select the accurate temperature sensor for this room

#### Step 2: Window Detection (Optional)
- **Enable window detection**: Toggle on if you have window sensors
- **Window contact sensor**: Select the window sensor entity
- **Enable temperature drop detection**: Toggle on to detect windows via temperature drops
- **Temperature drop threshold**: Set the threshold (default: 1.0°C)

#### Step 3: Battery Saver Settings
- **Enable battery saver mode**: Toggle on (recommended)
- **Temperature tolerance**: Set offset tolerance (default: 0.3°C)
- **Update backoff time**: Set minimum time between updates (default: 15 minutes)

#### Step 4: Pre-heat Settings (Optional)
- **Enable adaptive pre-heat**: Toggle on for learning-based scheduling
- **Learning safety buffer**: Add extra margin (default: 10%)
- **Minimum pre-heat time**: Shortest allowed duration (default: 15 minutes)
- **Maximum pre-heat time**: Longest allowed duration (default: 120 minutes)

## Usage

### Entities Created

For each configured room, the integration creates:

#### Climate Entity
- `climate.{room}_tado_local_offset`
- Your primary interface - set temperature here
- Displays actual room temperature from external sensor
- HVAC mode and action from real Tado

#### Sensors
- `sensor.{room}_temperature_offset` - Current offset calculation
- `sensor.{room}_heating_rate` - Learned heating rate (°C/min)
- `sensor.{room}_preheat_time` - Predicted pre-heat time needed
- `sensor.{room}_compensated_target` (diagnostic) - Actual target sent to Tado
- `sensor.{room}_last_compensation` (diagnostic) - Last update timestamp

#### Binary Sensors
- `binary_sensor.{room}_window_open` - Window detection status
- `binary_sensor.{room}_compensation_active` (diagnostic) - Compensation running

#### Configuration Numbers
- `number.{room}_desired_temperature` - Set via automations/schedules
- `number.{room}_tolerance` - Adjust compensation sensitivity
- `number.{room}_backoff_minutes` - Adjust update frequency

#### Configuration Switches
- `switch.{room}_battery_saver` - Enable/disable battery saver
- `switch.{room}_window_override` - Override window detection
- `switch.{room}_compensation_enabled` - Enable/disable compensation

### Services

#### `tado_local_offset.force_compensation`
Force immediate compensation update, bypassing backoff timer.

```yaml
service: tado_local_offset.force_compensation
data:
  entity_id: climate.bedroom_tado_local_offset  # or "all"
```

#### `tado_local_offset.reset_learning`
Clear heating cycle history and restart learning.

```yaml
service: tado_local_offset.reset_learning
data:
  entity_id: climate.bedroom_tado_local_offset  # or "all"
```

#### `tado_local_offset.set_preheat`
Manually trigger pre-heat for upcoming schedule.

```yaml
service: tado_local_offset.set_preheat
data:
  entity_id: climate.bedroom_tado_local_offset
  target_time: "07:00:00"
  target_temperature: 21.0
```

## How It Works

### Compensation Logic

1. **Offset Calculation**: `offset = external_temp - tado_temp`
2. **Compensated Target**: `compensated = desired_temp + offset`
3. **Apply to Tado**: Set real Tado thermostat to compensated target
4. **Result**: When Tado reaches its (compensated) target, the room is at your desired temperature

**Example:**
- You want: 21°C
- External sensor reads: 20°C
- Tado sensor reads: 22°C (2°C too high)
- Offset: 20 - 22 = -2°C
- Compensated target: 21 + (-2) = 19°C
- Set Tado to 19°C
- When Tado reaches 19°C, room is actually at 21°C ✓

### Battery Saver Optimizations

- **Tolerance check**: Skip updates if offset < configured tolerance
- **Backoff timer**: Minimum time between updates
- **HVAC awareness**: Don't interrupt active heating/cooling cycles
- **Window detection**: Pause when windows are open

### Learning System

Tracks completed heating cycles to calculate:
- Average heating rate (°C per minute)
- Weighted towards recent cycles
- Filters outliers automatically
- Improves pre-heat accuracy over time

## Automations Example

### Morning Schedule with Pre-heat

```yaml
automation:
  - alias: "Bedroom Morning Preheat"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: tado_local_offset.set_preheat
        data:
          entity_id: climate.bedroom_tado_local_offset
          target_time: "07:00:00"
          target_temperature: 21.0
```

### Adaptive Schedule Using Number Entity

```yaml
automation:
  - alias: "Living Room Evening"
    trigger:
      - platform: time
        at: "18:00:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.living_room_desired_temperature
        data:
          value: 22.0
```

## Troubleshooting

### Room not reaching target temperature
- Check `sensor.{room}_temperature_offset` - is it stable?
- Verify external sensor placement (avoid drafts, sunlight)
- Check `sensor.{room}_compensated_target` - is it reasonable?
- Increase tolerance if offset oscillates

### Too many updates / Battery draining
- Enable battery saver mode
- Increase tolerance (try 0.5°C)
- Increase backoff time (try 20-30 minutes)

### Pre-heat inaccurate
- Wait 7-14 days for learning to stabilize
- Check `sensor.{room}_heating_rate` - should be 0.05-0.3°C/min
- Adjust learning buffer if consistently early/late
- Ensure heating cycles complete without interruption

### Window detection false positives
- Increase temperature drop threshold
- Disable temp drop detection, use only physical sensors
- Check sensor placement (away from radiator)

## Development & Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by the original Tado cloud integration's offset feature
- Built for the Home Assistant community
- Thanks to all contributors and testers

## Support

- 🐛 [Report issues](https://github.com/czepter/ha-tado-local-offset/issues)
- 💬 [Discussions](https://github.com/czepter/ha-tado-local-offset/discussions)
- ⭐ Star the repo if you find it useful!
