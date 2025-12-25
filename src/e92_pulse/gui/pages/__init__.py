"""
E92 Pulse GUI Pages

Contains the main content pages for the application.
"""

from e92_pulse.gui.pages.connect_page import ConnectPage
from e92_pulse.gui.pages.quick_test_page import QuickTestPage
from e92_pulse.gui.pages.fault_memory_page import FaultMemoryPage
from e92_pulse.gui.pages.services_page import ServicesPage
from e92_pulse.gui.pages.export_page import ExportPage

__all__ = [
    "ConnectPage",
    "QuickTestPage",
    "FaultMemoryPage",
    "ServicesPage",
    "ExportPage",
]
