"""
CAN Transport Implementation

Implements proper CAN bus communication for BMW diagnostics using SocketCAN.
This is the correct Linux-native approach for vehicle diagnostics.

Requirements:
- SocketCAN-compatible CAN adapter (e.g., PEAK PCAN-USB, Kvaser, CANable)
- can-utils package for interface setup
- python-can library
- can-isotp for ISO-TP layer
"""

import time
from typing import Any

from e92_pulse.core.app_logging import get_logger
from e92_pulse.transport.base import BaseTransport, TransportError

logger = get_logger(__name__)

# BMW E9x CAN Configuration
BMW_CAN_BITRATE = 500000  # 500 kbps
BMW_DIAG_TX_BASE = 0x6F1  # Tester -> ECU base ID
BMW_DIAG_RX_BASE = 0x600  # ECU -> Tester base ID (+ ECU offset)


class CANTransport(BaseTransport):
    """
    CAN transport using SocketCAN for BMW diagnostics.

    Uses python-can for CAN bus access and can-isotp for
    ISO-TP (ISO 15765-2) transport layer required by UDS.
    """

    def __init__(self) -> None:
        self._bus: Any = None
        self._isotp_layer: Any = None
        self._interface: str = "can0"
        self._target_address: int = 0x00
        self._is_open: bool = False

    def open(self, interface: str = "can0", bitrate: int = BMW_CAN_BITRATE) -> bool:
        """
        Open the CAN interface.

        Args:
            interface: SocketCAN interface name (e.g., can0, vcan0)
            bitrate: CAN bus bitrate (default 500000 for BMW)

        Returns:
            True if opened successfully
        """
        try:
            import can
        except ImportError:
            logger.error("python-can not installed. Install with: pip install python-can")
            raise TransportError(
                message="python-can library not installed",
                code="MISSING_DEPENDENCY",
                recoverable=False,
            )

        if self._is_open:
            logger.warning("CAN interface already open, closing first")
            self.close()

        try:
            # Try to open SocketCAN interface
            self._bus = can.interface.Bus(
                channel=interface,
                interface="socketcan",
                bitrate=bitrate,
            )

            self._interface = interface
            self._is_open = True

            logger.info(f"CAN interface opened: {interface} @ {bitrate} bps")
            return True

        except can.CanError as e:
            logger.error(f"Failed to open CAN interface: {e}")
            raise TransportError(
                message=f"Failed to open CAN interface {interface}: {e}",
                code="CAN_OPEN_FAILED",
                recoverable=True,
            )
        except OSError as e:
            logger.error(f"CAN interface not found: {e}")
            raise TransportError(
                message=f"CAN interface {interface} not found. Is SocketCAN configured?",
                code="INTERFACE_NOT_FOUND",
                recoverable=True,
            )

    def close(self) -> None:
        """Close the CAN interface."""
        if self._isotp_layer:
            try:
                self._isotp_layer.stop()
            except Exception:
                pass
            self._isotp_layer = None

        if self._bus:
            try:
                self._bus.shutdown()
                logger.info(f"CAN interface closed: {self._interface}")
            except Exception as e:
                logger.warning(f"Error closing CAN interface: {e}")
            finally:
                self._bus = None

        self._is_open = False

    def is_open(self) -> bool:
        """Check if CAN interface is open."""
        return self._is_open and self._bus is not None

    def set_target_address(self, address: int) -> None:
        """
        Set target ECU address.

        This configures the CAN arbitration IDs for ISO-TP communication.
        BMW uses:
        - TX: 0x6F1 (tester to all ECUs)
        - RX: 0x600 + ECU address offset
        """
        self._target_address = address

        # Reconfigure ISO-TP layer for new target
        if self._is_open:
            self._setup_isotp_for_target(address)

    def _setup_isotp_for_target(self, ecu_address: int) -> None:
        """Configure ISO-TP layer for specific ECU."""
        try:
            import isotp
        except ImportError:
            logger.warning("can-isotp not installed, using raw CAN")
            return

        # Close existing ISO-TP layer
        if self._isotp_layer:
            try:
                self._isotp_layer.stop()
            except Exception:
                pass

        # BMW arbitration ID scheme:
        # Tester -> ECU: 0x6F1 (broadcast) or specific
        # ECU -> Tester: 0x600 + ECU diagnostic address
        tx_id = BMW_DIAG_TX_BASE
        rx_id = BMW_DIAG_RX_BASE + ecu_address

        try:
            # Configure ISO-TP addressing
            tp_addr = isotp.Address(
                addressing_mode=isotp.AddressingMode.Normal_11bits,
                txid=tx_id,
                rxid=rx_id,
            )

            # ISO-TP parameters for BMW
            params = isotp.TransportParams()
            params.tx_padding = 0x00
            params.rx_consecutive_frame_timeout = 1.0
            params.max_frame_size = 4095

            self._isotp_layer = isotp.TransportLayer(
                rxfn=self._isotp_rx_callback,
                txfn=self._isotp_tx_callback,
                address=tp_addr,
                params=params,
            )
            self._isotp_layer.start()

            logger.debug(f"ISO-TP configured: TX=0x{tx_id:03X}, RX=0x{rx_id:03X}")

        except Exception as e:
            logger.warning(f"ISO-TP setup failed: {e}, using raw CAN")
            self._isotp_layer = None

    def _isotp_rx_callback(self) -> bytes | None:
        """Callback for ISO-TP receive."""
        if not self._bus:
            return None

        try:
            msg = self._bus.recv(timeout=0.01)
            if msg:
                return bytes(msg.data)
        except Exception:
            pass
        return None

    def _isotp_tx_callback(self, data: bytes) -> None:
        """Callback for ISO-TP transmit."""
        if not self._bus:
            return

        try:
            import can
            msg = can.Message(
                arbitration_id=BMW_DIAG_TX_BASE,
                data=data,
                is_extended_id=False,
            )
            self._bus.send(msg)
        except Exception as e:
            logger.error(f"CAN TX error: {e}")

    def send(self, data: bytes) -> bool:
        """
        Send UDS data via CAN/ISO-TP.

        Args:
            data: UDS payload bytes (service ID + data)

        Returns:
            True if sent successfully
        """
        if not self.is_open():
            raise TransportError(
                message="CAN interface not open",
                code="NOT_OPEN",
                recoverable=True,
            )

        try:
            if self._isotp_layer:
                # Send via ISO-TP (handles segmentation)
                self._isotp_layer.send(data)
                logger.debug(f"TX ISO-TP ({len(data)}): {data.hex()}")
            else:
                # Fallback: Raw CAN (single frame only)
                self._send_raw_can(data)

            return True

        except Exception as e:
            logger.error(f"CAN send error: {e}")
            return False

    def _send_raw_can(self, data: bytes) -> None:
        """Send raw CAN frame (single frame ISO-TP)."""
        import can

        if len(data) > 7:
            raise TransportError(
                message="Data too long for single CAN frame, ISO-TP required",
                code="DATA_TOO_LONG",
                recoverable=False,
            )

        # Single frame format: [length, data...]
        frame_data = bytes([len(data)]) + data
        frame_data = frame_data.ljust(8, b'\x00')  # Pad to 8 bytes

        msg = can.Message(
            arbitration_id=BMW_DIAG_TX_BASE,
            data=frame_data,
            is_extended_id=False,
        )

        self._bus.send(msg)
        logger.debug(f"TX CAN (0x{BMW_DIAG_TX_BASE:03X}): {frame_data.hex()}")

    def receive(self, timeout: float = 1.0) -> bytes | None:
        """
        Receive UDS response via CAN/ISO-TP.

        Args:
            timeout: Receive timeout in seconds

        Returns:
            UDS payload bytes or None on timeout
        """
        if not self.is_open():
            raise TransportError(
                message="CAN interface not open",
                code="NOT_OPEN",
                recoverable=True,
            )

        try:
            if self._isotp_layer:
                # Receive via ISO-TP
                data = self._isotp_layer.recv(timeout=timeout)
                if data:
                    logger.debug(f"RX ISO-TP ({len(data)}): {data.hex()}")
                    return data
            else:
                # Fallback: Raw CAN receive
                return self._receive_raw_can(timeout)

        except Exception as e:
            logger.error(f"CAN receive error: {e}")

        return None

    def _receive_raw_can(self, timeout: float) -> bytes | None:
        """Receive raw CAN frame."""
        expected_rx_id = BMW_DIAG_RX_BASE + self._target_address

        start_time = time.time()
        while (time.time() - start_time) < timeout:
            msg = self._bus.recv(timeout=0.1)
            if msg and msg.arbitration_id == expected_rx_id:
                # Single frame format: [length, data...]
                if msg.data[0] <= 7:
                    length = msg.data[0]
                    data = bytes(msg.data[1:1 + length])
                    logger.debug(f"RX CAN (0x{msg.arbitration_id:03X}): {data.hex()}")
                    return data

        return None

    def validate(self) -> bool:
        """
        Validate CAN connection by checking bus status.

        Returns:
            True if CAN interface is operational
        """
        if not self.is_open():
            return False

        try:
            # Try to get bus state
            state = self._bus.state
            logger.info(f"CAN bus state: {state}")
            return True
        except Exception as e:
            logger.warning(f"CAN validation failed: {e}")
            return False

    def flush(self) -> None:
        """Flush CAN buffers."""
        if self._bus:
            try:
                # Read and discard any pending messages
                while True:
                    msg = self._bus.recv(timeout=0.01)
                    if not msg:
                        break
            except Exception:
                pass

    def get_info(self) -> dict[str, Any]:
        """Get transport information."""
        return {
            "type": "socketcan",
            "interface": self._interface,
            "is_open": self.is_open(),
            "target": f"0x{self._target_address:02X}",
            "tx_id": f"0x{BMW_DIAG_TX_BASE:03X}",
            "rx_id": f"0x{BMW_DIAG_RX_BASE + self._target_address:03X}",
        }


