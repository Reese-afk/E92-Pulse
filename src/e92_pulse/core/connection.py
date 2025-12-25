"""
Connection Manager

Manages the lifecycle of diagnostic connections including:
- Connection establishment and validation
- Support for SocketCAN interfaces (Linux-native)
- Simulation mode fallback
- State management and event notifications
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Protocol, Any

from e92_pulse.core.app_logging import get_logger, log_audit_event
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

    def open(self, interface: str, bitrate: int = 500000) -> bool:
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

    def set_target_address(self, address: int) -> None:
        """Set target ECU address."""
        ...


@dataclass
class InterfaceInfo:
    """Information about a CAN interface."""

    name: str  # e.g., "can0", "vcan0"
    interface_type: str  # "socketcan", "virtual", "simulation"
    description: str
    is_available: bool
    bitrate: int | None = None


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

    Supports:
    - SocketCAN interfaces (can0, can1, etc.)
    - Virtual CAN for testing (vcan0)
    - Simulation mode (no hardware required)
    """

    config: AppConfig
    _state: ConnectionState = ConnectionState.DISCONNECTED
    _transport: Any = None  # TransportProtocol
    _current_interface: InterfaceInfo | None = None
    _state_callbacks: list[StateChangeCallback] = field(default_factory=list)
    _last_error: ConnectionError | None = None
    _simulation_mode: bool = False

    def __post_init__(self) -> None:
        """Initialize connection manager."""
        self._simulation_mode = self.config.simulation_mode

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def current_interface(self) -> InterfaceInfo | None:
        """Currently connected interface."""
        return self._current_interface

    @property
    def last_error(self) -> ConnectionError | None:
        """Last connection error."""
        return self._last_error

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._state == ConnectionState.CONNECTED

    @property
    def simulation_mode(self) -> bool:
        """Check if in simulation mode."""
        return self._simulation_mode

    def set_simulation_mode(self, enabled: bool) -> None:
        """Enable or disable simulation mode."""
        if self.is_connected:
            self.disconnect()
        self._simulation_mode = enabled
        self._transport = None
        logger.info(f"Simulation mode: {enabled}")

    def add_state_callback(self, callback: StateChangeCallback) -> None:
        """Add a callback for state changes."""
        self._state_callbacks.append(callback)

    def remove_state_callback(self, callback: StateChangeCallback) -> None:
        """Remove a state change callback."""
        if callback in self._state_callbacks:
            self._state_callbacks.remove(callback)

    def discover_interfaces(self) -> list[InterfaceInfo]:
        """
        Discover available CAN interfaces.

        Returns:
            List of available interfaces (SocketCAN + simulation)
        """
        interfaces: list[InterfaceInfo] = []

        # Always add simulation mode option
        interfaces.append(
            InterfaceInfo(
                name="simulation",
                interface_type="simulation",
                description="Simulation Mode (No Hardware)",
                is_available=True,
                bitrate=None,
            )
        )

        # Check for SocketCAN interfaces
        try:
            from e92_pulse.transport.can_transport import list_can_interfaces

            can_interfaces = list_can_interfaces()
            for iface in can_interfaces:
                is_virtual = iface.startswith("vcan")
                interfaces.append(
                    InterfaceInfo(
                        name=iface,
                        interface_type="virtual" if is_virtual else "socketcan",
                        description=f"{'Virtual ' if is_virtual else ''}CAN Interface",
                        is_available=True,
                        bitrate=500000,
                    )
                )
        except Exception as e:
            logger.warning(f"Error discovering CAN interfaces: {e}")

        return interfaces

    def connect(self, interface: str | InterfaceInfo | None = None) -> bool:
        """
        Establish a diagnostic connection.

        Args:
            interface: Interface to connect to (name, InterfaceInfo, or None for simulation)

        Returns:
            True if connection successful
        """
        if self._state == ConnectionState.CONNECTED:
            logger.warning("Already connected, disconnecting first")
            self.disconnect()

        self._set_state(ConnectionState.CONNECTING)

        # Resolve interface
        interface_info: InterfaceInfo | None = None

        if interface is None or interface == "simulation" or self._simulation_mode:
            # Use simulation mode
            interface_info = InterfaceInfo(
                name="simulation",
                interface_type="simulation",
                description="Simulation Mode",
                is_available=True,
            )
            self._simulation_mode = True
        elif isinstance(interface, InterfaceInfo):
            interface_info = interface
        else:
            # It's an interface name string
            interface_info = InterfaceInfo(
                name=interface,
                interface_type="socketcan",
                description=f"CAN Interface {interface}",
                is_available=True,
                bitrate=500000,
            )

        logger.info(f"Connecting to {interface_info.name}...")

        # Get or create transport
        if self._transport is None:
            self._transport = self._create_transport()

        try:
            # Attempt to open transport
            if interface_info.interface_type == "simulation":
                # Mock transport doesn't need real interface
                if not self._transport.open("simulation", 0):
                    self._set_error(
                        "Failed to initialize simulation",
                        "SIM_INIT_FAILED",
                        recoverable=True,
                        suggestion="Restart the application",
                    )
                    return False
            else:
                # Real CAN interface
                bitrate = interface_info.bitrate or 500000
                if not self._transport.open(interface_info.name, bitrate):
                    self._set_error(
                        f"Failed to open CAN interface {interface_info.name}",
                        "CAN_OPEN_FAILED",
                        recoverable=True,
                        suggestion="Check if interface is up: sudo ip link set can0 up type can bitrate 500000",
                    )
                    return False

            self._current_interface = interface_info
            self._set_state(ConnectionState.VALIDATING)

            # Validate connection
            if not self._transport.validate():
                if interface_info.interface_type != "simulation":
                    self._transport.close()
                    self._set_error(
                        "CAN bus validation failed",
                        "VALIDATION_FAILED",
                        recoverable=True,
                        suggestion="Check CAN adapter and vehicle connection",
                    )
                    return False

            self._set_state(ConnectionState.CONNECTED)

            log_audit_event(
                "connection_established",
                f"Connected to {interface_info.name}",
                {
                    "interface": interface_info.name,
                    "type": interface_info.interface_type,
                },
            )

            logger.info(f"Connected successfully to {interface_info.name}")
            return True

        except Exception as e:
            logger.error(f"Connection error: {e}")
            self._set_error(
                str(e),
                "CONNECTION_EXCEPTION",
                recoverable=True,
                suggestion="Check CAN adapter installation and permissions",
            )
            return False

    def disconnect(self) -> None:
        """Disconnect from the diagnostic interface."""
        if self._transport:
            try:
                if hasattr(self._transport, 'is_open') and self._transport.is_open():
                    self._transport.close()
            except Exception as e:
                logger.warning(f"Error closing transport: {e}")

        interface_name = self._current_interface.name if self._current_interface else "unknown"
        self._current_interface = None
        self._set_state(ConnectionState.DISCONNECTED)

        log_audit_event(
            "connection_closed",
            f"Disconnected from {interface_name}",
        )

        logger.info("Disconnected")

    def set_transport(self, transport: Any) -> None:
        """Set the transport implementation (for testing/simulation)."""
        self._transport = transport

    def get_transport(self) -> Any:
        """Get the current transport."""
        return self._transport

    def _create_transport(self) -> Any:
        """Create the appropriate transport instance."""
        if self._simulation_mode:
            from e92_pulse.transport.mock_transport import MockTransport

            logger.info("Using simulation transport")
            return MockTransport()
        else:
            from e92_pulse.transport.can_transport import CANTransport

            logger.info("Using CAN transport (SocketCAN)")
            return CANTransport()

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
