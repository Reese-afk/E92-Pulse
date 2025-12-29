# E92 Pulse

BMW E92 M3 Diagnostic Tool - Plug and Play

## Requirements

- Linux (Fedora, Ubuntu, etc.)
- Innomaker USB2CAN adapter (~$33 on Amazon)
- DB9 to OBD2 cable (~$18 on Amazon)
- Python 3.10+

## Install

```bash
git clone https://github.com/Reese-afk/E92-Pulse.git
cd E92-Pulse
pip install -e .
```

## Run

```bash
# Setup CAN interface (one time after plugging in adapter)
sudo ip link set can0 up type can bitrate 500000

# Run the app
python -m e92_pulse
```

## Features

- Auto-detect USB CAN adapter
- Scan all ECU modules
- Read fault codes from all ECUs
- Clear fault codes from all ECUs

## ECU List (BMW E92 M3)

- DME (Engine) - 0x12
- EGS (Transmission) - 0x18
- ZGM (Gateway) - 0x00
- KOMBI (Instrument Cluster) - 0x40
- CAS (Car Access System) - 0x60
- DSC (Stability Control) - 0x6C
- EPS (Power Steering) - 0x72
- SZL (Steering Column) - 0x78
- IHKA (Climate) - 0xA0
- JBE (Junction Box) - 0xB8

## Troubleshooting

**No CAN interface found:**
```bash
# Check if adapter is recognized
lsusb | grep -i can

# Setup interface manually
sudo ip link set can0 up type can bitrate 500000
```

**Permission denied:**
```bash
# Add user to dialout group
sudo usermod -aG dialout $USER
# Log out and back in
```
