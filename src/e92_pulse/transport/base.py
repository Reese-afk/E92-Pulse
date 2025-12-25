"""
Base Transport Interface

Defines the abstract interface for all transport implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TransportError(Exception):
    """Transport-level error."""

    message: str
    code: str
    recoverable: bool = True

    def __str__(self) -> str:
        return f"TransportError[{self.code}]: {self.message}"


class BaseTransport(ABC):
    """
    Abstract base class for transport implementations.

    All transports must implement these methods for consistent
    behavior across CAN and mock implementations.
    """

    @abstractmethod
    def open(self, interface: str, bitrate: int = 500000) -> bool:
        """
        Open the transport connection.

        Args:
            interface: Interface identifier (can0, vcan0, simulation)
            bitrate: CAN bitrate (default 500000 for BMW)

        Returns:
            True if opened successfully
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the transport connection."""
        pass

    @abstractmethod
    def is_open(self) -> bool:
        """Check if the transport is open."""
        pass

    @abstractmethod
    def send(self, data: bytes) -> bool:
        """
        Send data through the transport.

        Args:
            data: Bytes to send

        Returns:
            True if sent successfully
        """
        pass

    @abstractmethod
    def receive(self, timeout: float = 1.0) -> bytes | None:
        """
        Receive data from the transport.

        Args:
            timeout: Receive timeout in seconds

        Returns:
            Received bytes or None on timeout
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """
        Validate the connection is alive and responsive.

        Returns:
            True if connection is valid
        """
        pass

    def flush(self) -> None:
        """Flush any pending data (optional implementation)."""
        pass

    def get_info(self) -> dict[str, Any]:
        """Get transport information (optional implementation)."""
        return {"type": self.__class__.__name__}