def list_can_interfaces() -> list[str]:
    """
    List available SocketCAN interfaces.

    Returns:
        List of interface names (e.g., ['can0', 'vcan0'])
    """
    interfaces = []

    try:
        import os

        # Check /sys/class/net for CAN interfaces
        net_path = "/sys/class/net"
        if os.path.exists(net_path):
            for iface in os.listdir(net_path):
                iface_type_path = os.path.join(net_path, iface, "type")
                try:
                    with open(iface_type_path) as f:
                        # Type 280 = CAN
                        if f.read().strip() == "280":
                            interfaces.append(iface)
                except (IOError, OSError):
                    pass

        # Also check for virtual CAN
        for vcan in ["vcan0", "vcan1"]:
            if os.path.exists(f"/sys/class/net/{vcan}"):
                if vcan not in interfaces:
                    interfaces.append(vcan)

    except Exception as e:
        logger.warning(f"Error listing CAN interfaces: {e}")

    return sorted(interfaces)


def detect_usb_can_adapters() -> list[dict]:
    """
    Detect USB CAN adapters that may not be configured yet.

    Returns:
        List of detected USB CAN adapters with info
    """
    adapters = []

    # Known USB CAN adapter VID:PID pairs
    KNOWN_CAN_ADAPTERS = {
        (0x1D50, 0x606F): "CANable/candleLight",
        (0x1D50, 0x606D): "CANable 2.0",
        (0x0483, 0x5740): "STM32 USB CAN",
        (0x16D0, 0x0E88): "USB2CAN",
        (0x1209, 0x2323): "Innomaker USB2CAN",
        (0x1FC9, 0x0083): "NXP LPC USB CAN",
        (0x0403, 0x6015): "FTDI USB CAN",
        (0x1FC9, 0x0089): "USB CAN Analyzer",
    }

    try:
        # Check /sys/bus/usb/devices for USB devices
        import os
        usb_path = "/sys/bus/usb/devices"

        if os.path.exists(usb_path):
            for device in os.listdir(usb_path):
                device_path = os.path.join(usb_path, device)
                vid_path = os.path.join(device_path, "idVendor")
                pid_path = os.path.join(device_path, "idProduct")

                try:
                    if os.path.exists(vid_path) and os.path.exists(pid_path):
                        with open(vid_path) as f:
                            vid = int(f.read().strip(), 16)
                        with open(pid_path) as f:
                            pid = int(f.read().strip(), 16)

                        # Check if it's a known CAN adapter
                        if (vid, pid) in KNOWN_CAN_ADAPTERS:
                            name = KNOWN_CAN_ADAPTERS[(vid, pid)]
                            adapters.append({
                                "vid": vid,
                                "pid": pid,
                                "name": name,
                                "device": device,
                            })
                        # Also check for gs_usb devices (generic CAN)
                        elif vid == 0x1D50:  # OpenMoko/candleLight VID
                            adapters.append({
                                "vid": vid,
                                "pid": pid,
                                "name": "gs_usb CAN adapter",
                                "device": device,
                            })
                except (IOError, OSError, ValueError):
                    pass

        # Also check for gs_usb driver binding
        gs_usb_path = "/sys/bus/usb/drivers/gs_usb"
        if os.path.exists(gs_usb_path):
            for item in os.listdir(gs_usb_path):
                if ":" in item:  # USB device binding format
                    if not any(a.get("driver") == "gs_usb" for a in adapters):
                        adapters.append({
                            "name": "gs_usb CAN adapter",
                            "driver": "gs_usb",
                            "device": item,
                        })

    except Exception as e:
        logger.debug(f"Error detecting USB CAN adapters: {e}")

    return adapters


