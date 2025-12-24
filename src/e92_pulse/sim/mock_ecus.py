"""
Mock ECU Implementations

Provides deterministic mock ECU responses for simulation mode.
All responses are predictable for reliable testing.
"""

from dataclasses import dataclass, field
from typing import Any

from e92_pulse.core.app_logging import get_logger
from e92_pulse.protocols.services import (
    UDSServices,
    DiagnosticSession,
    DTCSubFunction,
    DTCStatusMask,
    RoutineControlType,
    BatteryRoutines,
)

logger = get_logger(__name__)


@dataclass
class MockDTC:
    """Mock DTC for simulation."""

    code: int  # 3-byte DTC
    status: int  # Status mask byte
    description: str = ""


@dataclass
class SimulationConfig:
    """Configuration for simulation mode."""

    # Response timing (ms)
    response_delay_min: int = 5
    response_delay_max: int = 50

    # Module behavior
    modules_responding: list[str] = field(
        default_factory=lambda: [
            "DME",
            "DSC",
            "EGS",
            "KOMBI",
            "CAS",
            "FRM",
            "IHKA",
        ]
    )

    # Pre-configured DTCs per module
    module_dtcs: dict[str, list[MockDTC]] = field(default_factory=dict)

    # Battery registration success
    battery_registration_succeeds: bool = True

    def __post_init__(self) -> None:
        """Initialize default DTCs."""
        if not self.module_dtcs:
            self.module_dtcs = {
                "DME": [
                    MockDTC(0x010100, DTCStatusMask.CONFIRMED_DTC, "Mass Air Flow Sensor"),
                    MockDTC(0x013000, DTCStatusMask.PENDING_DTC, "Throttle Position"),
                ],
                "DSC": [
                    MockDTC(0xC10100, DTCStatusMask.CONFIRMED_DTC, "ABS Wheel Speed Sensor"),
                ],
                "KOMBI": [],  # No faults
            }


