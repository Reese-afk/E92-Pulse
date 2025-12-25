"""
Connection Manager

Manages the lifecycle of diagnostic connections including:
- Connection establishment and validation
- Automatic reconnection
- State management
- Event notifications
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Protocol

from e92_pulse.core.app_logging import get_logger, log_audit_event
from e92_pulse.core.discovery import PortDiscovery, PortInfo
from e92_pulse.core.config import AppConfig

logger = get_logger(__name__)


class ConnectionState(Enum):
    """Connection state machine states."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    VALIDATING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()
    ERROR = auto()


class TransportProtocol(Protocol):
    """Protocol for transport implementations."""

    def open(self, port: str, baud_rate: int) -> bool:
        """Open the transport connection."""
        ...

    def close(self) -> None:
        """Close the transport connection."""
        ...

    def is_open(self) -> bool:
        """Check if transport is open."""
        ...

    def send(self, data: bytes) -> bool:
        """Send data through the transport."""
        ...

    def receive(self, timeout: float) -> bytes | None:
        """Receive data from the transport."""
        ...

    def validate(self) -> bool:
        """Validate the connection is alive."""
        ...


@dataclass
class ConnectionError:
    """Details about a connection error."""

    message: str
    code: str
    recoverable: bool
    suggestion: str


StateChangeCallback = Callable[[ConnectionState, ConnectionState], None]


