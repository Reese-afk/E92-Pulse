"""
Safety Manager

Enforces hard blocks on dangerous operations that could:
- Enable vehicle theft
- Brick ECU modules
- Tamper with odometer/VIN
- Bypass security systems

All safety violations are logged and blocked at multiple layers.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable

from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class SafetyCategory(Enum):
    """Categories of blocked operations."""

    IMMOBILIZER = auto()  # Key programming, EWS bypass
    SECURITY_BYPASS = auto()  # Security access exploitation
    VIN_TAMPERING = auto()  # VIN modification
    ODOMETER = auto()  # Mileage manipulation
    ECU_FLASH = auto()  # Flashing/coding that can brick modules
    THEFT_ADJACENT = auto()  # Any operation that could aid theft


@dataclass
class SafetyViolation:
    """Record of a blocked operation attempt."""

    timestamp: datetime
    category: SafetyCategory
    operation: str
    details: str
    blocked: bool = True


@dataclass
class SafetyManager:
    """
    Central safety enforcement for all diagnostic operations.

    This manager implements hard blocks on dangerous operations.
    These blocks CANNOT be disabled or bypassed.
    """

    _violations: list[SafetyViolation] = field(default_factory=list)
    _hooks: list[Callable[[SafetyViolation], None]] = field(default_factory=list)

    # UDS Service IDs that are always blocked
    BLOCKED_SERVICES: frozenset[int] = frozenset(
        {
            0x27,  # Security Access (when used for bypass)
            0x2E,  # Write Data By Identifier (for protected IDs)
            0x34,  # Request Download (ECU flashing)
            0x35,  # Request Upload
            0x36,  # Transfer Data
            0x37,  # Request Transfer Exit
            0x38,  # Request File Transfer
        }
    )

    # Data Identifiers (DIDs) that are always blocked for write
    BLOCKED_WRITE_DIDS: frozenset[int] = frozenset(
        {
            0xF190,  # VIN
            0xF191,  # Vehicle Manufacturer ECU Hardware Number
            0x2500,  # Odometer (common BMW DID)
            0x2501,  # Odometer backup
            0x2502,  # Odometer tertiary
        }
    )

    # Routine IDs that are blocked
    BLOCKED_ROUTINES: frozenset[int] = frozenset(
        {
            0x0100,  # Key programming routines
            0x0101,
            0x0102,
            0x0103,
            0x0200,  # Immobilizer routines
            0x0201,
            0x0202,
            0xFF00,  # ECU flash preparation
            0xFF01,
            0xFF02,
        }
    )

    # Keywords in operation names that trigger blocking
    BLOCKED_KEYWORDS: tuple[str, ...] = (
        "immobilizer",
        "immo",
        "ews",
        "key_program",
        "key_learn",
        "security_bypass",
        "security_unlock",
        "vin_write",
        "vin_modify",
        "odometer",
        "mileage",
        "km_write",
        "flash_ecu",
        "flash_write",
        "coding_write",
        "dump_eeprom",
        "eeprom_write",
        "cas_reset",
        "theft",
        "unlock_ecu",
    )

    def check_operation(self, operation: str, details: str = "") -> bool:
        """
        Check if an operation is allowed.

        Args:
            operation: Name/description of the operation
            details: Additional details for logging

        Returns:
            True if operation is allowed, False if blocked

        Note:
            Blocked operations are logged and recorded.
        """
        operation_lower = operation.lower().replace(" ", "_").replace("-", "_")

        # Check against blocked keywords
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in operation_lower:
                self._record_violation(
                    SafetyCategory.THEFT_ADJACENT,
                    operation,
                    f"Operation contains blocked keyword: {keyword}. {details}",
                )
                return False

        return True

    def check_service(self, service_id: int, sub_function: int = 0) -> bool:
        """
        Check if a UDS service is allowed.

        Args:
            service_id: UDS service identifier
            sub_function: Optional sub-function

        Returns:
            True if service is allowed, False if blocked
        """
        if service_id in self.BLOCKED_SERVICES:
            category = self._categorize_service(service_id)
            self._record_violation(
                category,
                f"UDS Service 0x{service_id:02X}",
                f"Service 0x{service_id:02X} (sub: 0x{sub_function:02X}) is blocked for safety",
            )
            return False

        return True

    def check_write_did(self, did: int) -> bool:
        """
        Check if writing to a DID is allowed.

        Args:
            did: Data Identifier to write

        Returns:
            True if write is allowed, False if blocked
        """
        if did in self.BLOCKED_WRITE_DIDS:
            self._record_violation(
                SafetyCategory.VIN_TAMPERING
                if did == 0xF190
                else SafetyCategory.ODOMETER,
                f"Write DID 0x{did:04X}",
                f"Writing to DID 0x{did:04X} is permanently blocked",
            )
            return False

        return True

    def check_routine(self, routine_id: int) -> bool:
        """
        Check if a routine control is allowed.

        Args:
            routine_id: Routine identifier

        Returns:
            True if routine is allowed, False if blocked
        """
        if routine_id in self.BLOCKED_ROUTINES:
            self._record_violation(
                SafetyCategory.IMMOBILIZER,
                f"Routine 0x{routine_id:04X}",
                f"Routine 0x{routine_id:04X} is blocked (security-sensitive)",
            )
            return False

        return True

    def check_ecu_reset(self, reset_type: int) -> bool:
        """
        Check if an ECU reset type is safe.

        Args:
            reset_type: UDS ECU reset sub-function

        Returns:
            True if reset type is safe
        """
        # Only soft reset (0x01) and key off/on reset (0x02) are allowed
        SAFE_RESET_TYPES = {0x01, 0x02, 0x03}

        if reset_type not in SAFE_RESET_TYPES:
            self._record_violation(
                SafetyCategory.ECU_FLASH,
                f"ECU Reset type 0x{reset_type:02X}",
                "Only soft reset, key off/on reset, and hard reset are allowed",
            )
            return False

        return True

    def get_violations(self) -> list[SafetyViolation]:
        """Get all recorded safety violations."""
        return self._violations.copy()

    def add_violation_hook(self, hook: Callable[[SafetyViolation], None]) -> None:
        """Add a callback for safety violations."""
        self._hooks.append(hook)

    def _record_violation(
        self, category: SafetyCategory, operation: str, details: str
    ) -> None:
        """Record a safety violation."""
        violation = SafetyViolation(
            timestamp=datetime.now(),
            category=category,
            operation=operation,
            details=details,
            blocked=True,
        )
        self._violations.append(violation)

        # Log the violation
        logger.warning(
            f"SAFETY BLOCK: {category.name} - {operation}",
            extra={
                "category": category.name,
                "operation": operation,
                "details": details,
            },
        )

        # Notify hooks
        for hook in self._hooks:
            try:
                hook(violation)
            except Exception as e:
                logger.error(f"Safety hook error: {e}")

    def _categorize_service(self, service_id: int) -> SafetyCategory:
        """Determine the safety category for a blocked service."""
        if service_id == 0x27:
            return SafetyCategory.SECURITY_BYPASS
        elif service_id in {0x34, 0x35, 0x36, 0x37, 0x38}:
            return SafetyCategory.ECU_FLASH
        else:
            return SafetyCategory.THEFT_ADJACENT

    def get_blocked_message(self, operation: str) -> str:
        """
        Get a user-friendly message explaining why an operation is blocked.

        Args:
            operation: The blocked operation

        Returns:
            Explanation message for the UI
        """
        return (
            f"Operation '{operation}' is blocked for safety reasons.\n\n"
            "E92 Pulse explicitly prohibits:\n"
            "- Immobilizer/key programming\n"
            "- Security bypass mechanisms\n"
            "- VIN tampering\n"
            "- Odometer/mileage changes\n"
            "- ECU flashing that can brick modules\n\n"
            "These restrictions protect you and your vehicle."
        )
