"""
Serial Transport Implementation

Implements K+DCAN serial communication for BMW diagnostics.
Handles serial port configuration, timing, and low-level protocol.
"""

import time
from typing import Any

from e92_pulse.core.app_logging import get_logger
from e92_pulse.transport.base import BaseTransport, TransportError

logger = get_logger(__name__)


class SerialTransport(BaseTransport):
    """
    Serial transport for K+DCAN USB cables.

    Implements the low-level serial communication required
    for BMW diagnostic protocols over K-line/D-CAN.
    """

    def __init__(self) -> None:
        self._serial: Any = None
        self._port: str | None = None
        self._baud_rate: int = 115200

    def open(self, port: str, baud_rate: int = 115200) -> bool:
        """
        Open the serial port.

        Args:
            port: Serial port path (e.g., /dev/ttyUSB0)
            baud_rate: Baud rate (default 115200 for K+DCAN)

        Returns:
            True if opened successfully
        """
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed")
            raise TransportError(
                message="pyserial library not installed",
                code="MISSING_DEPENDENCY",
                recoverable=False,
            )

        if self._serial and self._serial.is_open:
            logger.warning(f"Port already open, closing first")
            self.close()

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )

            self._port = port
            self._baud_rate = baud_rate

            # Flush buffers
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # Small delay for port stabilization
            time.sleep(0.1)

            logger.info(f"Serial port opened: {port} @ {baud_rate} baud")
            return True

        except serial.SerialException as e:
            logger.error(f"Failed to open serial port: {e}")
            raise TransportError(
                message=str(e),
                code="SERIAL_OPEN_FAILED",
                recoverable=True,
            )

    def close(self) -> None:
        """Close the serial port."""
        if self._serial:
            try:
                if self._serial.is_open:
                    self._serial.close()
                    logger.info(f"Serial port closed: {self._port}")
            except Exception as e:
                logger.warning(f"Error closing serial port: {e}")
            finally:
                self._serial = None
                self._port = None

    def is_open(self) -> bool:
        """Check if serial port is open."""
        return self._serial is not None and self._serial.is_open

    def send(self, data: bytes) -> bool:
        """
        Send data over serial.

        Args:
            data: Bytes to send

        Returns:
            True if sent successfully
        """
        if not self.is_open():
            raise TransportError(
                message="Serial port not open",
                code="NOT_OPEN",
                recoverable=True,
            )

        try:
            bytes_written = self._serial.write(data)
            self._serial.flush()

            if bytes_written != len(data):
                logger.warning(
                    f"Partial write: {bytes_written}/{len(data)} bytes"
                )
                return False

            logger.debug(f"TX ({len(data)}): {data.hex()}")
            return True

        except Exception as e:
            logger.error(f"Serial write error: {e}")
            return False

    def receive(self, timeout: float = 1.0) -> bytes | None:
        """
        Receive data from serial.

        Args:
            timeout: Receive timeout in seconds

        Returns:
            Received bytes or None on timeout
        """
        if not self.is_open():
            raise TransportError(
                message="Serial port not open",
                code="NOT_OPEN",
                recoverable=True,
            )

        try:
            # Set timeout
            self._serial.timeout = timeout

            # Read available data
            data = self._serial.read(1024)

            if data:
                logger.debug(f"RX ({len(data)}): {data.hex()}")
                return data

            return None

        except Exception as e:
            logger.error(f"Serial read error: {e}")
            return None

    def receive_exact(self, count: int, timeout: float = 1.0) -> bytes | None:
        """
        Receive exactly count bytes.

        Args:
            count: Number of bytes to receive
            timeout: Receive timeout in seconds

        Returns:
            Received bytes or None on timeout
        """
        if not self.is_open():
            return None

        try:
            self._serial.timeout = timeout
            data = self._serial.read(count)

            if len(data) == count:
                logger.debug(f"RX ({len(data)}): {data.hex()}")
                return data

            logger.warning(f"Partial read: {len(data)}/{count} bytes")
            return data if data else None

        except Exception as e:
            logger.error(f"Serial read error: {e}")
            return None

    def validate(self) -> bool:
        """
        Validate the connection by checking if port is responsive.

        For K+DCAN, we can check DTR/RTS lines or send a basic probe.

        Returns:
            True if connection is valid
        """
        if not self.is_open():
            return False

        try:
            # Check control lines
            self._serial.dtr = True
            self._serial.rts = True

            # Small delay
            time.sleep(0.05)

            # For real validation, we would send a diagnostic probe
            # Here we just verify the port is still functional
            return self._serial.is_open

        except Exception as e:
            logger.warning(f"Validation failed: {e}")
            return False

    def flush(self) -> None:
        """Flush serial buffers."""
        if self.is_open():
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

    def get_info(self) -> dict[str, Any]:
        """Get transport information."""
        return {
            "type": "serial",
            "port": self._port,
            "baud_rate": self._baud_rate,
            "is_open": self.is_open(),
        }

    def set_baud_rate(self, baud_rate: int) -> bool:
        """
        Change baud rate on open port.

        Args:
            baud_rate: New baud rate

        Returns:
            True if successful
        """
        if not self.is_open():
            return False

        try:
            self._serial.baudrate = baud_rate
            self._baud_rate = baud_rate
            logger.info(f"Baud rate changed to {baud_rate}")
            return True
        except Exception as e:
            logger.error(f"Failed to change baud rate: {e}")
            return False
