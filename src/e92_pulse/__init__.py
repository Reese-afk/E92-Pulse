"""
E92 Pulse - BMW E92 M3 Diagnostic Tool

A production-grade diagnostic GUI tool for BMW E92 M3 using K+DCAN USB cable.
Provides ISTA-style guided workflows for vehicle diagnostics.

SECURITY NOTICE:
This tool explicitly blocks and refuses to implement:
- Immobilizer/key programming
- Security bypass mechanisms
- VIN tampering
- Mileage/odometer changes
- ECU flashing/tuning/coding that can brick modules
- Any theft-adjacent workflows

These restrictions are by design and cannot be circumvented.
"""

__version__ = "0.1.0"
__author__ = "E92 Pulse Contributors"

from e92_pulse.core.safety import SafetyManager

# Initialize global safety manager on import
_safety_manager = SafetyManager()


def get_safety_manager() -> SafetyManager:
    """Get the global safety manager instance."""
    return _safety_manager
