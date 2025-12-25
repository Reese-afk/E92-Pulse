"""
Tests for safety manager blocks.
"""

import pytest
from e92_pulse.core.safety import SafetyManager, SafetyCategory, SafetyViolation


class TestSafetyManager:
    """Tests for SafetyManager class."""

    def test_safety_manager_creation(self, safety_manager: SafetyManager):
        """Test safety manager initialization."""
        assert safety_manager is not None
        assert len(safety_manager._violations) == 0

    def test_blocked_services(self, safety_manager: SafetyManager):
        """Test that dangerous services are blocked."""
        # Security Access should be blocked
        assert not safety_manager.check_service(0x27)

        # Request Download should be blocked
        assert not safety_manager.check_service(0x34)

        # Transfer Data should be blocked
        assert not safety_manager.check_service(0x36)

    def test_allowed_services(self, safety_manager: SafetyManager):
        """Test that safe services are allowed."""
        # Read Data By ID should be allowed
        assert safety_manager.check_service(0x22)

        # Diagnostic Session Control should be allowed
        assert safety_manager.check_service(0x10)

        # Read DTC Info should be allowed
        assert safety_manager.check_service(0x19)

        # Clear DTC Info should be allowed
        assert safety_manager.check_service(0x14)

    def test_blocked_write_dids(self, safety_manager: SafetyManager):
        """Test that protected DIDs are blocked for write."""
        # VIN should be blocked
        assert not safety_manager.check_write_did(0xF190)

        # Odometer should be blocked
        assert not safety_manager.check_write_did(0x2500)
        assert not safety_manager.check_write_did(0x2501)

    def test_allowed_write_dids(self, safety_manager: SafetyManager):
        """Test that safe DIDs are allowed for write."""
        # General purpose DIDs should be allowed
        assert safety_manager.check_write_did(0x1234)

    def test_blocked_routines(self, safety_manager: SafetyManager):
        """Test that dangerous routines are blocked."""
        # Key programming routines
        assert not safety_manager.check_routine(0x0100)
        assert not safety_manager.check_routine(0x0101)

        # Immobilizer routines
        assert not safety_manager.check_routine(0x0200)

        # ECU flash preparation
        assert not safety_manager.check_routine(0xFF00)

    def test_allowed_routines(self, safety_manager: SafetyManager):
        """Test that safe routines are allowed."""
        # Battery registration
        assert safety_manager.check_routine(0x0300)

        # General purpose routines
        assert safety_manager.check_routine(0x1234)

    def test_blocked_ecu_reset_types(self, safety_manager: SafetyManager):
        """Test that dangerous reset types are blocked."""
        # Only types 0x01, 0x02, 0x03 should be allowed
        assert not safety_manager.check_ecu_reset(0x04)
        assert not safety_manager.check_ecu_reset(0x60)
        assert not safety_manager.check_ecu_reset(0xFF)

    def test_allowed_ecu_reset_types(self, safety_manager: SafetyManager):
        """Test that safe reset types are allowed."""
        assert safety_manager.check_ecu_reset(0x01)  # Hard reset
        assert safety_manager.check_ecu_reset(0x02)  # Key off/on
        assert safety_manager.check_ecu_reset(0x03)  # Soft reset

    def test_blocked_operations_by_keyword(self, safety_manager: SafetyManager):
        """Test that operations with dangerous keywords are blocked."""
        dangerous_operations = [
            "immobilizer_bypass",
            "ews_reset",
            "key_programming",
            "vin_write",
            "odometer_reset",
            "mileage_correction",
            "flash_ecu",
            "eeprom_dump",
            "security_unlock",
            "theft_mode",
        ]

        for op in dangerous_operations:
            assert not safety_manager.check_operation(op), f"{op} should be blocked"

    def test_allowed_operations(self, safety_manager: SafetyManager):
        """Test that safe operations are allowed."""
        safe_operations = [
            "read_dtc",
            "clear_dtc",
            "battery_registration",
            "reset_adaptation",
            "read_live_data",
            "module_scan",
        ]

        for op in safe_operations:
            assert safety_manager.check_operation(op), f"{op} should be allowed"

    def test_violation_recording(self, safety_manager: SafetyManager):
        """Test that violations are recorded."""
        # Trigger a violation
        safety_manager.check_service(0x27)

        violations = safety_manager.get_violations()
        assert len(violations) == 1
        assert violations[0].category == SafetyCategory.SECURITY_BYPASS
        assert violations[0].blocked is True

    def test_violation_hook(self, safety_manager: SafetyManager):
        """Test violation hook callback."""
        hook_called = False
        received_violation = None

        def hook(violation: SafetyViolation):
            nonlocal hook_called, received_violation
            hook_called = True
            received_violation = violation

        safety_manager.add_violation_hook(hook)
        safety_manager.check_service(0x34)  # Trigger violation

        assert hook_called
        assert received_violation is not None
        assert received_violation.category == SafetyCategory.ECU_FLASH

    def test_get_blocked_message(self, safety_manager: SafetyManager):
        """Test blocked message generation."""
        message = safety_manager.get_blocked_message("Test Operation")

        assert "Test Operation" in message
        assert "blocked" in message.lower()
        assert "immobilizer" in message.lower()
        assert "vin" in message.lower()


class TestSafetyViolation:
    """Tests for SafetyViolation dataclass."""

    def test_violation_creation(self):
        """Test creating a safety violation."""
        from datetime import datetime

        violation = SafetyViolation(
            timestamp=datetime.now(),
            category=SafetyCategory.VIN_TAMPERING,
            operation="vin_write",
            details="Attempted VIN modification",
            blocked=True,
        )

        assert violation.category == SafetyCategory.VIN_TAMPERING
        assert violation.blocked is True


class TestSafetyCategory:
    """Tests for SafetyCategory enumeration."""

    def test_all_categories_defined(self):
        """Test all safety categories are defined."""
        categories = [
            SafetyCategory.IMMOBILIZER,
            SafetyCategory.SECURITY_BYPASS,
            SafetyCategory.VIN_TAMPERING,
            SafetyCategory.ODOMETER,
            SafetyCategory.ECU_FLASH,
            SafetyCategory.THEFT_ADJACENT,
        ]

        assert len(categories) == 6