class MockECU:
    """
    Mock ECU for simulation.

    Responds to UDS requests with deterministic responses.
    """

    def __init__(
        self,
        module_id: str,
        address: int,
        config: SimulationConfig | None = None,
    ) -> None:
        """
        Initialize mock ECU.

        Args:
            module_id: Module identifier (e.g., "DME")
            address: Diagnostic address
            config: Simulation configuration
        """
        self.module_id = module_id
        self.address = address
        self._config = config or SimulationConfig()
        self._session = DiagnosticSession.DEFAULT
        self._dtcs: list[MockDTC] = self._config.module_dtcs.get(module_id, [])
        self._battery_registered = False

        # Software version (simulated)
        self._software_version = f"E92_{module_id}_V1.23"

    def process_request(self, request: bytes) -> bytes | None:
        """
        Process a UDS request and return response.

        Args:
            request: UDS request bytes

        Returns:
            UDS response bytes
        """
        if len(request) < 1:
            return None

        service_id = request[0]
        sub_data = request[1:] if len(request) > 1 else b""

        logger.debug(
            f"[SIM:{self.module_id}] Request: {service_id:02X} {sub_data.hex()}"
        )

        # Route to handler
        handlers = {
            UDSServices.DIAGNOSTIC_SESSION_CONTROL: self._handle_session_control,
            UDSServices.TESTER_PRESENT: self._handle_tester_present,
            UDSServices.READ_DATA_BY_IDENTIFIER: self._handle_read_data,
            UDSServices.READ_DTC_INFORMATION: self._handle_read_dtc,
            UDSServices.CLEAR_DIAGNOSTIC_INFORMATION: self._handle_clear_dtc,
            UDSServices.ROUTINE_CONTROL: self._handle_routine_control,
            UDSServices.ECU_RESET: self._handle_ecu_reset,
        }

        handler = handlers.get(service_id)
        if handler:
            response = handler(sub_data)
            logger.debug(f"[SIM:{self.module_id}] Response: {response.hex()}")
            return response

        # Service not supported
        return self._negative_response(service_id, 0x11)

    def _positive_response(self, service_id: int, data: bytes = b"") -> bytes:
        """Create positive response."""
        return bytes([service_id + 0x40]) + data

    def _negative_response(self, service_id: int, nrc: int) -> bytes:
        """Create negative response."""
        return bytes([0x7F, service_id, nrc])

    def _handle_session_control(self, data: bytes) -> bytes:
        """Handle Diagnostic Session Control."""
        if len(data) < 1:
            return self._negative_response(0x10, 0x13)

        session_type = data[0]

        # Accept default and extended sessions
        if session_type in (
            DiagnosticSession.DEFAULT,
            DiagnosticSession.EXTENDED,
        ):
            self._session = session_type
            # Response: session type + P2 timing parameters
            return self._positive_response(0x10, bytes([session_type, 0x00, 0x19, 0x01, 0xF4]))

        return self._negative_response(0x10, 0x12)  # Sub-function not supported

    def _handle_tester_present(self, data: bytes) -> bytes:
        """Handle Tester Present."""
        sub_function = data[0] if data else 0x00

        # Check suppress positive response bit
        if sub_function & 0x80:
            return b""  # No response

        return self._positive_response(0x3E, bytes([sub_function & 0x7F]))

    def _handle_read_data(self, data: bytes) -> bytes:
        """Handle Read Data By Identifier."""
        if len(data) < 2:
            return self._negative_response(0x22, 0x13)

        did = int.from_bytes(data[0:2], "big")

        # Handle common DIDs
        if did == 0xF190:  # VIN
            vin = b"WBSWD93537P" + self.module_id.encode()[:6].ljust(6, b"0")
            return self._positive_response(0x22, data[0:2] + vin)

        if did == 0xF194:  # Software version
            version = self._software_version.encode()[:20]
            return self._positive_response(0x22, data[0:2] + version)

        if did == 0x1001:  # Battery voltage
            voltage = int(13.8 * 10)  # 13.8V in 0.1V units
            return self._positive_response(
                0x22, data[0:2] + voltage.to_bytes(2, "big")
            )

        # Unknown DID
        return self._negative_response(0x22, 0x31)

    def _handle_read_dtc(self, data: bytes) -> bytes:
        """Handle Read DTC Information."""
        if len(data) < 1:
            return self._negative_response(0x19, 0x13)

        sub_function = data[0]

        if sub_function == DTCSubFunction.REPORT_NUMBER_OF_DTC_BY_STATUS_MASK:
            # Response: StatusAvailabilityMask + DTCFormatIdentifier + DTCCount
            mask = data[1] if len(data) > 1 else 0xFF
            count = sum(1 for d in self._dtcs if d.status & mask)
            return self._positive_response(
                0x19,
                bytes([sub_function, 0xFF, 0x01]) + count.to_bytes(2, "big"),
            )

        if sub_function == DTCSubFunction.REPORT_DTC_BY_STATUS_MASK:
            mask = data[1] if len(data) > 1 else 0xFF
            response_data = bytes([sub_function, 0xFF])

            for dtc in self._dtcs:
                if dtc.status & mask:
                    # DTC (3 bytes) + Status (1 byte)
                    response_data += dtc.code.to_bytes(3, "big") + bytes(
                        [dtc.status]
                    )

            return self._positive_response(0x19, response_data)

        return self._negative_response(0x19, 0x12)

    def _handle_clear_dtc(self, data: bytes) -> bytes:
        """Handle Clear Diagnostic Information."""
        # Clear all DTCs
        self._dtcs.clear()
        logger.info(f"[SIM:{self.module_id}] DTCs cleared")
        return self._positive_response(0x14)

    def _handle_routine_control(self, data: bytes) -> bytes:
        """Handle Routine Control."""
        if len(data) < 3:
            return self._negative_response(0x31, 0x13)

        control_type = data[0]
        routine_id = int.from_bytes(data[1:3], "big")

        if routine_id == BatteryRoutines.REGISTER_BATTERY:
            if control_type == RoutineControlType.START_ROUTINE:
                if self._config.battery_registration_succeeds:
                    self._battery_registered = True
                    logger.info(f"[SIM:{self.module_id}] Battery registered")
                    return self._positive_response(
                        0x31, bytes([control_type]) + data[1:3] + bytes([0x00])
                    )
                else:
                    return self._negative_response(0x31, 0x22)

            if control_type == RoutineControlType.REQUEST_ROUTINE_RESULTS:
                status = 0x00 if self._battery_registered else 0x01
                return self._positive_response(
                    0x31, bytes([control_type]) + data[1:3] + bytes([status])
                )

        # Routine not supported
        return self._negative_response(0x31, 0x31)

    def _handle_ecu_reset(self, data: bytes) -> bytes:
        """Handle ECU Reset."""
        if len(data) < 1:
            return self._negative_response(0x11, 0x13)

        reset_type = data[0]

        # Accept soft reset and key off/on reset
        if reset_type in (0x01, 0x02, 0x03):
            logger.info(f"[SIM:{self.module_id}] ECU reset type {reset_type}")
            return self._positive_response(0x11, bytes([reset_type]))

        return self._negative_response(0x11, 0x12)


