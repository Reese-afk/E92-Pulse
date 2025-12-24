"""
BMW Service Functions

Implements safe service routines for BMW E92 M3.
All dangerous operations are explicitly blocked.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable

from e92_pulse.core.app_logging import get_logger, log_audit_event, log_diagnostic_action
from e92_pulse.core.safety import SafetyManager
from e92_pulse.core.vehicle import ServiceRecord, VehicleProfile
from e92_pulse.protocols.uds_client import UDSClient, UDSError
from e92_pulse.protocols.services import (
    DiagnosticSession,
    RoutineControlType,
    ResetType,
    BatteryRoutines,
)

logger = get_logger(__name__)


class ServiceState(Enum):
    """Service execution state."""

    IDLE = auto()
    CHECKING_PRECONDITIONS = auto()
    EXECUTING = auto()
    COMPLETE = auto()
    FAILED = auto()
    ABORTED = auto()


@dataclass
class ServiceResult:
    """Result of a service execution."""

    service_name: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Precondition:
    """Service precondition."""

    name: str
    description: str
    check_fn: Callable[[], bool]
    required: bool = True
    met: bool | None = None

    def check(self) -> bool:
        """Check if precondition is met."""
        try:
            self.met = self.check_fn()
            return self.met
        except Exception as e:
            logger.warning(f"Precondition check failed: {self.name} - {e}")
            self.met = False
            return False


# Callback types
ServiceProgressCallback = Callable[[str, int], None]  # message, percent


class BatteryRegistrationService:
    """
    Battery Registration Service.

    Registers a new battery with the vehicle's power management system.
    This is a safe, user-serviceable operation required after battery replacement.
    """

    SERVICE_NAME = "Battery Registration"
    TARGET_MODULE = "DME"  # Or FRM depending on vehicle

    def __init__(
        self,
        uds_client: UDSClient,
        safety_manager: SafetyManager,
        vehicle_profile: VehicleProfile,
    ) -> None:
        """Initialize battery registration service."""
        self._uds = uds_client
        self._safety = safety_manager
        self._profile = vehicle_profile
        self._state = ServiceState.IDLE
        self._progress_callbacks: list[ServiceProgressCallback] = []
        self._abort_requested = False

    @property
    def state(self) -> ServiceState:
        """Current service state."""
        return self._state

    def add_progress_callback(self, callback: ServiceProgressCallback) -> None:
        """Add callback for progress updates."""
        self._progress_callbacks.append(callback)

    def get_preconditions(self) -> list[Precondition]:
        """Get list of preconditions for this service."""
        return [
            Precondition(
                name="connection",
                description="Diagnostic connection established",
                check_fn=lambda: True,  # Will be checked at execution
                required=True,
            ),
            Precondition(
                name="ignition",
                description="Ignition is ON (engine OFF)",
                check_fn=lambda: True,  # User must confirm
                required=True,
            ),
            Precondition(
                name="voltage",
                description="Battery voltage is stable (>11.5V)",
                check_fn=lambda: True,  # Will attempt to read
                required=False,
            ),
            Precondition(
                name="no_charging",
                description="Battery charger disconnected",
                check_fn=lambda: True,  # User must confirm
                required=True,
            ),
        ]

    def execute(
        self,
        battery_capacity_ah: int = 80,
        battery_type: str = "AGM",
    ) -> ServiceResult:
        """
        Execute battery registration.

        Args:
            battery_capacity_ah: Battery capacity in Ah
            battery_type: Battery type (AGM, EFB, Standard)

        Returns:
            ServiceResult with outcome
        """
        start_time = datetime.now()
        self._state = ServiceState.EXECUTING
        self._abort_requested = False

        log_audit_event(
            "service_started",
            f"Battery registration started: {battery_capacity_ah}Ah {battery_type}",
            {
                "capacity": battery_capacity_ah,
                "type": battery_type,
            },
        )

        try:
            # Step 1: Enter extended session
            self._notify_progress("Entering diagnostic session...", 10)

            response = self._uds.diagnostic_session_control(
                DiagnosticSession.EXTENDED
            )
            if not response.positive:
                return self._fail_result(
                    f"Failed to enter extended session: {response.error_message}"
                )

            if self._abort_requested:
                return self._abort_result()

            # Step 2: Start battery registration routine
            self._notify_progress("Starting battery registration routine...", 30)

            # Build routine data (format varies by ECU)
            # Common format: capacity (2 bytes) + type code (1 byte)
            type_codes = {"AGM": 0x03, "EFB": 0x02, "STANDARD": 0x01}
            type_code = type_codes.get(battery_type.upper(), 0x01)

            routine_data = (
                battery_capacity_ah.to_bytes(2, "big") +
                bytes([type_code])
            )

            try:
                routine_response = self._uds.routine_control(
                    RoutineControlType.START_ROUTINE,
                    BatteryRoutines.REGISTER_BATTERY,
                    routine_data,
                )
            except UDSError as e:
                # Routine might not be supported - try alternative method
                logger.warning(f"Routine control failed: {e}")
                return self._fail_result(
                    "Battery registration routine not supported. "
                    "Your vehicle may require dealer-level tools for this operation."
                )

            if self._abort_requested:
                return self._abort_result()

            # Step 3: Check routine result
            self._notify_progress("Checking registration result...", 70)

            if not routine_response.positive:
                return self._fail_result(
                    f"Registration failed: {routine_response.error_message}"
                )

            # Step 4: Verify registration (optional)
            self._notify_progress("Verifying registration...", 90)

            try:
                verify_response = self._uds.routine_control(
                    RoutineControlType.REQUEST_ROUTINE_RESULTS,
                    BatteryRoutines.REGISTER_BATTERY,
                )
                if verify_response.positive:
                    logger.info("Battery registration verified")
            except Exception:
                pass  # Verification is optional

            # Success
            self._notify_progress("Battery registration complete!", 100)
            self._state = ServiceState.COMPLETE

            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            result = ServiceResult(
                service_name=self.SERVICE_NAME,
                success=True,
                message=f"Battery registered: {battery_capacity_ah}Ah {battery_type}",
                details={
                    "capacity": battery_capacity_ah,
                    "type": battery_type,
                },
                execution_time_ms=execution_time,
            )

            # Record in profile
            self._profile.add_service_record(
                ServiceRecord(
                    service_name=self.SERVICE_NAME,
                    module_id=self.TARGET_MODULE,
                    timestamp=datetime.now(),
                    success=True,
                    details=f"{battery_capacity_ah}Ah {battery_type}",
                    parameters={
                        "capacity": battery_capacity_ah,
                        "type": battery_type,
                    },
                )
            )

            log_diagnostic_action(
                "battery_registration",
                module_id=self.TARGET_MODULE,
                success=True,
                details={
                    "capacity": battery_capacity_ah,
                    "type": battery_type,
                },
            )

            return result

        except Exception as e:
            logger.error(f"Battery registration error: {e}")
            return self._fail_result(str(e))

    def abort(self) -> None:
        """Request service abort."""
        self._abort_requested = True

    def _notify_progress(self, message: str, percent: int) -> None:
        """Notify progress callbacks."""
        logger.info(f"[{percent}%] {message}")
        for callback in self._progress_callbacks:
            try:
                callback(message, percent)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    def _fail_result(self, message: str) -> ServiceResult:
        """Create failure result."""
        self._state = ServiceState.FAILED

        log_diagnostic_action(
            "battery_registration",
            module_id=self.TARGET_MODULE,
            success=False,
            error=message,
        )

        return ServiceResult(
            service_name=self.SERVICE_NAME,
            success=False,
            message=message,
        )

    def _abort_result(self) -> ServiceResult:
        """Create abort result."""
        self._state = ServiceState.ABORTED
        return ServiceResult(
            service_name=self.SERVICE_NAME,
            success=False,
            message="Operation aborted by user",
        )


class ECUResetService:
    """
    ECU Reset Service.

    Performs safe ECU resets. Only soft and key-off/on resets are allowed.
    Hard resets that could brick modules are blocked.
    """

    SERVICE_NAME = "ECU Reset"

    def __init__(
        self,
        uds_client: UDSClient,
        safety_manager: SafetyManager,
        vehicle_profile: VehicleProfile,
    ) -> None:
        """Initialize ECU reset service."""
        self._uds = uds_client
        self._safety = safety_manager
        self._profile = vehicle_profile
        self._state = ServiceState.IDLE

    @property
    def state(self) -> ServiceState:
        """Current service state."""
        return self._state

    def get_allowed_reset_types(self) -> list[tuple[int, str, str]]:
        """Get list of allowed reset types."""
        return [
            (ResetType.SOFT_RESET, "Soft Reset", "Restarts ECU software"),
            (ResetType.KEY_OFF_ON_RESET, "Key Off/On Reset", "Simulates ignition cycle"),
        ]

    def execute(
        self,
        module_id: str,
        module_address: int,
        reset_type: int = ResetType.SOFT_RESET,
    ) -> ServiceResult:
        """
        Execute ECU reset.

        Args:
            module_id: Target module identifier
            module_address: Module diagnostic address
            reset_type: Reset type (only safe types allowed)

        Returns:
            ServiceResult with outcome
        """
        # Safety check
        if not self._safety.check_ecu_reset(reset_type):
            return ServiceResult(
                service_name=self.SERVICE_NAME,
                success=False,
                message=self._safety.get_blocked_message(
                    f"ECU Reset type 0x{reset_type:02X}"
                ),
            )

        self._state = ServiceState.EXECUTING

        log_audit_event(
            "ecu_reset_started",
            f"ECU reset initiated for {module_id}",
            {
                "module": module_id,
                "reset_type": reset_type,
            },
        )

        try:
            self._uds.set_target(module_address)

            # Enter extended session first
            session_response = self._uds.diagnostic_session_control(
                DiagnosticSession.EXTENDED
            )
            if not session_response.positive:
                return ServiceResult(
                    service_name=self.SERVICE_NAME,
                    success=False,
                    message=f"Failed to enter extended session: {session_response.error_message}",
                )

            # Perform reset
            reset_response = self._uds.ecu_reset(reset_type)

            if reset_response.positive:
                self._state = ServiceState.COMPLETE

                self._profile.add_service_record(
                    ServiceRecord(
                        service_name=self.SERVICE_NAME,
                        module_id=module_id,
                        timestamp=datetime.now(),
                        success=True,
                        details=f"Reset type: 0x{reset_type:02X}",
                    )
                )

                return ServiceResult(
                    service_name=self.SERVICE_NAME,
                    success=True,
                    message=f"ECU reset successful for {module_id}",
                    details={"reset_type": reset_type},
                )
            else:
                self._state = ServiceState.FAILED
                return ServiceResult(
                    service_name=self.SERVICE_NAME,
                    success=False,
                    message=f"Reset failed: {reset_response.error_message}",
                )

        except Exception as e:
            self._state = ServiceState.FAILED
            logger.error(f"ECU reset error: {e}")
            return ServiceResult(
                service_name=self.SERVICE_NAME,
                success=False,
                message=str(e),
            )


class ServiceManager:
    """
    Central manager for all service functions.

    Provides access to available services and coordinates execution.
    """

    def __init__(
        self,
        uds_client: UDSClient,
        safety_manager: SafetyManager,
        vehicle_profile: VehicleProfile,
    ) -> None:
        """Initialize service manager."""
        self._uds = uds_client
        self._safety = safety_manager
        self._profile = vehicle_profile

        # Initialize services
        self._battery_service = BatteryRegistrationService(
            uds_client, safety_manager, vehicle_profile
        )
        self._reset_service = ECUResetService(
            uds_client, safety_manager, vehicle_profile
        )

    @property
    def battery_registration(self) -> BatteryRegistrationService:
        """Get battery registration service."""
        return self._battery_service

    @property
    def ecu_reset(self) -> ECUResetService:
        """Get ECU reset service."""
        return self._reset_service

    def get_available_services(self) -> list[dict[str, str]]:
        """Get list of available services."""
        return [
            {
                "id": "battery_registration",
                "name": "Battery Registration",
                "description": "Register a new battery with the vehicle's power management",
                "category": "maintenance",
            },
            {
                "id": "ecu_reset",
                "name": "ECU Reset",
                "description": "Perform a safe reset of an ECU module",
                "category": "maintenance",
            },
        ]
