"""
E92 Pulse Transport Layer

Provides abstracted transport implementations for diagnostic communication.
Supports SocketCAN for proper CAN bus access on Linux.
"""

from e92_pulse.transport.base import BaseTransport, TransportError
from e92_pulse.transport.can_transport import CANTransport

__all__ = [
    "BaseTransport",
    "TransportError",
    "CANTransport",
]