class MockECUManager:
    """
    Manages mock ECUs for simulation mode.

    Routes requests to the appropriate mock ECU based on address.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        """
        Initialize mock ECU manager.

        Args:
            config: Simulation configuration
        """
        self._config = config or SimulationConfig()
        self._ecus: dict[int, MockECU] = {}
        self._current_target: int = 0

        # Initialize mock ECUs from configuration
        self._initialize_ecus()

    def _initialize_ecus(self) -> None:
        """Initialize mock ECUs based on module registry."""
        # Default addresses for E92 modules
        module_addresses = {
            "DME": 0x12,
            "EGS": 0x18,
            "DSC": 0x56,
            "EPS": 0x32,
            "KOMBI": 0x60,
            "CAS": 0x40,
            "FRM": 0x16,
            "CCC": 0x63,
            "IHKA": 0x3B,
            "PDC": 0x62,
            "SZL": 0x61,
            "ACSM": 0x64,
            "EDC": 0x59,
            "SINE": 0x73,
        }

        for module_id in self._config.modules_responding:
            if module_id in module_addresses:
                address = module_addresses[module_id]
                self._ecus[address] = MockECU(module_id, address, self._config)
                logger.debug(f"[SIM] Initialized mock ECU: {module_id} @ 0x{address:02X}")

    def set_target(self, address: int) -> None:
        """Set current target ECU address."""
        self._current_target = address

    def process_request(self, request: bytes) -> bytes | None:
        """
        Process request to current target ECU.

        Args:
            request: UDS request bytes

        Returns:
            UDS response bytes or None
        """
        ecu = self._ecus.get(self._current_target)
        if ecu:
            return ecu.process_request(request)

        # No ECU at this address - no response
        logger.debug(f"[SIM] No ECU at address 0x{self._current_target:02X}")
        return None

    def get_ecu(self, address: int) -> MockECU | None:
        """Get mock ECU by address."""
        return self._ecus.get(address)

    def get_all_addresses(self) -> list[int]:
        """Get all mock ECU addresses."""
        return list(self._ecus.keys())

    def add_dtc(self, module_id: str, dtc: MockDTC) -> bool:
        """Add a DTC to a mock ECU."""
        for ecu in self._ecus.values():
            if ecu.module_id == module_id:
                ecu._dtcs.append(dtc)
                return True
        return False

    def clear_all_dtcs(self) -> None:
        """Clear DTCs from all mock ECUs."""
        for ecu in self._ecus.values():
            ecu._dtcs.clear()
