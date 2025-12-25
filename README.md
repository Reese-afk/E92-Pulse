# E92 Pulse

A production-grade diagnostic GUI tool for BMW E92 M3 using K+DCAN USB cable. Provides ISTA-style guided workflows for vehicle diagnostics on Linux.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![Platform](https://img.shields.io/badge/platform-Linux-orange.svg)

## Features

- **ISTA-Style Guided Workflows**: Step-by-step wizards for diagnostics
- **Quick Test (Module Scan)**: Discover and probe all ECU modules
- **Fault Memory Management**: Read, display, search, and clear DTCs
- **Service Functions**: Battery registration, ECU reset
- **Session Export**: Export diagnostic sessions as ZIP/JSON
- **Simulation Mode**: Full functionality without hardware for testing

## What This Tool Does NOT Do

**HARD BLOCKED - These features are explicitly prohibited:**

- Immobilizer/key programming
- Security bypass mechanisms
- VIN tampering or modification
- Odometer/mileage changes
- ECU flashing, tuning, or coding that can brick modules
- Any theft-adjacent workflows

These restrictions are enforced at multiple layers and cannot be circumvented. All blocked attempts are logged.

## Hardware Requirements

- **K+DCAN USB Cable**: FTDI-based cables recommended for best compatibility
  - FTDI FT232R/FT232H (preferred)
  - CH340/CH341 (compatible)
  - CP210x, PL2303 (compatible)
- **Linux System**: Tested on Ubuntu 22.04+, Debian 12+
- **Python 3.11+**

### Recommended Cables

1. **FTDI-based K+DCAN cables** - Most reliable for BMW diagnostics
2. Ensure your cable supports both K-line and D-CAN protocols

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/example/e92-pulse.git
cd e92-pulse

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e ".[dev]"
```

### Dependencies

Core dependencies are installed automatically:
- PyQt6 (GUI framework)
- pyserial (serial port access)
- python-can (CAN bus support)
- can-isotp (ISO-TP protocol)
- udsoncan (UDS protocol)
- pyyaml (configuration)
- platformdirs (platform paths)

## Linux Permissions

### Add User to dialout Group

```bash
sudo usermod -aG dialout $USER
```

**Important**: Log out and back in for group changes to take effect.

### Verify Permissions

```bash
# Check group membership
groups

# Verify you can access the serial port
ls -la /dev/ttyUSB*
```

### Optional: udev Rule

For persistent permissions, create `/etc/udev/rules.d/99-kdcan.rules`:

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", MODE="0666", GROUP="dialout"
```

Then reload udev:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

See [docs/linux-permissions.md](docs/linux-permissions.md) for detailed setup instructions.

## Usage

### Run with GUI

```bash
# Using module
python -m e92_pulse

# Using console script
e92-pulse

# With simulation mode (no hardware needed)
e92-pulse --simulation

# With debug logging
e92-pulse --debug
```

### Command Line Options

```
usage: e92-pulse [-h] [--simulation] [--debug] [--log-dir LOG_DIR] [--config CONFIG] [--version]

E92 Pulse - BMW E92 M3 Diagnostic Tool

options:
  -h, --help         show this help message and exit
  --simulation, -s   Run in simulation mode (no hardware required)
  --debug, -d        Enable debug logging
  --log-dir LOG_DIR  Custom log directory (default: ./logs)
  --config CONFIG    Path to configuration file
  --version, -v      show program's version number and exit
```

## Workflow Guide

### 1. Connect

1. Plug in your K+DCAN USB cable
2. Connect the OBD-II end to your vehicle
3. Turn ignition ON (engine OFF)
4. Launch E92 Pulse
5. Select the detected port and click "Connect"

### 2. Quick Test (Module Scan)

1. Navigate to "Quick Test"
2. Click "Start Scan"
3. View the results showing all modules and their status:
   - **OK**: Module responding, no faults
   - **FAULT**: Module responding with DTCs
   - **NO RESPONSE**: Module not responding

### 3. Fault Memory

1. Navigate to "Fault Memory"
2. Click "Read DTCs" to retrieve all fault codes
3. Use filters to search and organize
4. Select DTCs to view details
5. Clear DTCs with confirmation dialogs

### 4. Service Functions

**Battery Registration:**
1. Navigate to "Service Functions"
2. Select "Battery Registration"
3. Enter battery capacity and type
4. Confirm all preconditions
5. Execute the registration

**ECU Reset:**
1. Select "ECU Reset"
2. Choose the target module
3. Select reset type (Soft/Key Off-On)
4. Confirm and execute

### 5. Export Session

1. Navigate to "Export Session"
2. Select what to include
3. Export as ZIP or JSON
4. Share with technicians or for records

## Configuration

Configuration is stored in `~/.config/e92_pulse/config.yaml`:

```yaml
simulation_mode: false
datapacks_dir: ~/.config/e92_pulse/datapacks
connection:
  preferred_port: null
  baud_rate: 115200
  timeout: 1.0
ui:
  theme: dark
  confirm_dtc_clear: true
logging:
  log_level: INFO
  log_dir: ./logs
```

## Datapacks

Additional module definitions can be loaded from user datapacks. See [docs/datapacks.md](docs/datapacks.md) for the schema.

Place datapack files in `~/.config/e92_pulse/datapacks/`.

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=e92_pulse --cov-report=html
```

### Code Quality

```bash
# Format code
black src tests

# Lint
ruff check src tests

# Type checking
mypy src
```

## Logging

All diagnostic actions are logged to `./logs/` in JSONL format for audit purposes:

```json
{"timestamp": "2024-01-15T10:30:00", "level": "INFO", "action": "clear_dtc", "module_id": "DME", "success": true}
```

## Roadmap

- [ ] Live data monitoring (engine parameters, sensors)
- [ ] Adaptation reset functions
- [ ] Service interval reset
- [ ] Enhanced DTC descriptions via datapacks
- [ ] Plugin system for extended functionality
- [ ] SocketCAN support for native CAN interfaces
- [ ] Report generation (PDF)

## Safety and Security

This tool is designed with safety as a priority:

1. **Safety Manager**: All operations are checked against blocked lists
2. **Two-Step Confirmations**: Destructive actions require confirmation
3. **Audit Logging**: Every action is logged with timestamps
4. **No Security Bypass**: Security Access service is blocked
5. **No ECU Flashing**: Upload/Download services are blocked

## Contributing

Contributions are welcome! Please read the contributing guidelines and ensure:

1. All tests pass
2. Code is formatted with black
3. No security-sensitive features are added
4. Safety blocks are not circumvented

## License

MIT License - See [LICENSE](LICENSE) for details.

## Disclaimer

This software is provided as-is for educational and diagnostic purposes. Users are responsible for ensuring proper use. The authors are not liable for any damage resulting from use of this software.

Always follow proper diagnostic procedures and safety precautions when working with vehicle electronics.
