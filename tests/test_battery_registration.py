"""
Tests for battery registration wizard logic.
"""

import pytest
from e92_pulse.bmw.services import (
    BatteryRegistrationService,
    ServiceResult,
    ServiceState,
    Precondition,
)
from e92_pulse.protocols.uds_client import UDSClient
from e92_pulse.core.safety import SafetyManager
from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.transport.mock_transport import MockTransport
from e92_pulse.sim.mock_ecus import MockECUManager, SimulationConfig


class TestBatteryRegistrationService:
    """Tests for BatteryRegistrationService class."""

    @pytest.fixture
    def battery_service(
        self, uds_client: UDSClient, safety_manager: SafetyManager, vehicle_profile: VehicleProfile
    ) -> BatteryRegistrationService:
        """Create battery registration service."""
        return BatteryRegistrationService(uds_client, safety_manager, vehicle_profile)

    def test_service_creation(self, battery_service: BatteryRegistrationService):
        """Test service initialization."""
        assert battery_service is not None
        assert battery_service.state == ServiceState.IDLE

    def test_service_name(self, battery_service: BatteryRegistrationService):
        """Test service name is correct."""
        assert battery_service.SERVICE_NAME == "Battery Registration"

    def test_get_preconditions(self, battery_service: BatteryRegistrationService):
        """Test getting preconditions list."""
        preconditions = battery_service.get_preconditions()

        assert len(preconditions) >= 3
        assert all(isinstance(p, Precondition) for p in preconditions)

        # Check required preconditions
        names = [p.name for p in preconditions]
        assert "connection" in names
        assert "ignition" in names

    def test_precondition_check(self):
        """Test precondition checking."""
        precondition = Precondition(
            name="test",
            description="Test precondition",
            check_fn=lambda: True,
            required=True,
        )

        assert precondition.check() is True
        assert precondition.met is True

    def test_precondition_failure(self):
        """Test precondition failure."""
        precondition = Precondition(
            name="test",
            description="Test precondition",
            check_fn=lambda: False,
            required=True,
        )

        assert precondition.check() is False
        assert precondition.met is False

    def test_execute_success(
        self, connected_mock_transport: MockTransport, safety_manager: SafetyManager
    ):
        """Test successful battery registration execution."""
        # Create mock ECU manager with success config
        config = SimulationConfig()
        config.battery_registration_succeeds = True
        config.modules_responding = ["DME"]
        mock_manager = MockECUManager(config)

        # Connect mock ECUs to transport
        connected_mock_transport.connect_mock_ecu(mock_manager)

        # Create UDS client
        uds = UDSClient(connected_mock_transport, safety_manager)
        uds.set_target(0x12)  # DME address

        # Create service
        profile = VehicleProfile()
        service = BatteryRegistrationService(uds, safety_manager, profile)

        # Execute
        result = service.execute(battery_capacity_ah=80, battery_type="AGM")

        assert result.success is True
        assert service.state == ServiceState.COMPLETE
        assert "80" in result.message or "AGM" in result.message

    def test_execute_failure(
        self, connected_mock_transport: MockTransport, safety_manager: SafetyManager
    ):
        """Test failed battery registration execution."""
        # Create mock ECU manager with failure config
        config = SimulationConfig()
        config.battery_registration_succeeds = False
        config.modules_responding = ["DME"]
        mock_manager = MockECUManager(config)

        connected_mock_transport.connect_mock_ecu(mock_manager)

        uds = UDSClient(connected_mock_transport, safety_manager)
        uds.set_target(0x12)

        profile = VehicleProfile()
        service = BatteryRegistrationService(uds, safety_manager, profile)

        result = service.execute(battery_capacity_ah=80, battery_type="AGM")

        assert result.success is False
        assert service.state == ServiceState.FAILED

    def test_service_record_created(
        self, connected_mock_transport: MockTransport, safety_manager: SafetyManager
    ):
        """Test service record is created on success."""
        config = SimulationConfig()
        config.battery_registration_succeeds = True
        config.modules_responding = ["DME"]
        mock_manager = MockECUManager(config)

        connected_mock_transport.connect_mock_ecu(mock_manager)

        uds = UDSClient(connected_mock_transport, safety_manager)
        uds.set_target(0x12)

        profile = VehicleProfile()
        service = BatteryRegistrationService(uds, safety_manager, profile)

        result = service.execute(battery_capacity_ah=90, battery_type="EFB")

        assert result.success is True
        assert len(profile.service_history) == 1

        record = profile.service_history[0]
        assert record.service_name == "Battery Registration"
        assert record.success is True

    def test_progress_callback(
        self, connected_mock_transport: MockTransport, safety_manager: SafetyManager
    ):
        """Test progress callbacks are called."""
        config = SimulationConfig()
        config.battery_registration_succeeds = True
        config.modules_responding = ["DME"]
        mock_manager = MockECUManager(config)

        connected_mock_transport.connect_mock_ecu(mock_manager)

        uds = UDSClient(connected_mock_transport, safety_manager)
        uds.set_target(0x12)

        profile = VehicleProfile()
        service = BatteryRegistrationService(uds, safety_manager, profile)

        progress_messages = []

        def on_progress(message: str, percent: int):
            progress_messages.append((message, percent))

        service.add_progress_callback(on_progress)
        service.execute(battery_capacity_ah=80, battery_type="AGM")

        assert len(progress_messages) > 0
        # Should have progress updates
        percentages = [p[1] for p in progress_messages]
        assert 0 in percentages or 10 in percentages  # Should start low
        assert 100 in percentages  # Should complete


class TestServiceResult:
    """Tests for ServiceResult class."""

    def test_success_result(self):
        """Test creating success result."""
        result = ServiceResult(
            service_name="Test",
            success=True,
            message="Operation completed",
            details={"key": "value"},
        )

        assert result.success is True
        assert "completed" in result.message

    def test_failure_result(self):
        """Test creating failure result."""
        result = ServiceResult(
            service_name="Test",
            success=False,
            message="Operation failed",
        )

        assert result.success is False
        assert "failed" in result.message

    def test_result_has_timestamp(self):
        """Test result has timestamp."""
        result = ServiceResult(
            service_name="Test",
            success=True,
            message="Done",
        )

        assert result.timestamp is not None
