"""
Pytest configuration and fixtures for E92 Pulse tests.
"""

import pytest
from pathlib import Path
from typing import Generator

from e92_pulse.core.config import AppConfig
from e92_pulse.core.safety import SafetyManager
from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.transport.mock_transport import MockTransport
from e92_pulse.protocols.uds_client import UDSClient
from e92_pulse.bmw.module_registry import ModuleRegistry
from e92_pulse.sim.mock_ecus import MockECUManager, SimulationConfig


@pytest.fixture
def app_config() -> AppConfig:
    """Create test application configuration."""
    config = AppConfig()
    config.simulation_mode = True
    return config


@pytest.fixture
def safety_manager() -> SafetyManager:
    """Create test safety manager."""
    return SafetyManager()


@pytest.fixture
def vehicle_profile() -> VehicleProfile:
    """Create test vehicle profile."""
    return VehicleProfile()


@pytest.fixture
def mock_transport() -> MockTransport:
    """Create mock transport."""
    return MockTransport()


@pytest.fixture
def simulation_config() -> SimulationConfig:
    """Create simulation configuration."""
    return SimulationConfig()


@pytest.fixture
def mock_ecu_manager(simulation_config: SimulationConfig) -> MockECUManager:
    """Create mock ECU manager."""
    return MockECUManager(simulation_config)


@pytest.fixture
def connected_mock_transport(
    mock_transport: MockTransport, mock_ecu_manager: MockECUManager
) -> MockTransport:
    """Create mock transport connected to mock ECUs."""
    mock_transport.open("/dev/mock", 115200)
    mock_transport.connect_mock_ecu(mock_ecu_manager)
    return mock_transport


@pytest.fixture
def uds_client(
    connected_mock_transport: MockTransport, safety_manager: SafetyManager
) -> UDSClient:
    """Create UDS client with mock transport."""
    return UDSClient(connected_mock_transport, safety_manager)


@pytest.fixture
def module_registry() -> ModuleRegistry:
    """Create module registry."""
    return ModuleRegistry()


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create temporary directory for test files."""
    return tmp_path
