"""
Tests for mock ECU DTC read/clear flows.
"""

import pytest
from e92_pulse.sim.mock_ecus import MockECU, MockECUManager, MockDTC, SimulationConfig
from e92_pulse.protocols.services import (
    UDSServices,
    DiagnosticSession,
    DTCSubFunction,
    DTCStatusMask,
    RoutineControlType,
    BatteryRoutines,
)


class TestMockECU:
    """Tests for MockECU class."""

    def test_mock_ecu_creation(self):
        """Test creating a mock ECU."""
        ecu = MockECU("DME", 0x12)
        assert ecu.module_id == "DME"
        assert ecu.address == 0x12

    def test_session_control_default(self):
        """Test entering default session."""
        ecu = MockECU("DME", 0x12)

        # Request: 0x10 0x01 (DiagnosticSessionControl, Default)
        request = bytes([0x10, 0x01])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x50  # Positive response
        assert response[1] == 0x01  # Default session

    def test_session_control_extended(self):
        """Test entering extended session."""
        ecu = MockECU("DME", 0x12)

        request = bytes([0x10, 0x03])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x50
        assert response[1] == 0x03  # Extended session

    def test_tester_present(self):
        """Test tester present response."""
        ecu = MockECU("DME", 0x12)

        request = bytes([0x3E, 0x00])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x7E  # Positive response

    def test_tester_present_suppress(self):
        """Test tester present with suppress response."""
        ecu = MockECU("DME", 0x12)

        request = bytes([0x3E, 0x80])  # Suppress positive response
        response = ecu.process_request(request)

        assert response == b""  # No response

    def test_read_dtc_count(self):
        """Test reading DTC count."""
        config = SimulationConfig()
        config.module_dtcs["TEST"] = [
            MockDTC(0x010100, DTCStatusMask.CONFIRMED_DTC, "Test DTC 1"),
            MockDTC(0x020200, DTCStatusMask.PENDING_DTC, "Test DTC 2"),
        ]
        ecu = MockECU("TEST", 0x99, config)

        # Read DTC count with status mask
        request = bytes([0x19, 0x01, 0xFF])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x59  # Positive response
        # Response structure: [0x59, SubFunc, StatusMask, FormatID, CountHigh, CountLow]
        # Count should be 2 (at bytes 4:6)
        count = int.from_bytes(response[4:6], "big")
        assert count == 2

    def test_read_dtc_by_status(self):
        """Test reading DTCs by status mask."""
        config = SimulationConfig()
        config.module_dtcs["TEST"] = [
            MockDTC(0x010100, DTCStatusMask.CONFIRMED_DTC, "Test DTC"),
        ]
        ecu = MockECU("TEST", 0x99, config)

        request = bytes([0x19, 0x02, 0xFF])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x59
        # Should contain DTC data
        assert len(response) > 2

    def test_clear_dtc(self):
        """Test clearing DTCs."""
        config = SimulationConfig()
        config.module_dtcs["TEST"] = [
            MockDTC(0x010100, DTCStatusMask.CONFIRMED_DTC, "Test DTC"),
        ]
        ecu = MockECU("TEST", 0x99, config)

        # First verify DTC exists
        assert len(ecu._dtcs) == 1

        # Clear DTCs
        request = bytes([0x14, 0xFF, 0xFF, 0xFF])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x54  # Positive response
        assert len(ecu._dtcs) == 0

    def test_read_vin(self):
        """Test reading VIN."""
        ecu = MockECU("DME", 0x12)

        # Read Data By ID for VIN (0xF190)
        request = bytes([0x22, 0xF1, 0x90])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x62  # Positive response
        assert response[1:3] == bytes([0xF1, 0x90])  # Echo DID
        # VIN data follows
        assert len(response) > 3

    def test_battery_registration_routine(self):
        """Test battery registration routine."""
        ecu = MockECU("DME", 0x12)

        # Start battery registration routine
        request = bytes([
            0x31,  # Routine Control
            RoutineControlType.START_ROUTINE,
            0x03, 0x00,  # Battery registration routine ID
            0x00, 0x50,  # 80 Ah
            0x03,  # AGM type
        ])
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x71  # Positive response

    def test_ecu_reset_soft(self):
        """Test soft ECU reset."""
        ecu = MockECU("DME", 0x12)

        request = bytes([0x11, 0x03])  # Soft reset
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x51  # Positive response
        assert response[1] == 0x03

    def test_unsupported_service(self):
        """Test unsupported service returns negative response."""
        ecu = MockECU("DME", 0x12)

        request = bytes([0xFF])  # Unsupported service
        response = ecu.process_request(request)

        assert response is not None
        assert response[0] == 0x7F  # Negative response
        assert response[2] == 0x11  # Service not supported


