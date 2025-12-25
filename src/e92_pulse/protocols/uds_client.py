"""
UDS Client Wrapper

Provides a high-level interface for UDS (Unified Diagnostic Services)
communication with safety checks and tracing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable

from e92_pulse.core.app_logging import get_logger, log_diagnostic_action
from e92_pulse.core.safety import SafetyManager
from e92_pulse.transport.base import BaseTransport

logger = get_logger(__name__)


class UDSServiceID(IntEnum):
    """UDS Service Identifiers (ISO 14229-1)."""

    # Diagnostic and Communication Management
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    ECU_RESET = 0x11
    SECURITY_ACCESS = 0x27
    COMMUNICATION_CONTROL = 0x28
    TESTER_PRESENT = 0x3E
    CONTROL_DTC_SETTING = 0x85

    # Data Transmission
    READ_DATA_BY_ID = 0x22
    READ_MEMORY_BY_ADDRESS = 0x23
    READ_SCALING_DATA_BY_ID = 0x24
    WRITE_DATA_BY_ID = 0x2E

    # Stored Data Transmission
    CLEAR_DTC_INFO = 0x14
    READ_DTC_INFO = 0x19

    # Input/Output Control
    INPUT_OUTPUT_CONTROL = 0x2F

    # Routine Control
    ROUTINE_CONTROL = 0x31

    # Upload/Download (BLOCKED by safety manager)
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37


class UDSNegativeResponse(IntEnum):
    """UDS Negative Response Codes (ISO 14229-1)."""

    GENERAL_REJECT = 0x10
    SERVICE_NOT_SUPPORTED = 0x11
    SUB_FUNCTION_NOT_SUPPORTED = 0x12
    INCORRECT_MESSAGE_LENGTH = 0x13
    RESPONSE_TOO_LONG = 0x14
    BUSY_REPEAT_REQUEST = 0x21
    CONDITIONS_NOT_CORRECT = 0x22
    REQUEST_SEQUENCE_ERROR = 0x24
    NO_RESPONSE_FROM_SUBNET = 0x25
    FAILURE_PREVENTS_EXEC = 0x26
    REQUEST_OUT_OF_RANGE = 0x31
    SECURITY_ACCESS_DENIED = 0x33
    INVALID_KEY = 0x35
    EXCEEDED_ATTEMPTS = 0x36
    REQUIRED_TIME_DELAY = 0x37
    UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
    TRANSFER_DATA_SUSPENDED = 0x71
    GENERAL_PROGRAMMING_FAILURE = 0x72
    WRONG_BLOCK_SEQUENCE = 0x73
    SERVICE_NOT_SUPPORTED_IN_SESSION = 0x7F


@dataclass
class UDSError(Exception):
    """UDS-level error."""

    message: str
    code: int
    service_id: int
    raw_response: bytes | None = None

    def __str__(self) -> str:
        return f"UDSError[0x{self.code:02X}]: {self.message}"


@dataclass
class UDSResponse:
    """UDS response container."""

    service_id: int
    data: bytes
    positive: bool
    error_code: int | None = None
    error_message: str | None = None
    raw_request: bytes | None = None
    raw_response: bytes | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def get_data_int(self, offset: int = 0, length: int = 1) -> int:
        """Extract integer from response data."""
        if offset + length > len(self.data):
            return 0
        return int.from_bytes(self.data[offset : offset + length], "big")


@dataclass
class TraceEntry:
    """Protocol trace entry."""

    timestamp: datetime
    direction: str  # "TX" or "RX"
    service_id: int
    data: bytes
    description: str


class UDSClient:
    """
    High-level UDS client with safety enforcement.

    Wraps transport layer and provides UDS service methods
    with built-in safety checks and protocol tracing.
    """

    def __init__(
        self,
        transport: BaseTransport,
        safety_manager: SafetyManager | None = None,
        target_address: int = 0x00,
    ) -> None:
        """
        Initialize UDS client.

        Args:
            transport: Transport layer for communication
            safety_manager: Safety manager for operation validation
            target_address: Target ECU address
        """
        self._transport = transport
        self._safety = safety_manager or SafetyManager()
        self._target_address = target_address
        self._trace: list[TraceEntry] = []
        self._trace_callbacks: list[Callable[[TraceEntry], None]] = []
        self._session_type: int = 0x01  # Default session
        self._response_timeout: float = 2.0

    @property
    def trace(self) -> list[TraceEntry]:
        """Get protocol trace."""
        return self._trace.copy()

    def add_trace_callback(
        self, callback: Callable[[TraceEntry], None]
    ) -> None:
        """Add callback for trace entries."""
        self._trace_callbacks.append(callback)

    def clear_trace(self) -> None:
        """Clear protocol trace."""
        self._trace.clear()

    def set_target(self, address: int) -> None:
        """Set target ECU address."""
        self._target_address = address
        # Also update transport if it supports target addressing
        if hasattr(self._transport, "set_target_address"):
            self._transport.set_target_address(address)
        # For mock transport with ECU manager
        if hasattr(self._transport, "_connected_ecu") and self._transport._connected_ecu:
            if hasattr(self._transport._connected_ecu, "set_target"):
                self._transport._connected_ecu.set_target(address)

    def set_timeout(self, timeout: float) -> None:
        """Set response timeout."""
        self._response_timeout = timeout

    def send_request(
        self,
        service_id: int,
        data: bytes = b"",
        check_safety: bool = True,
    ) -> UDSResponse:
        """
        Send a UDS request and receive response.

        Args:
            service_id: UDS service ID
            data: Request data (after service ID)
            check_safety: Whether to check against safety manager

        Returns:
            UDSResponse with result

        Raises:
            UDSError: On communication or protocol error
        """
        # Safety check
        if check_safety and not self._safety.check_service(service_id):
            raise UDSError(
                message=self._safety.get_blocked_message(
                    f"Service 0x{service_id:02X}"
                ),
                code=0xFF,
                service_id=service_id,
            )

        # Build request
        request = bytes([service_id]) + data

        # Trace TX
        self._add_trace("TX", service_id, request, f"Request: {request.hex()}")

        # Send
        if not self._transport.send(request):
            raise UDSError(
                message="Failed to send request",
                code=0xFE,
                service_id=service_id,
            )

        # Receive
        response_data = self._transport.receive(self._response_timeout)

        if response_data is None:
            raise UDSError(
                message="No response (timeout)",
                code=0xFD,
                service_id=service_id,
            )

        # Parse response
        return self._parse_response(service_id, request, response_data)

    def _parse_response(
        self,
        request_service_id: int,
        request: bytes,
        response: bytes,
    ) -> UDSResponse:
        """Parse UDS response."""
        if len(response) < 1:
            raise UDSError(
                message="Empty response",
                code=0xFC,
                service_id=request_service_id,
                raw_response=response,
            )

        response_sid = response[0]

        # Positive response (service ID + 0x40)
        if response_sid == request_service_id + 0x40:
            self._add_trace(
                "RX", response_sid, response, f"Positive: {response.hex()}"
            )
            return UDSResponse(
                service_id=request_service_id,
                data=response[1:],
                positive=True,
                raw_request=request,
                raw_response=response,
            )

        # Negative response (0x7F)
        if response_sid == 0x7F and len(response) >= 3:
            error_sid = response[1]
            error_code = response[2]
            error_msg = self._get_error_message(error_code)

            self._add_trace(
                "RX",
                response_sid,
                response,
                f"Negative: {error_msg} (0x{error_code:02X})",
            )

            return UDSResponse(
                service_id=error_sid,
                data=response[3:] if len(response) > 3 else b"",
                positive=False,
                error_code=error_code,
                error_message=error_msg,
                raw_request=request,
                raw_response=response,
            )

        # Unknown response format
        self._add_trace(
            "RX", response_sid, response, f"Unknown: {response.hex()}"
        )
        return UDSResponse(
            service_id=response_sid,
            data=response[1:],
            positive=False,
            error_code=0xFB,
            error_message="Unexpected response format",
            raw_request=request,
            raw_response=response,
        )

    def _add_trace(
        self, direction: str, service_id: int, data: bytes, description: str
    ) -> None:
        """Add entry to protocol trace."""
        entry = TraceEntry(
            timestamp=datetime.now(),
            direction=direction,
            service_id=service_id,
            data=data,
            description=description,
        )
        self._trace.append(entry)

        for callback in self._trace_callbacks:
            try:
                callback(entry)
            except Exception as e:
                logger.warning(f"Trace callback error: {e}")

    def _get_error_message(self, code: int) -> str:
        """Get human-readable error message."""
        try:
            return UDSNegativeResponse(code).name.replace("_", " ").title()
        except ValueError:
            return f"Unknown Error (0x{code:02X})"

    # High-level service methods

    def diagnostic_session_control(self, session_type: int) -> UDSResponse:
        """
        Change diagnostic session.

        Args:
            session_type: Session type (0x01=default, 0x02=programming, 0x03=extended)

        Returns:
            UDSResponse
        """
        response = self.send_request(
            UDSServiceID.DIAGNOSTIC_SESSION_CONTROL,
            bytes([session_type]),
        )
        if response.positive:
            self._session_type = session_type
        return response

    def tester_present(self, suppress_response: bool = True) -> UDSResponse:
        """
        Send tester present to keep session alive.

        Args:
            suppress_response: Suppress positive response

        Returns:
            UDSResponse
        """
        sub_function = 0x80 if suppress_response else 0x00
        return self.send_request(
            UDSServiceID.TESTER_PRESENT,
            bytes([sub_function]),
        )

    def ecu_reset(self, reset_type: int) -> UDSResponse:
        """
        Reset ECU.

        Args:
            reset_type: Reset type (0x01=hard, 0x02=keyoff/on, 0x03=soft)

        Returns:
            UDSResponse

        Note:
            Only safe reset types are allowed (safety manager checks).
        """
        # Additional safety check for reset type
        if not self._safety.check_ecu_reset(reset_type):
            raise UDSError(
                message=f"Reset type 0x{reset_type:02X} not allowed",
                code=0xFF,
                service_id=UDSServiceID.ECU_RESET,
            )

        log_diagnostic_action(
            "ecu_reset",
            module_id=f"0x{self._target_address:02X}",
            details={"reset_type": reset_type},
        )

        return self.send_request(
            UDSServiceID.ECU_RESET,
            bytes([reset_type]),
        )

    def read_data_by_id(self, *data_ids: int) -> UDSResponse:
        """
        Read data by identifier.

        Args:
            data_ids: One or more 16-bit data identifiers

        Returns:
            UDSResponse with data
        """
        data = b""
        for did in data_ids:
            data += did.to_bytes(2, "big")

        return self.send_request(UDSServiceID.READ_DATA_BY_ID, data)

    def read_vin(self) -> str | None:
        """
        Read Vehicle Identification Number (VIN) from the ECU.

        Returns:
            VIN string if successful, None if failed
        """
        # Standard UDS DID for VIN is 0xF190
        VIN_DID = 0xF190

        try:
            response = self.read_data_by_id(VIN_DID)
            if response.is_positive and response.data:
                # Skip the DID echo (2 bytes) and decode VIN
                vin_data = response.data[2:] if len(response.data) > 2 else response.data
                # VIN is typically ASCII, 17 characters
                vin = vin_data.decode("ascii", errors="ignore").strip()
                # Validate VIN length
                if len(vin) >= 11:  # Minimum reasonable VIN length
                    return vin
            return None
        except Exception as e:
            logger.warning(f"Failed to read VIN: {e}")
            return None

    def write_data_by_id(self, data_id: int, data: bytes) -> UDSResponse:
        """
        Write data by identifier.

        Args:
            data_id: 16-bit data identifier
            data: Data to write

        Returns:
            UDSResponse

        Note:
            Protected DIDs are blocked by safety manager.
        """
        # Safety check for protected DIDs
        if not self._safety.check_write_did(data_id):
            raise UDSError(
                message=f"DID 0x{data_id:04X} is protected",
                code=0xFF,
                service_id=UDSServiceID.WRITE_DATA_BY_ID,
            )

        request_data = data_id.to_bytes(2, "big") + data
        return self.send_request(UDSServiceID.WRITE_DATA_BY_ID, request_data)

    def read_dtc_info(self, sub_function: int, data: bytes = b"") -> UDSResponse:
        """
        Read DTC information.

        Args:
            sub_function: Sub-function (e.g., 0x01=number, 0x02=by status mask)
            data: Additional data

        Returns:
            UDSResponse with DTC info
        """
        return self.send_request(
            UDSServiceID.READ_DTC_INFO,
            bytes([sub_function]) + data,
        )

    def clear_dtc_info(self, group: int = 0xFFFFFF) -> UDSResponse:
        """
        Clear diagnostic trouble codes.

        Args:
            group: DTC group (0xFFFFFF = all)

        Returns:
            UDSResponse

        Note:
            This action is logged for audit purposes.
        """
        log_diagnostic_action(
            "clear_dtc",
            module_id=f"0x{self._target_address:02X}",
            details={"group": f"0x{group:06X}"},
        )

        data = group.to_bytes(3, "big")
        return self.send_request(UDSServiceID.CLEAR_DTC_INFO, data)

    def routine_control(
        self,
        control_type: int,
        routine_id: int,
        data: bytes = b"",
    ) -> UDSResponse:
        """
        Execute routine control.

        Args:
            control_type: Control type (0x01=start, 0x02=stop, 0x03=request results)
            routine_id: 16-bit routine identifier
            data: Optional routine data

        Returns:
            UDSResponse

        Note:
            Dangerous routines are blocked by safety manager.
        """
        # Safety check for protected routines
        if not self._safety.check_routine(routine_id):
            raise UDSError(
                message=f"Routine 0x{routine_id:04X} is blocked",
                code=0xFF,
                service_id=UDSServiceID.ROUTINE_CONTROL,
            )

        log_diagnostic_action(
            "routine_control",
            module_id=f"0x{self._target_address:02X}",
            details={
                "control_type": control_type,
                "routine_id": f"0x{routine_id:04X}",
            },
        )

        request_data = (
            bytes([control_type]) + routine_id.to_bytes(2, "big") + data
        )
        return self.send_request(UDSServiceID.ROUTINE_CONTROL, request_data)

    def control_dtc_setting(self, on: bool) -> UDSResponse:
        """
        Enable/disable DTC setting.

        Args:
            on: True to enable, False to disable

        Returns:
            UDSResponse
        """
        sub_function = 0x01 if on else 0x02
        return self.send_request(
            UDSServiceID.CONTROL_DTC_SETTING,
            bytes([sub_function]),
        )
