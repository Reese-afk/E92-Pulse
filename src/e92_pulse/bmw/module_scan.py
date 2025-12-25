"""
Module Scanner

Scans for responding BMW ECU modules and reads their status.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable

from e92_pulse.core.app_logging import get_logger, log_diagnostic_action
from e92_pulse.core.vehicle import ModuleStatus, VehicleProfile
from e92_pulse.bmw.module_registry import ModuleRegistry, ModuleDefinition
from e92_pulse.protocols.uds_client import UDSClient, UDSError
from e92_pulse.protocols.services import (
    DiagnosticSession,
    DTCSubFunction,
    DTCStatusMask,
)

logger = get_logger(__name__)


class ScanState(Enum):
    """Module scan state."""

    IDLE = auto()
    SCANNING = auto()
    COMPLETE = auto()
    ABORTED = auto()
    ERROR = auto()


@dataclass
class ModuleScanResult:
    """Result of scanning a single module."""

    module_id: str
    name: str
    address: int
    responding: bool
    has_faults: bool
    fault_count: int
    variant: str | None = None
    software_version: str | None = None
    error_message: str | None = None
    scan_time_ms: float = 0.0


@dataclass
class ScanResult:
    """Complete scan result."""

    modules: list[ModuleScanResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    total_modules: int = 0
    responding_modules: int = 0
    modules_with_faults: int = 0
    total_faults: int = 0
    aborted: bool = False
    error: str | None = None

    def get_summary(self) -> str:
        """Get a human-readable summary."""
        duration = (
            (self.end_time - self.start_time).total_seconds()
            if self.end_time
            else 0
        )
        return (
            f"Scanned {self.total_modules} modules in {duration:.1f}s: "
            f"{self.responding_modules} responding, "
            f"{self.modules_with_faults} with faults ({self.total_faults} total)"
        )


# Callback types
ScanProgressCallback = Callable[[int, int, str], None]  # current, total, module_name
ScanCompleteCallback = Callable[[ScanResult], None]


class ModuleScanner:
    """
    Scans BMW ECU modules.

    Probes each module in the registry to determine:
    - If module is responding
    - Number of stored DTCs
    - Software variant information
    """

    def __init__(
        self,
        uds_client: UDSClient,
        registry: ModuleRegistry,
        vehicle_profile: VehicleProfile,
    ) -> None:
        """
        Initialize module scanner.

        Args:
            uds_client: UDS client for communication
            registry: Module registry with definitions
            vehicle_profile: Vehicle profile to update
        """
        self._uds = uds_client
        self._registry = registry
        self._profile = vehicle_profile
        self._state = ScanState.IDLE
        self._abort_requested = False
        self._progress_callbacks: list[ScanProgressCallback] = []
        self._complete_callbacks: list[ScanCompleteCallback] = []

    @property
    def state(self) -> ScanState:
        """Current scan state."""
        return self._state

    @property
    def is_scanning(self) -> bool:
        """Check if scan is in progress."""
        return self._state == ScanState.SCANNING

    def add_progress_callback(self, callback: ScanProgressCallback) -> None:
        """Add callback for scan progress updates."""
        self._progress_callbacks.append(callback)

    def add_complete_callback(self, callback: ScanCompleteCallback) -> None:
        """Add callback for scan completion."""
        self._complete_callbacks.append(callback)

    def scan_all(
        self,
        modules: list[ModuleDefinition] | None = None,
    ) -> ScanResult:
        """
        Scan all modules in registry.

        Args:
            modules: Specific modules to scan (default: all)

        Returns:
            ScanResult with all module statuses
        """
        self._state = ScanState.SCANNING
        self._abort_requested = False

        result = ScanResult()
        result.start_time = datetime.now()

        # Get modules to scan
        modules_to_scan = modules or self._registry.get_all_modules()
        result.total_modules = len(modules_to_scan)

        logger.info(f"Starting scan of {result.total_modules} modules")

        for i, module_def in enumerate(modules_to_scan):
            if self._abort_requested:
                result.aborted = True
                break

            # Notify progress
            self._notify_progress(i, result.total_modules, module_def.name)

            # Scan this module
            module_result = self._scan_module(module_def)
            result.modules.append(module_result)

            # Update counters
            if module_result.responding:
                result.responding_modules += 1
                if module_result.has_faults:
                    result.modules_with_faults += 1
                    result.total_faults += module_result.fault_count

            # Update vehicle profile
            self._profile.add_module(
                ModuleStatus(
                    module_id=module_result.module_id,
                    name=module_result.name,
                    address=module_result.address,
                    responding=module_result.responding,
                    has_faults=module_result.has_faults,
                    fault_count=module_result.fault_count,
                    last_scan=datetime.now(),
                    variant=module_result.variant,
                    software_version=module_result.software_version,
                )
            )

        result.end_time = datetime.now()
        self._profile.scan_complete = not result.aborted
        self._profile.last_scan_time = result.end_time

        self._state = (
            ScanState.ABORTED if result.aborted else ScanState.COMPLETE
        )

        log_diagnostic_action(
            "module_scan_complete",
            details={
                "total": result.total_modules,
                "responding": result.responding_modules,
                "with_faults": result.modules_with_faults,
            },
        )

        logger.info(result.get_summary())

        # Notify completion
        self._notify_complete(result)

        return result

    def _scan_module(self, module_def: ModuleDefinition) -> ModuleScanResult:
        """Scan a single module."""
        start_time = datetime.now()

        result = ModuleScanResult(
            module_id=module_def.module_id,
            name=module_def.name,
            address=module_def.address,
            responding=False,
            has_faults=False,
            fault_count=0,
        )

        try:
            # Set target address
            self._uds.set_target(module_def.address)

            # Try to establish session
            response = self._uds.diagnostic_session_control(
                DiagnosticSession.DEFAULT
            )

            if not response.positive:
                result.error_message = f"Session control failed: {response.error_message}"
                return result

            result.responding = True

            # Try extended session for more data
            if module_def.supports_extended_session:
                try:
                    self._uds.diagnostic_session_control(
                        DiagnosticSession.EXTENDED
                    )
                except Exception:
                    pass  # Fall back to default session

            # Read DTC count
            try:
                dtc_response = self._uds.read_dtc_info(
                    DTCSubFunction.REPORT_NUMBER_OF_DTC_BY_STATUS_MASK,
                    bytes([DTCStatusMask.CONFIRMED_DTC | DTCStatusMask.PENDING_DTC]),
                )

                if dtc_response.positive and len(dtc_response.data) >= 4:
                    # Response: StatusAvailabilityMask (1) + DTCFormatIdentifier (1) + DTCCount (2)
                    result.fault_count = int.from_bytes(
                        dtc_response.data[2:4], "big"
                    )
                    result.has_faults = result.fault_count > 0

            except Exception as e:
                logger.debug(f"DTC read failed for {module_def.module_id}: {e}")

            # Try to read software version
            try:
                version_response = self._uds.read_data_by_id(0xF194)  # Software number
                if version_response.positive and version_response.data:
                    # Try to decode as ASCII
                    try:
                        result.software_version = (
                            version_response.data[:20]
                            .decode("ascii", errors="ignore")
                            .strip()
                        )
                    except Exception:
                        result.software_version = version_response.data[:20].hex()

            except Exception:
                pass  # Version read is optional

        except UDSError as e:
            result.error_message = str(e)
        except Exception as e:
            result.error_message = f"Unexpected error: {e}"
            logger.error(f"Scan error for {module_def.module_id}: {e}")

        finally:
            result.scan_time_ms = (
                datetime.now() - start_time
            ).total_seconds() * 1000

        return result

    def scan_single(self, module_id: str) -> ModuleScanResult | None:
        """Scan a single module by ID."""
        module_def = self._registry.get_module(module_id)
        if not module_def:
            return None

        return self._scan_module(module_def)

    def abort(self) -> None:
        """Request scan abort."""
        if self._state == ScanState.SCANNING:
            self._abort_requested = True
            logger.info("Scan abort requested")

    def _notify_progress(self, current: int, total: int, module_name: str) -> None:
        """Notify progress callbacks."""
        for callback in self._progress_callbacks:
            try:
                callback(current, total, module_name)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    def _notify_complete(self, result: ScanResult) -> None:
        """Notify completion callbacks."""
        for callback in self._complete_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.warning(f"Complete callback error: {e}")
