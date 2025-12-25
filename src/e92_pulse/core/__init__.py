"""
E92 Pulse Core Package

Contains core functionality for discovery, connection management,
safety enforcement, vehicle profiles, and logging.
"""

from e92_pulse.core.discovery import PortDiscovery, PortInfo
from e92_pulse.core.connection import ConnectionManager, ConnectionState
from e92_pulse.core.safety import SafetyManager, SafetyViolation
from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.core.app_logging import get_logger, setup_logging
from e92_pulse.core.config import AppConfig, load_config

__all__ = [
    "PortDiscovery",
    "PortInfo",
    "ConnectionManager",
    "ConnectionState",
    "SafetyManager",
    "SafetyViolation",
    "VehicleProfile",
    "get_logger",
    "setup_logging",
    "AppConfig",
    "load_config",
]
