# Linux Permissions Setup

This guide covers the necessary Linux permissions and configuration for using E92 Pulse with K+DCAN USB cables.

## Quick Setup

### 1. Add User to dialout Group

Serial ports on Linux are typically owned by the `dialout` group. Add your user to this group:

```bash
sudo usermod -aG dialout $USER
```

**Important**: You must log out and log back in for the group change to take effect.

### 2. Verify Group Membership

After logging back in, verify you're in the dialout group:

```bash
groups
```

You should see `dialout` in the output.

## Detailed Setup

### Check Current Permissions

First, identify your device:

```bash
# List USB serial devices
ls -la /dev/ttyUSB*

# Or for ACM devices
ls -la /dev/ttyACM*
```

Output example:
```
crw-rw---- 1 root dialout 188, 0 Jan 15 10:00 /dev/ttyUSB0
```

### Verify Access

Test if you can access the port:

```bash
# Try to read device info
cat /sys/class/tty/ttyUSB0/device/uevent
```

If you get a permission error, ensure you've logged out and back in after the group change.

## udev Rules

For more control over device permissions and naming, create udev rules.

### Create udev Rule File

Create `/etc/udev/rules.d/99-e92-pulse.rules`:

```bash
sudo nano /etc/udev/rules.d/99-e92-pulse.rules
```

### FTDI Devices

```udev
# FTDI FT232R USB-Serial (common K+DCAN cable)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", MODE="0666", GROUP="dialout", SYMLINK+="kdcan%n"

# FTDI FT232H
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6014", MODE="0666", GROUP="dialout", SYMLINK+="kdcan%n"

# FTDI FT2232
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", MODE="0666", GROUP="dialout", SYMLINK+="kdcan%n"
```

### CH340 Devices

```udev
# CH340
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666", GROUP="dialout", SYMLINK+="kdcan_ch340_%n"
```

### CP210x Devices

```udev
# Silicon Labs CP210x
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout", SYMLINK+="kdcan_cp210x_%n"
```

### Reload udev Rules

After creating or modifying rules:

```bash
# Reload rules
sudo udevadm control --reload-rules

# Trigger rules for existing devices
sudo udevadm trigger

# Or unplug and replug your device
```

## Stable Device Paths

E92 Pulse prefers stable device paths from `/dev/serial/by-id/` over dynamic `/dev/ttyUSB*` paths.

### Find Your Device's Stable Path

```bash
ls -la /dev/serial/by-id/
```

Example output:
```
lrwxrwxrwx 1 root root 13 Jan 15 10:00 usb-FTDI_FT232R_USB_UART_A12345-if00-port0 -> ../../ttyUSB0
```

### Benefits of Stable Paths

- Same path after reboot
- Consistent identification even with multiple USB serial devices
- No dependency on plug order

## Troubleshooting

### Permission Denied

If you see "Permission denied" errors:

1. Verify group membership: `groups`
2. Ensure you logged out and back in
3. Check device permissions: `ls -la /dev/ttyUSB*`
4. Try with sudo to confirm it's a permission issue

### Device Not Found

If your device isn't detected:

1. Check if it's connected: `lsusb`
2. Check dmesg for errors: `dmesg | tail -20`
3. Verify kernel module loaded: `lsmod | grep usbserial`

### Wrong Device Selected

If E92 Pulse selects the wrong port:

1. Unplug other USB serial devices
2. Use the port dropdown to manually select
3. Use the stable `/dev/serial/by-id/` path

### Driver Issues

For FTDI devices, the driver should be built into the kernel. For others:

```bash
# Check loaded modules
lsmod | grep -E "ftdi|ch341|cp210x|pl2303"

# Load module manually if needed
sudo modprobe ftdi_sio
sudo modprobe ch341
sudo modprobe cp210x
```

## Security Considerations

### Principle of Least Privilege

The dialout group approach is preferred over:
- Running as root (dangerous)
- chmod 777 on the device (too permissive)

### Audit Trail

E92 Pulse logs all diagnostic operations. Logs are stored in `./logs/` by default.

## Testing Your Setup

### Quick Test

```bash
# Test serial port access
python3 -c "import serial; s = serial.Serial('/dev/ttyUSB0', 115200, timeout=1); print('OK'); s.close()"
```

### With E92 Pulse

```bash
# Run in simulation mode first
e92-pulse --simulation

# Then test with real hardware
e92-pulse --debug
```

## Virtual Machine Considerations

If running in a VM:

1. Pass through the USB device to the VM
2. Install guest additions/tools
3. Ensure the VM user is in dialout group
4. Check VM USB settings for the correct device

### VirtualBox

```bash
# Add user to vboxusers
sudo usermod -aG vboxusers $USER
```

Then configure USB passthrough in VM settings.

### VMware

Use the VM > Removable Devices menu to connect the USB device.
