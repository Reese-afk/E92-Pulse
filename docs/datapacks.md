# Datapacks

Datapacks allow you to extend E92 Pulse with additional module definitions, DTC descriptions, and service routines without modifying the core application.

## Overview

Datapacks are YAML or JSON files placed in `~/.config/e92_pulse/datapacks/`. They are automatically loaded when the application starts.

**Important**: Datapacks must NOT contain proprietary BMW data. Only use publicly available information or your own definitions.

## Datapack Location

```
~/.config/e92_pulse/
├── config.yaml
└── datapacks/
    ├── my_custom_modules.yaml
    └── dtc_descriptions.json
```

## Schema

### Basic Structure

```yaml
# Datapack metadata
metadata:
  id: "my-datapack"
  name: "My Custom Datapack"
  version: "1.0.0"
  description: "Custom module definitions"
  author: "Your Name"
  license: "MIT"

# Module definitions
modules:
  - module_id: "CUSTOM"
    name: "Custom Module"
    description: "My custom module"
    address: 0x99
    category: "body"
    dtc_prefix: "B"
    priority: 50

# DTC descriptions (optional)
dtc_descriptions:
  "P0100": "Mass Air Flow Circuit"
  "P0171": "System Too Lean"

# Live data definitions (optional)
live_data:
  - id: "engine_rpm"
    name: "Engine RPM"
    did: 0x100C
    unit: "rpm"
    scale: 0.25
    offset: 0
```

### Module Definition Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `module_id` | string | Yes | Unique identifier (e.g., "DME") |
| `name` | string | Yes | Human-readable name |
| `description` | string | No | Description of function |
| `address` | integer | Yes | Diagnostic address (hex) |
| `can_id_tx` | integer | No | CAN TX ID |
| `can_id_rx` | integer | No | CAN RX ID |
| `category` | string | No | Category: powertrain, chassis, body, general |
| `dtc_prefix` | string | No | DTC code prefix: P, C, B, U |
| `supports_extended_session` | boolean | No | Whether module supports extended session |
| `priority` | integer | No | Scan priority (higher = scanned first) |
| `variants` | list | No | List of variant strings |

### Categories

- `powertrain`: Engine, transmission, emissions
- `chassis`: Suspension, brakes, steering
- `body`: Interior, exterior, comfort
- `general`: Other modules

### DTC Prefixes

- `P`: Powertrain
- `C`: Chassis
- `B`: Body
- `U`: Network/Communication

## Example Datapacks

### Custom Module Definitions

```yaml
metadata:
  id: "e92-extras"
  name: "E92 Extra Modules"
  version: "1.0.0"
  description: "Additional E92 module definitions"

modules:
  - module_id: "HEADUNIT"
    name: "Head Unit"
    description: "Aftermarket head unit"
    address: 0x68
    category: "body"
    dtc_prefix: "B"
    priority: 15

  - module_id: "EXHAUST"
    name: "Exhaust Valve Control"
    description: "Active exhaust valve controller"
    address: 0x75
    category: "powertrain"
    dtc_prefix: "P"
    priority: 25
```

### DTC Descriptions

```json
{
  "metadata": {
    "id": "dtc-descriptions",
    "name": "DTC Descriptions Pack",
    "version": "1.0.0"
  },
  "dtc_descriptions": {
    "P0100": "Mass Air Flow Circuit Malfunction",
    "P0101": "Mass Air Flow Circuit Range/Performance",
    "P0102": "Mass Air Flow Circuit Low Input",
    "P0103": "Mass Air Flow Circuit High Input",
    "P0171": "System Too Lean (Bank 1)",
    "P0174": "System Too Lean (Bank 2)",
    "C1000": "ABS Hydraulic Pump Motor Circuit",
    "B1000": "General Body Electrical"
  }
}
```

### Live Data Definitions

```yaml
metadata:
  id: "live-data"
  name: "Live Data Pack"
  version: "1.0.0"

live_data:
  - id: "engine_rpm"
    name: "Engine RPM"
    did: 0x100C
    unit: "rpm"
    scale: 0.25
    offset: 0
    min: 0
    max: 9000

  - id: "coolant_temp"
    name: "Coolant Temperature"
    did: 0x1005
    unit: "°C"
    scale: 1.0
    offset: -40
    min: -40
    max: 150

  - id: "throttle_position"
    name: "Throttle Position"
    did: 0x1011
    unit: "%"
    scale: 0.392
    offset: 0
    min: 0
    max: 100
```

## Loading Datapacks

Datapacks are automatically loaded when E92 Pulse starts. To refresh:

1. Close E92 Pulse
2. Modify datapack files
3. Restart E92 Pulse

## Validation

Datapacks are validated on load. Invalid entries are logged but don't prevent application startup.

Common validation errors:
- Missing required fields
- Invalid address format
- Duplicate module IDs

Check the application logs for validation errors:
```bash
e92-pulse --debug
```

## Best Practices

1. **Use descriptive IDs**: Make module_id and datapack ID meaningful
2. **Document your changes**: Include description fields
3. **Test thoroughly**: Use simulation mode to test new definitions
4. **Version your datapacks**: Increment version when making changes
5. **Avoid conflicts**: Use unique addresses and module IDs

## Security Note

**Never include in datapacks:**
- Security bypass routines
- Immobilizer/key data
- VIN modification routines
- Odometer reset routines
- ECU flash addresses

Such content is blocked by the safety manager regardless of datapack definitions.

## Sharing Datapacks

When sharing datapacks:
1. Include only non-proprietary information
2. Document the source of your data
3. Test with simulation mode
4. Include license information
