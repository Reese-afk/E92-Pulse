"""
E92 Pulse BMW-Specific Package

Contains BMW E92 M3 specific module definitions, scanning logic,
and service implementations.
"""

from e92_pulse.bmw.module_registry import ModuleRegistry, ModuleDefinition
from e92_pulse.bmw.module_scan import ModuleScanner, ScanResult
from e92_pulse.bmw.services import ServiceManager, BatteryRegistrationService

__all__ = [
    "ModuleRegistry",
    "ModuleDefinition",
    "ModuleScanner",
    "ScanResult",
    "ServiceManager",
    "BatteryRegistrationService",
]