def get_interface_status(interface: str = "can0") -> dict:
    """
    Get detailed status of a CAN interface.

    Returns:
        Dict with interface status info
    """
    import os

    status = {
        "name": interface,
        "exists": False,
        "is_up": False,
        "is_can": False,
        "bitrate": None,
        "state": "unknown",
        "error": None,
    }

    net_path = f"/sys/class/net/{interface}"

    if not os.path.exists(net_path):
        status["error"] = f"Interface {interface} not found"
        return status

    status["exists"] = True

    # Check if it's a CAN interface
    try:
        with open(f"{net_path}/type") as f:
            if f.read().strip() == "280":
                status["is_can"] = True
    except (IOError, OSError):
        pass

    # Check operational state
    try:
        with open(f"{net_path}/operstate") as f:
            state = f.read().strip()
            status["state"] = state
            status["is_up"] = state == "up"
    except (IOError, OSError):
        pass

    # Try to get bitrate from can specific stats
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "-details", "link", "show", interface],
            capture_output=True,
            text=True,
        )
        if "bitrate" in result.stdout:
            # Parse bitrate from output
            for part in result.stdout.split():
                if part.isdigit() and int(part) > 100000:
                    status["bitrate"] = int(part)
                    break
    except Exception:
        pass

    return status


def setup_can_interface(interface: str = "can0", bitrate: int = BMW_CAN_BITRATE) -> bool:
    """
    Set up a SocketCAN interface (requires root).

    Args:
        interface: Interface name
        bitrate: CAN bus bitrate

    Returns:
        True if setup successful
    """
    import subprocess

    try:
        # Bring down interface first
        subprocess.run(
            ["ip", "link", "set", interface, "down"],
            capture_output=True,
            check=False,
        )

        # Set bitrate
        subprocess.run(
            ["ip", "link", "set", interface, "type", "can", "bitrate", str(bitrate)],
            capture_output=True,
            check=True,
        )

        # Bring up interface
        subprocess.run(
            ["ip", "link", "set", interface, "up"],
            capture_output=True,
            check=True,
        )

        logger.info(f"CAN interface {interface} configured at {bitrate} bps")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to setup CAN interface: {e}")
        return False
    except FileNotFoundError:
        logger.error("ip command not found - is iproute2 installed?")
        return False


def setup_virtual_can(interface: str = "vcan0") -> bool:
    """
    Set up a virtual CAN interface for testing.

    Args:
        interface: Virtual interface name

    Returns:
        True if setup successful
    """
    import subprocess

    try:
        # Load vcan module
        subprocess.run(
            ["modprobe", "vcan"],
            capture_output=True,
            check=False,
        )

        # Create virtual interface
        subprocess.run(
            ["ip", "link", "add", "dev", interface, "type", "vcan"],
            capture_output=True,
            check=False,  # May already exist
        )

        # Bring up interface
        subprocess.run(
            ["ip", "link", "set", interface, "up"],
            capture_output=True,
            check=True,
        )

        logger.info(f"Virtual CAN interface {interface} created")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to setup virtual CAN: {e}")
        return False
