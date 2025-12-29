"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Simple, clean main window.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QProgressBar
)
from PyQt6.QtGui import QFont, QColor

from e92_pulse.core.connection import ConnectionManager, ConnectionState
from e92_pulse.core.config import AppConfig
from e92_pulse.core.safety import SafetyManager
from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.core.modules import ModuleRegistry
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config

        # Core components
        self._safety_manager = SafetyManager()
        self._vehicle_profile = VehicleProfile()
        self._connection_manager = ConnectionManager(config)
        self._module_registry = ModuleRegistry(config.datapacks_dir)

        self._uds_client = None
        self._module_scanner = None

        self.setWindowTitle("E92 Pulse - BMW Diagnostics")
        self.setMinimumSize(1000, 700)

        self._setup_ui()
        self._apply_style()

        # Auto-scan for interface
        QTimer.singleShot(500, self._scan_interface)

    def _apply_style(self):
        """Apply dark theme."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QPushButton {
                background-color: #0066cc;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0077ee;
            }
            QPushButton:disabled {
                background-color: #444444;
                color: #888888;
            }
            QPushButton#danger {
                background-color: #cc3333;
            }
            QPushButton#danger:hover {
                background-color: #ee4444;
            }
            QTableWidget {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                gridline-color: #444444;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #333333;
                padding: 8px;
                border: none;
            }
            QProgressBar {
                background-color: #333333;
                border: none;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0066cc;
                border-radius: 5px;
            }
        """)

    def _setup_ui(self):
        """Setup the UI."""
        central = QWidget()
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = self._create_sidebar()
        layout.addWidget(sidebar)

        # Main content
        self._content = QStackedWidget()
        layout.addWidget(self._content, 1)

        # Create pages
        self._create_connect_page()
        self._create_scan_page()
        self._create_reset_page()

    def _create_sidebar(self):
        """Create navigation sidebar."""
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("background-color: #252525; border-right: 1px solid #333;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 20, 10, 20)
        layout.setSpacing(10)

        # Title
        title = QLabel("E92 Pulse")
        title.setFont(QFont("Sans", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #00aaff;")
        layout.addWidget(title)

        subtitle = QLabel("BMW E92 M3")
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        layout.addSpacing(30)

        # Nav buttons
        self._nav_buttons = {}

        pages = [
            ("connect", "Connect"),
            ("scan", "Scan Modules"),
            ("reset", "Reset ECUs"),
        ]

        for key, label in pages:
            btn = QPushButton(label)
            btn.setMinimumHeight(45)
            btn.clicked.connect(lambda checked, k=key: self._show_page(k))
            layout.addWidget(btn)
            self._nav_buttons[key] = btn

            if key != "connect":
                btn.setEnabled(False)

        layout.addStretch()

        # Status
        self._status_label = QLabel("Not Connected")
        self._status_label.setStyleSheet("color: #cc0000;")
        layout.addWidget(self._status_label)

        return sidebar

    def _create_connect_page(self):
        """Create connect page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("Connect to Vehicle")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        self._iface_label = QLabel("Scanning...")
        self._iface_label.setFont(QFont("Sans", 16))
        layout.addWidget(self._iface_label)

        btn_layout = QHBoxLayout()

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setMinimumHeight(50)
        self._connect_btn.setMinimumWidth(150)
        self._connect_btn.clicked.connect(self._connect)
        self._connect_btn.setEnabled(False)
        btn_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("danger")
        self._disconnect_btn.setMinimumHeight(50)
        self._disconnect_btn.setMinimumWidth(150)
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._disconnect_btn.setEnabled(False)
        btn_layout.addWidget(self._disconnect_btn)

        rescan_btn = QPushButton("Rescan")
        rescan_btn.setMinimumHeight(50)
        rescan_btn.clicked.connect(self._scan_interface)
        btn_layout.addWidget(rescan_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Instructions
        instructions = QLabel(
            "1. Connect Innomaker USB2CAN to laptop\n"
            "2. Connect DB9 cable to car OBD port\n"
            "3. Turn ignition ON\n"
            "4. Run: sudo ip link set can0 up type can bitrate 500000\n"
            "5. Click Connect"
        )
        instructions.setStyleSheet("color: #888888; font-family: monospace;")
        layout.addWidget(instructions)

        layout.addStretch()

        self._content.addWidget(page)

    def _create_scan_page(self):
        """Create module scan page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("ECU Modules")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        # Scan button
        btn_layout = QHBoxLayout()
        self._scan_btn = QPushButton("Scan All Modules")
        self._scan_btn.setMinimumHeight(50)
        self._scan_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._scan_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Progress
        self._scan_progress = QProgressBar()
        self._scan_progress.setMinimumHeight(30)
        self._scan_progress.hide()
        layout.addWidget(self._scan_progress)

        # Results table
        self._module_table = QTableWidget()
        self._module_table.setColumnCount(4)
        self._module_table.setHorizontalHeaderLabels(["Module", "Address", "Status", "Faults"])
        self._module_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._module_table.setMinimumHeight(400)
        layout.addWidget(self._module_table)

        self._content.addWidget(page)

    def _create_reset_page(self):
        """Create reset page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("Reset ECUs")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        warning = QLabel("Warning: Only reset ECUs if you know what you're doing!")
        warning.setStyleSheet("color: #ffaa00;")
        layout.addWidget(warning)

        # Reset buttons
        btn_layout = QVBoxLayout()

        self._reset_all_btn = QPushButton("Reset All ECUs (Soft Reset)")
        self._reset_all_btn.setObjectName("danger")
        self._reset_all_btn.setMinimumHeight(50)
        self._reset_all_btn.clicked.connect(self._reset_all_ecus)
        btn_layout.addWidget(self._reset_all_btn)

        self._clear_dtc_btn = QPushButton("Clear All Fault Codes")
        self._clear_dtc_btn.setMinimumHeight(50)
        self._clear_dtc_btn.clicked.connect(self._clear_all_dtcs)
        btn_layout.addWidget(self._clear_dtc_btn)

        layout.addLayout(btn_layout)

        # Status
        self._reset_status = QLabel("")
        self._reset_status.setStyleSheet("color: #00cc00;")
        layout.addWidget(self._reset_status)

        layout.addStretch()

        self._content.addWidget(page)

    def _show_page(self, key):
        """Show a page."""
        pages = {"connect": 0, "scan": 1, "reset": 2}
        if key in pages:
            self._content.setCurrentIndex(pages[key])

    def _scan_interface(self):
        """Scan for CAN interface."""
        interfaces = self._connection_manager.discover_interfaces()

        if interfaces:
            iface = interfaces[0]
            self._iface_label.setText(f"Found: {iface.name} (SocketCAN @ 500kbps)")
            self._iface_label.setStyleSheet("color: #00cc00;")
            self._connect_btn.setEnabled(True)
            self._current_interface = iface
        else:
            self._iface_label.setText("No CAN interface found - connect adapter and run setup")
            self._iface_label.setStyleSheet("color: #cc6600;")
            self._connect_btn.setEnabled(False)
            self._current_interface = None

    def _connect(self):
        """Connect to vehicle."""
        if not hasattr(self, '_current_interface') or not self._current_interface:
            return

        self._connect_btn.setEnabled(False)

        if self._connection_manager.connect(self._current_interface):
            self._on_connected()
        else:
            error = self._connection_manager.last_error
            if error:
                QMessageBox.warning(self, "Connection Failed", f"{error.message}\n\n{error.suggestion}")
            self._connect_btn.setEnabled(True)

    def _disconnect(self):
        """Disconnect from vehicle."""
        self._connection_manager.disconnect()
        self._on_disconnected()

    def _on_connected(self):
        """Handle successful connection."""
        self._status_label.setText("Connected")
        self._status_label.setStyleSheet("color: #00cc00;")
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)

        # Enable nav
        for key, btn in self._nav_buttons.items():
            btn.setEnabled(True)

        # Initialize UDS client
        try:
            from e92_pulse.protocols.uds_client import UDSClient
            from e92_pulse.services.module_scanner import ModuleScanner

            transport = self._connection_manager.get_transport()
            self._uds_client = UDSClient(transport, self._safety_manager)
            self._module_scanner = ModuleScanner(
                self._uds_client, self._module_registry, self._safety_manager
            )
        except Exception as e:
            logger.error(f"Failed to init UDS: {e}")

    def _on_disconnected(self):
        """Handle disconnection."""
        self._status_label.setText("Disconnected")
        self._status_label.setStyleSheet("color: #cc0000;")
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)

        # Disable nav except connect
        for key, btn in self._nav_buttons.items():
            if key != "connect":
                btn.setEnabled(False)

        self._show_page("connect")

    def _start_scan(self):
        """Start module scan."""
        if not self._module_scanner:
            QMessageBox.warning(self, "Error", "Not connected to vehicle")
            return

        self._scan_btn.setEnabled(False)
        self._scan_progress.show()
        self._scan_progress.setValue(0)
        self._module_table.setRowCount(0)

        # Run scan
        try:
            modules = self._module_registry.get_all_modules()
            total = len(modules)

            for i, module in enumerate(modules):
                self._scan_progress.setValue(int((i / total) * 100))

                try:
                    result = self._module_scanner.probe_module(module)
                    self._add_module_result(module, result)
                except Exception as e:
                    self._add_module_result(module, {"status": "error", "error": str(e)})

            self._scan_progress.setValue(100)
        except Exception as e:
            QMessageBox.warning(self, "Scan Error", str(e))
        finally:
            self._scan_btn.setEnabled(True)
            QTimer.singleShot(2000, self._scan_progress.hide)

    def _add_module_result(self, module, result):
        """Add module result to table."""
        row = self._module_table.rowCount()
        self._module_table.insertRow(row)

        self._module_table.setItem(row, 0, QTableWidgetItem(module.name))
        self._module_table.setItem(row, 1, QTableWidgetItem(f"0x{module.address:02X}"))

        status = result.get("status", "unknown")
        status_item = QTableWidgetItem(status.upper())
        if status == "ok":
            status_item.setForeground(QColor("#00cc00"))
        elif status == "fault":
            status_item.setForeground(QColor("#ffaa00"))
        else:
            status_item.setForeground(QColor("#cc0000"))
        self._module_table.setItem(row, 2, status_item)

        faults = result.get("fault_count", 0)
        self._module_table.setItem(row, 3, QTableWidgetItem(str(faults)))

    def _reset_all_ecus(self):
        """Reset all ECUs."""
        reply = QMessageBox.question(
            self, "Confirm Reset",
            "This will send soft reset to all ECUs.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if not self._uds_client:
            QMessageBox.warning(self, "Error", "Not connected")
            return

        self._reset_status.setText("Resetting ECUs...")

        try:
            modules = self._module_registry.get_all_modules()
            for module in modules:
                try:
                    self._uds_client.ecu_reset(module.address, reset_type=0x01)
                except Exception:
                    pass

            self._reset_status.setText("Reset complete")
        except Exception as e:
            self._reset_status.setText(f"Error: {e}")
            self._reset_status.setStyleSheet("color: #cc0000;")

    def _clear_all_dtcs(self):
        """Clear all fault codes."""
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "This will clear all fault codes from all ECUs.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if not self._uds_client:
            QMessageBox.warning(self, "Error", "Not connected")
            return

        self._reset_status.setText("Clearing fault codes...")

        try:
            modules = self._module_registry.get_all_modules()
            for module in modules:
                try:
                    self._uds_client.clear_dtcs(module.address)
                except Exception:
                    pass

            self._reset_status.setText("Fault codes cleared")
        except Exception as e:
            self._reset_status.setText(f"Error: {e}")
            self._reset_status.setStyleSheet("color: #cc0000;")

    def closeEvent(self, event):
        """Handle window close."""
        if self._connection_manager.is_connected:
            self._connection_manager.disconnect()
        event.accept()
