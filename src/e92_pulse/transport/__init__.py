"""
E92 Pulse Transport Layer

Provides abstracted transport implementations for diagnostic communication.
Supports serial (K+DCAN) and is future-ready for CAN/SocketCAN.
"""

from e92_pulse.transport.base import BaseTransport, TransportError
from e92_pulse.transport.serial_link import SerialTransport
from e92_pulse.transport.mock_transport import MockTransport

__all__ = [
    "BaseTransport",
    "TransportError",
    "SerialTransport",
    "MockTransport",
]