@dataclass
class ConnectionManager:
    """
    Manages diagnostic connection lifecycle.

    Handles port discovery, connection establishment, validation,
    and automatic reconnection.
    """

    config: AppConfig
    _state: ConnectionState = ConnectionState.DISCONNECTED
    _transport: TransportProtocol | None = None
    _current_port: PortInfo | None = None
    _discovery: PortDiscovery | None = None
    _state_callbacks: list[StateChangeCallback] = field(default_factory=list)
    _last_error: ConnectionError | None = None
    _simulation_mode: bool = False

    def __post_init__(self) -> None:
        """Initialize connection manager."""
        self._discovery = PortDiscovery(
            last_known_port=self.config.last_known_port
        )
        self._simulation_mode = self.config.simulation_mode

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def current_port(self) -> PortInfo | None:
        """Currently connected port."""
        return self._current_port

    @property
    def last_error(self) -> ConnectionError | None:
        """Last connection error."""
        return self._last_error

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._state == ConnectionState.CONNECTED

    def add_state_callback(self, callback: StateChangeCallback) -> None:
        """Add a callback for state changes."""
        self._state_callbacks.append(callback)

    def remove_state_callback(self, callback: StateChangeCallback) -> None:
        """Remove a state change callback."""
        if callback in self._state_callbacks:
            self._state_callbacks.remove(callback)

    def discover_ports(self, force_rescan: bool = False) -> list[PortInfo]:
        """Discover available ports."""
        if self._discovery is None:
            self._discovery = PortDiscovery()
        return self._discovery.discover_ports(force_rescan)

    def connect(self, port: str | PortInfo | None = None) -> bool:
        """
        Establish a diagnostic connection.

        Args:
            port: Port to connect to (device path, PortInfo, or None for auto)

        Returns:
            True if connection successful
        """
        if self._state == ConnectionState.CONNECTED:
            logger.warning("Already connected, disconnecting first")
            self.disconnect()

        self._set_state(ConnectionState.CONNECTING)

        # Resolve port
        port_info: PortInfo | None = None

        if port is None:
            # Auto-select best port
            if self._discovery is None:
                self._discovery = PortDiscovery()
            port_info = self._discovery.get_best_port()
            if port_info is None:
                self._set_error(
                    "No diagnostic ports detected",
                    "NO_PORTS",
                    recoverable=True,
                    suggestion="Check cable connection and USB permissions",
                )
                return False
        elif isinstance(port, PortInfo):
            port_info = port
        else:
            # It's a device path string
            if self._discovery is None:
                self._discovery = PortDiscovery()
            port_info = self._discovery.get_port_by_device(port)
            if port_info is None:
                # Create minimal PortInfo for the path
                from e92_pulse.core.discovery import ChipType

                port_info = PortInfo(
                    device=port,
                    name="Manual Port",
                    description="Manually specified port",
                    hwid="",
                    vid=None,
                    pid=None,
                    serial_number=None,
                    manufacturer=None,
                    product=None,
                    chip_type=ChipType.UNKNOWN,
                    by_id_path=None,
                    score=0,
                )

        logger.info(f"Connecting to {port_info.device}...")

        # Get or create transport
        if self._transport is None:
            self._transport = self._create_transport()

        try:
            # Attempt to open transport
            if not self._transport.open(
                port_info.by_id_path or port_info.device,
                self.config.connection.baud_rate,
            ):
                self._set_error(
                    f"Failed to open port {port_info.device}",
                    "OPEN_FAILED",
                    recoverable=True,
                    suggestion="Check if port is in use by another application",
                )
                return False

            self._current_port = port_info
            self._set_state(ConnectionState.VALIDATING)

            # Validate connection
            if not self._transport.validate():
                self._transport.close()
                self._set_error(
                    "Connection validation failed",
                    "VALIDATION_FAILED",
                    recoverable=True,
                    suggestion="Ensure ignition is ON and cable is properly connected",
                )
                return False

            self._set_state(ConnectionState.CONNECTED)
            self.config.last_known_port = port_info.device

            log_audit_event(
                "connection_established",
                f"Connected to {port_info.device}",
                {
                    "port": port_info.device,
                    "chip": port_info.chip_type.name,
                    "score": port_info.score,
                },
            )

            logger.info(f"Connected successfully to {port_info.device}")
            return True

        except Exception as e:
            logger.error(f"Connection error: {e}")
            self._set_error(
                str(e),
                "CONNECTION_EXCEPTION",
                recoverable=True,
                suggestion="Check cable and permissions",
            )
            return False

    def disconnect(self) -> None:
        """Disconnect from the diagnostic interface."""
        if self._transport and self._transport.is_open():
            try:
                self._transport.close()
            except Exception as e:
                logger.warning(f"Error closing transport: {e}")

        port_device = self._current_port.device if self._current_port else "unknown"
        self._current_port = None
        self._set_state(ConnectionState.DISCONNECTED)

        log_audit_event(
            "connection_closed",
            f"Disconnected from {port_device}",
        )

        logger.info("Disconnected")

    def set_transport(self, transport: TransportProtocol) -> None:
        """Set the transport implementation (for testing/simulation)."""
        self._transport = transport

    def get_transport(self) -> TransportProtocol | None:
        """Get the current transport."""
        return self._transport

    def _create_transport(self) -> TransportProtocol:
        """Create the appropriate transport instance."""
        if self._simulation_mode:
            from e92_pulse.transport.mock_transport import MockTransport

            logger.info("Using simulation transport")
            return MockTransport()
        else:
            from e92_pulse.transport.serial_link import SerialTransport

            return SerialTransport()

    def _set_state(self, new_state: ConnectionState) -> None:
        """Update state and notify callbacks."""
        old_state = self._state
        self._state = new_state

        if old_state != new_state:
            logger.debug(f"Connection state: {old_state.name} -> {new_state.name}")
            for callback in self._state_callbacks:
                try:
                    callback(old_state, new_state)
                except Exception as e:
                    logger.error(f"State callback error: {e}")

    def _set_error(
        self,
        message: str,
        code: str,
        recoverable: bool,
        suggestion: str,
    ) -> None:
        """Set error state with details."""
        self._last_error = ConnectionError(
            message=message,
            code=code,
            recoverable=recoverable,
            suggestion=suggestion,
        )
        self._set_state(ConnectionState.ERROR)
        logger.error(f"Connection error [{code}]: {message}")