class TestMockECUManager:
    """Tests for MockECUManager class."""

    def test_manager_creation(self):
        """Test creating ECU manager."""
        manager = MockECUManager()
        assert manager is not None

    def test_default_ecus_created(self):
        """Test default ECUs are created from config."""
        config = SimulationConfig()
        config.modules_responding = ["DME", "DSC"]
        manager = MockECUManager(config)

        addresses = manager.get_all_addresses()
        assert len(addresses) == 2

    def test_set_target_and_process(self):
        """Test setting target and processing request."""
        config = SimulationConfig()
        config.modules_responding = ["DME"]
        manager = MockECUManager(config)

        # Get DME address
        manager.set_target(0x12)

        request = bytes([0x10, 0x01])
        response = manager.process_request(request)

        assert response is not None
        assert response[0] == 0x50

    def test_no_response_from_unknown_address(self):
        """Test no response from unknown ECU address."""
        manager = MockECUManager()

        manager.set_target(0xFF)  # Unknown address
        response = manager.process_request(bytes([0x10, 0x01]))

        assert response is None

    def test_add_dtc(self):
        """Test adding DTC to mock ECU."""
        config = SimulationConfig()
        config.modules_responding = ["DME"]
        manager = MockECUManager(config)

        success = manager.add_dtc(
            "DME",
            MockDTC(0x123456, DTCStatusMask.CONFIRMED_DTC, "Test"),
        )

        assert success is True

        # Verify DTC was added
        ecu = manager.get_ecu(0x12)
        assert ecu is not None
        assert len(ecu._dtcs) > 0

    def test_clear_all_dtcs(self):
        """Test clearing all DTCs across ECUs."""
        config = SimulationConfig()
        config.modules_responding = ["DME", "DSC"]
        manager = MockECUManager(config)

        # Add DTCs
        manager.add_dtc("DME", MockDTC(0x111111, 0x08, "Test 1"))
        manager.add_dtc("DSC", MockDTC(0x222222, 0x08, "Test 2"))

        manager.clear_all_dtcs()

        # Verify all cleared
        for address in manager.get_all_addresses():
            ecu = manager.get_ecu(address)
            assert len(ecu._dtcs) == 0


class TestSimulationConfig:
    """Tests for SimulationConfig class."""

    def test_default_config(self):
        """Test default configuration."""
        config = SimulationConfig()

        assert config.response_delay_min >= 0
        assert config.response_delay_max >= config.response_delay_min
        assert len(config.modules_responding) > 0
        assert config.battery_registration_succeeds is True

    def test_custom_modules(self):
        """Test custom module configuration."""
        config = SimulationConfig()
        config.modules_responding = ["DME", "KOMBI"]

        assert len(config.modules_responding) == 2
        assert "DME" in config.modules_responding
        assert "KOMBI" in config.modules_responding

    def test_custom_dtcs(self):
        """Test custom DTC configuration."""
        config = SimulationConfig()
        config.module_dtcs = {
            "DME": [MockDTC(0x010100, 0x08, "Custom DTC")],
        }

        assert "DME" in config.module_dtcs
        assert len(config.module_dtcs["DME"]) == 1
