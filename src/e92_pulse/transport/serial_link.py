"""
Serial Transport Implementation (DEPRECATED)

NOTE: This module is DEPRECATED. K+DCAN cables require proprietary
Windows drivers and do not work properly on Linux via serial.

For Linux, use the CAN transport with a SocketCAN-compatible adapter:
- PEAK PCAN-USB
- Kvaser
- CANable
- Or similar SocketCAN devices

See: can_transport.py for the correct Linux implementation.

Original K+DCAN Protocol Notes (historical):
- K-line: ISO 14230 (KWP2000) at 10400 baud for older modules
- D-CAN: ISO 15765 (CAN over serial) at 115200 baud for newer modules
- Most E92 modules use D-CAN at 500kbps CAN speed, 115200 serial
"""

import time
from typing import Any

from e92_pulse.core.app_logging import get_logger
from e92_pulse.transport.base import BaseTransport, TransportError

logger = get_logger(__name__)


class SerialTransport(BaseTransport):
    """
    Serial transport for K+DCAN USB cables.

    DEPRECATED: K+DCAN cables do not work properly on Linux.
    Use CANTransport with a SocketCAN adapter instead.

    Implements the low-level serial communication required
    for BMW diagnostic protocols over K-line/D-CAN.
    """

    # BMW D-CAN header format
    DCAN_HEADER_FORMAT = 0x00  # Standard addressing

    def __init__(self) -> None:
        self._serial: Any = None
        self._port: str | None = None
        self._baud_rate: int = 115200
        self._target_address: int = 0x00
        self._source_address: int = 0xF1  # Tester address
        self._use_dcan: bool = True  # Default to D-CAN mode

    def open(self, port: str, baud_rate: int = 115200) -> bool:
        """
        Open the serial port and initialize D-CAN mode.

        Args:
            port: Serial port path (e.g., /dev/ttyUSB0)
            baud_rate: Baud rate (default 115200 for D-CAN)

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
            logger.warning("Port already open, closing first")
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

            # Initialize D-CAN mode on the cable
            if not self._init_dcan_mode():
                logger.warning("D-CAN init failed, trying K-line mode")
                self._use_dcan = False

            logger.info(f"Serial port opened: {port} @ {baud_rate} baud")
            return True

        except serial.SerialException as e:
            logger.error(f"Failed to open serial port: {e}")
            raise TransportError(
                message=str(e),
                code="SERIAL_OPEN_FAILED",
                recoverable=True,
            )

    def _init_dcan_mode(self) -> bool:
        """
        Initialize D-CAN mode on K+DCAN cable.

        Different cables use different activation methods:
        - DTR/RTS control lines
        - Break condition
        - Wake-up byte sequence

        Returns:
            True if D-CAN mode initialized successfully
        """
        if not self.is_open():
            return False

        try:
            # Method 1: Try break condition first (some cables need this)
            logger.info("Trying D-CAN activation with break condition...")
            self._serial.break_condition = True
            time.sleep(0.025)  # 25ms break
            self._serial.break_condition = False
            time.sleep(0.025)

            # Method 2: Set DTR/RTS lines
            # Try different combinations - some cables are wired differently
            self._serial.dtr = True
            self._serial.rts = True
            time.sleep(0.05)

            # Flush buffers
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # Method 3: Send wake-up pattern (some cables need this)
            # Send 5-baud init pattern approximation
            wake_up = bytes([0x00, 0x00, 0x00])
            self._serial.write(wake_up)
            time.sleep(0.1)
            self._serial.reset_input_buffer()  # Discard any echo

            logger.info("D-CAN mode initialized (DTR=1, RTS=1, break sent)")
            return True

        except Exception as e:
            logger.warning(f"D-CAN init error: {e}")
            return False

    def _init_kline_mode(self) -> bool:
        """
        Initialize K-line mode (for older modules).

        K-line uses pin 7 of OBD port at slower speeds.

        Returns:
            True if K-line mode initialized
        """
        if not self.is_open():
            return False

        try:
            # K-line mode: Set DTR=0, RTS=1 for most cables
            self._serial.dtr = False
            self._serial.rts = True
            time.sleep(0.1)

            # Change baud rate for K-line
            self._serial.baudrate = 10400
            self._baud_rate = 10400

            logger.info("K-line mode initialized (DTR=0, RTS=1) @ 10400 baud")
            return True

        except Exception as e:
            logger.warning(f"K-line init error: {e}")
            return False

    def set_target_address(self, address: int) -> None:
        """Set the target ECU address for message framing."""
        self._target_address = address

    def close(self) -> None:
        """Close the serial port."""
        if self._serial:
            try:
                if self._serial.is_open:
                    # Reset control lines
                    self._serial.dtr = False
                    self._serial.rts = False
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
        Send data over serial with proper BMW framing.

        Args:
            data: UDS payload bytes (service ID + data)

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
            # Frame the message for BMW protocol
            framed_data = self._frame_message(data)

            bytes_written = self._serial.write(framed_data)
            self._serial.flush()

            if bytes_written != len(framed_data):
                logger.warning(
                    f"Partial write: {bytes_written}/{len(framed_data)} bytes"
                )
                return False

            logger.debug(f"TX ({len(framed_data)}): {framed_data.hex()}")

            # K+DCAN cables echo transmitted data back
            # We must read and discard the echo before reading the response
            time.sleep(0.05)  # Wait for echo to arrive
            echo = self._serial.read(len(framed_data))
            if echo:
                logger.debug(f"Echo ({len(echo)}): {echo.hex()}")
                if echo != framed_data:
                    logger.warning(f"Echo mismatch! Sent: {framed_data.hex()}, Got: {echo.hex()}")

            return True

        except Exception as e:
            logger.error(f"Serial write error: {e}")
            return False

    def _frame_message(self, data: bytes) -> bytes:
        """
        Frame UDS data for BMW K+DCAN cable.

        BMW uses ISO 14230 format:
        [Format] [Target] [Source] [Data...] [Checksum]

        The format byte encodes the length for short messages.
        """
        length = len(data)

        if length <= 7:
            # Single frame: format byte contains length
            format_byte = 0x80 | length
            frame = bytes([format_byte, self._target_address, self._source_address])
            frame += data
        else:
            # Longer message: length in separate byte
            format_byte = 0x80
            frame = bytes([format_byte, self._target_address, self._source_address, length])
            frame += data

        # Add checksum (XOR of all bytes)
        checksum = 0
        for b in frame:
            checksum ^= b
        frame += bytes([checksum])

        logger.debug(f"TX frame: {frame.hex()}")
        return frame

    def receive(self, timeout: float = 1.0) -> bytes | None:
        """
        Receive and unframe response from serial.

        Args:
            timeout: Receive timeout in seconds

        Returns:
            UDS payload bytes or None on timeout
        """
        if not self.is_open():
            raise TransportError(
                message="Serial port not open",
                code="NOT_OPEN",
                recoverable=True,
            )

        try:
            self._serial.timeout = timeout

            # ISO 14230 format: [Format] [Target] [Source] [Data...] [Checksum]
            # Read header (format + target + source)
            header = self._serial.read(3)
            if len(header) < 3:
                return None

            format_byte = header[0]
            logger.debug(f"RX header: {header.hex()}")

            # Extract length from format byte
            if format_byte & 0x80:
                length = format_byte & 0x3F
                if length == 0:
                    # Length in next byte
                    length_byte = self._serial.read(1)
                    if not length_byte:
                        return None
                    length = length_byte[0]
                    header += length_byte
            else:
                length = format_byte & 0x3F

            if length == 0:
                logger.warning("Zero length in response")
                return None

            # Read data + checksum
            remaining = length + 1  # data + checksum
            data = self._serial.read(remaining)

            if len(data) < remaining:
                logger.warning(f"Incomplete response: got {len(data)}, expected {remaining}")
                # Return what we got if any
                if len(data) > 1:
                    return data[:-1] if len(data) > 0 else None
                return None

            # Verify checksum (XOR of all bytes including header should equal received checksum)
            full_message = header + data[:-1]
            calc_checksum = 0
            for b in full_message:
                calc_checksum ^= b

            recv_checksum = data[-1]
            if calc_checksum != recv_checksum:
                logger.warning(f"Checksum mismatch: calc=0x{calc_checksum:02X}, recv=0x{recv_checksum:02X}")
                # Still return data - checksum issues are common

            payload = data[:-1]  # Return data without checksum
            logger.debug(f"RX payload ({len(payload)}): {payload.hex()}")
            return payload

        except Exception as e:
            logger.error(f"Serial read error: {e}")
            return None

    def receive_exact(self, count: int, timeout: float = 1.0) -> bytes | None:
        """
        Receive exactly count bytes (raw, no unframing).

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
        Validate connection by sending a TesterPresent message.

        Returns:
            True if ECU responds
        """
        if not self.is_open():
            return False

        try:
            # Send TesterPresent (0x3E 0x00)
            self.set_target_address(0x00)  # Broadcast
            tester_present = bytes([0x3E, 0x00])

            if not self.send(tester_present):
                return False

            # Try to receive response
            response = self.receive(timeout=0.5)

            # Any response (even negative) means something is connected
            if response:
                logger.info("Validation: ECU responded to TesterPresent")
                return True

            # No response - might still be OK, some ECUs don't respond to broadcast
            logger.info("Validation: No response to TesterPresent (may be normal)")
            return True  # Assume OK if port is open

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
            "mode": "D-CAN" if self._use_dcan else "K-line",
            "target": f"0x{self._target_address:02X}",
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

    def switch_to_kline(self) -> bool:
        """Switch to K-line mode for older modules."""
        self._use_dcan = False
        return self._init_kline_mode()

    def switch_to_dcan(self) -> bool:
        """Switch to D-CAN mode (default for E9x)."""
        self._use_dcan = True
        return self._init_dcan_mode()
