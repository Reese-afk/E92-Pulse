"""
Mock Transport Implementation

Provides a simulated transport for testing and demonstration.
Returns deterministic responses for predictable behavior in tests and CI.
"""

import time
from typing import Any
from collections import deque

from e92_pulse.core.app_logging import get_logger
from e92_pulse.transport.base import BaseTransport

logger = get_logger(__name__)


class MockTransport(BaseTransport):
    """
    Mock transport for simulation mode.

    Provides a queue-based transport that can be loaded with
    expected responses for testing and demonstration.
    """

    def __init__(self) -> None:
        self._is_open: bool = False
        self._interface: str | None = None
        self._tx_buffer: deque[bytes] = deque()
        self._rx_buffer: deque[bytes] = deque()
        self._connected_ecu: Any = None
        self._target_address: int = 0x00

    def set_target_address(self, address: int) -> None:
        """Set target ECU address for routing."""
        self._target_address = address
        if self._connected_ecu and hasattr(self._connected_ecu, "set_target"):
            self._connected_ecu.set_target(address)
        logger.debug(f"[MOCK] Target address set to 0x{address:02X}")

    def open(self, interface: str, bitrate: int = 500000) -> bool:
        """Simulate opening a CAN interface."""
        logger.info(f"[MOCK] Opening interface: {interface} @ {bitrate} bps")
        self._is_open = True
        self._interface = interface
        return True

    def close(self) -> None:
        """Simulate closing the interface."""
        logger.info("[MOCK] Closing interface")
        self._is_open = False
        self._interface = None
        self._tx_buffer.clear()
        self._rx_buffer.clear()

    def is_open(self) -> bool:
        """Check if mock port is open."""
        return self._is_open

    def send(self, data: bytes) -> bool:
        """
        Simulate sending data.

        If connected to a mock ECU, processes the request
        and queues the response.
        """
        if not self._is_open:
            return False

        logger.debug(f"[MOCK] TX ({len(data)}): {data.hex()}")
        self._tx_buffer.append(data)

        # If we have a connected mock ECU, process the request
        if self._connected_ecu:
            response = self._connected_ecu.process_request(data)
            if response:
                self._rx_buffer.append(response)

        return True

    def receive(self, timeout: float = 1.0) -> bytes | None:
        """Simulate receiving data."""
        if not self._is_open:
            return None

        # Simulate some latency
        time.sleep(min(timeout * 0.01, 0.01))

        if self._rx_buffer:
            data = self._rx_buffer.popleft()
            logger.debug(f"[MOCK] RX ({len(data)}): {data.hex()}")
            return data

        return None

    def validate(self) -> bool:
        """Mock validation always succeeds."""
        return self._is_open

    def connect_mock_ecu(self, ecu: Any) -> None:
        """Connect a mock ECU for response generation."""
        self._connected_ecu = ecu
        logger.info(f"[MOCK] Connected mock ECU: {ecu}")

    def queue_response(self, response: bytes) -> None:
        """Queue a response for the next receive call."""
        self._rx_buffer.append(response)

    def get_last_sent(self) -> bytes | None:
        """Get the last sent data (for testing)."""
        return self._tx_buffer[-1] if self._tx_buffer else None

    def get_sent_count(self) -> int:
        """Get count of sent messages."""
        return len(self._tx_buffer)

    def clear_buffers(self) -> None:
        """Clear all buffers."""
        self._tx_buffer.clear()
        self._rx_buffer.clear()

    def flush(self) -> None:
        """Clear input buffer."""
        self._rx_buffer.clear()

    def get_info(self) -> dict[str, Any]:
        """Get transport information."""
        return {
            "type": "mock",
            "interface": self._interface,
            "is_open": self._is_open,
            "tx_count": len(self._tx_buffer),
            "rx_pending": len(self._rx_buffer),
        }
