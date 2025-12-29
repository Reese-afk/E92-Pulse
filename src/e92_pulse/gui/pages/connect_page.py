"""
Connect Page

Provides interface for connecting to the diagnostic interface.
Handles CAN interface discovery, selection, and connection management.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QGroupBox,
    QTextEdit,
    QMessageBox,
)
from PyQt6.QtGui import QFont

from e92_pulse.core.connection import ConnectionManager, ConnectionState, InterfaceInfo
from e92_pulse.core.config import AppConfig
from e92_pulse.core.app_logging import get_logger
from e92_pulse.transport.can_transport import (
    detect_usb_can_adapters,
    get_interface_status,
)

logger = get_logger(__name__)


class ConnectPage(QWidget):
    """
    Connection management page.

    Provides:
    - CAN interface discovery and selection
    - Connect/disconnect controls
    - Connection status display
    - Hardware requirements information
    """

    connection_established = pyqtSignal()
    connection_closed = pyqtSignal()

    def __init__(
        self,
        connection_manager: ConnectionManager,
        config: AppConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._connection_manager = connection_manager
        self._config = config
        self._interfaces: list[InterfaceInfo] = []

        self._setup_ui()
        self._connect_signals()

        # Initial interface scan
        QTimer.singleShot(100, self._scan_interfaces)

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Connect to Vehicle")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "Select a SocketCAN interface to begin diagnostics"
        )
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Main content
        content_layout = QHBoxLayout()
        content_layout.setSpacing(30)

        # Left side - Connection controls
        left_frame = QFrame()
        left_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        left_layout = QVBoxLayout(left_frame)

        # Interface selection
        iface_group = QGroupBox("CAN Interface")
        iface_layout = QVBoxLayout(iface_group)

        # USB Adapter detection status
        self._adapter_status = QLabel("Checking for USB CAN adapters...")
        self._adapter_status.setStyleSheet("color: #888888; font-size: 11px;")
        self._adapter_status.setWordWrap(True)
        iface_layout.addWidget(self._adapter_status)

        iface_row = QHBoxLayout()
        self._interface_combo = QComboBox()
        self._interface_combo.setMinimumWidth(300)
        self._interface_combo.setPlaceholderText("Select interface...")
        iface_row.addWidget(self._interface_combo, 1)

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setFixedWidth(80)
        self._rescan_btn.clicked.connect(self._scan_interfaces)
        iface_row.addWidget(self._rescan_btn)

        iface_layout.addLayout(iface_row)

        # Interface details
        self._iface_details = QLabel("No interface selected")
        self._iface_details.setStyleSheet("color: #888888; font-size: 11px;")
        self._iface_details.setWordWrap(True)
        iface_layout.addWidget(self._iface_details)

        # Test adapter button
        self._test_btn = QPushButton("Test Adapter")
        self._test_btn.setStyleSheet("""
            QPushButton {
                background-color: #336699;
            }
            QPushButton:hover {
                background-color: #4477aa;
            }
        """)
        self._test_btn.clicked.connect(self._on_test_adapter)
        self._test_btn.setEnabled(False)
        iface_layout.addWidget(self._test_btn)

        left_layout.addWidget(iface_group)

        # Connection status
        status_group = QGroupBox("Connection Status")
        status_layout = QVBoxLayout(status_group)

        self._status_label = QLabel("Disconnected")
        self._status_label.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self._status_label)

        self._status_detail = QLabel("")
        self._status_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_detail.setStyleSheet("color: #888888;")
        status_layout.addWidget(self._status_detail)

        left_layout.addWidget(status_group)

        # Connect/Disconnect buttons
        btn_layout = QHBoxLayout()

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setMinimumHeight(50)
        self._connect_btn.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._connect_btn.setEnabled(False)  # Disabled until interface found
        btn_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setMinimumHeight(50)
        self._disconnect_btn.setFont(QFont("Sans", 12))
        self._disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc3333;
            }
            QPushButton:hover {
                background-color: #dd4444;
            }
        """)
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_layout.addWidget(self._disconnect_btn)

        left_layout.addLayout(btn_layout)
        left_layout.addStretch()

        content_layout.addWidget(left_frame)

        # Right side - Information
        right_frame = QFrame()
        right_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        right_layout = QVBoxLayout(right_frame)

        # Requirements
        req_group = QGroupBox("Requirements")
        req_layout = QVBoxLayout(req_group)

        requirements = [
            "SocketCAN-compatible CAN adapter",
            "  (PEAK PCAN-USB, Kvaser, CANable, etc.)",
            "Vehicle ignition ON (engine OFF)",
            "CAN interface configured at 500kbps",
            "Stable 12V battery",
        ]

        for req in requirements:
            req_label = QLabel(f"  {req}")
            req_label.setStyleSheet("color: #cccccc;")
            req_layout.addWidget(req_label)

        right_layout.addWidget(req_group)

        # Troubleshooting
        trouble_group = QGroupBox("Troubleshooting")
        trouble_layout = QVBoxLayout(trouble_group)

        self._trouble_text = QTextEdit()
        self._trouble_text.setReadOnly(True)
        self._trouble_text.setMaximumHeight(150)
        self._trouble_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: none;
                font-family: monospace;
                font-size: 11px;
            }
        """)
        self._trouble_text.setHtml("""
            <p style="color: #888888;">
            <b>No CAN interfaces detected?</b><br>
            - Connect your SocketCAN adapter<br>
            - Set up interface with:<br>
            <code style="color: #00cccc;">sudo ip link set can0 up type can bitrate 500000</code><br><br>
            <b>Connection fails?</b><br>
            - Ensure ignition is ON<br>
            - Verify CAN adapter is recognized (dmesg)<br>
            - Check can-utils: <code style="color: #00cccc;">candump can0</code>
            </p>
        """)
        trouble_layout.addWidget(self._trouble_text)

        right_layout.addWidget(trouble_group)
        right_layout.addStretch()

        content_layout.addWidget(right_frame)

        layout.addLayout(content_layout, 1)

        # Warning banner
        warning_frame = QFrame()
        warning_frame.setStyleSheet("""
            QFrame {
                background-color: #664400;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        warning_layout = QHBoxLayout(warning_frame)

        warning_icon = QLabel("")
        warning_icon.setFont(QFont("Sans", 16))
        warning_layout.addWidget(warning_icon)

        warning_text = QLabel(
            "<b>Important:</b> This tool does NOT support immobilizer, "
            "key programming, VIN changes, or ECU flashing. "
            "These operations are blocked for safety."
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text, 1)

        layout.addWidget(warning_frame)

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        self._interface_combo.currentIndexChanged.connect(self._on_interface_selected)
        self._connection_manager.add_state_callback(self._on_state_change)

    def _scan_interfaces(self) -> None:
        """Scan for available CAN interfaces."""
        self._interface_combo.clear()

        # First check for USB CAN adapters (even if not configured)
        usb_adapters = detect_usb_can_adapters()
        if usb_adapters:
            adapter_names = [a.get("name", "Unknown") for a in usb_adapters]
            self._adapter_status.setText(
                f"USB CAN adapter detected: {', '.join(adapter_names)}"
            )
            self._adapter_status.setStyleSheet("color: #00cc00; font-size: 11px;")
        else:
            self._adapter_status.setText(
                "No USB CAN adapter detected. Connect your Innomaker USB2CAN."
            )
            self._adapter_status.setStyleSheet("color: #cc6600; font-size: 11px;")

        # Now check for configured SocketCAN interfaces
        self._interfaces = self._connection_manager.discover_interfaces()

        if not self._interfaces:
            self._interface_combo.addItem("No CAN interfaces detected")
            self._interface_combo.setEnabled(False)
            self._connect_btn.setEnabled(False)
            self._test_btn.setEnabled(False)

            if usb_adapters:
                self._iface_details.setText(
                    "USB adapter found but interface not configured.\n"
                    "Run: sudo ip link set can0 up type can bitrate 500000"
                )
            else:
                self._iface_details.setText(
                    "No SocketCAN interfaces found.\n"
                    "Connect a CAN adapter and configure it."
                )
        else:
            self._interface_combo.setEnabled(True)
            self._connect_btn.setEnabled(True)
            self._test_btn.setEnabled(True)

            for iface in self._interfaces:
                if iface.interface_type == "virtual":
                    display = f"{iface.name} - Virtual CAN (Testing)"
                else:
                    display = f"{iface.name} - CAN Interface @ 500kbps"
                self._interface_combo.addItem(display)

            # Select first interface
            self._interface_combo.setCurrentIndex(0)
            self._on_interface_selected(0)

        logger.info(f"Interface scan: {len(self._interfaces)} CAN interface(s) found")

    def _on_interface_selected(self, index: int) -> None:
        """Handle interface selection change."""
        if index < 0 or index >= len(self._interfaces):
            return

        iface = self._interfaces[index]
        if iface.interface_type == "virtual":
            details = "Virtual CAN interface for testing\nUse can-utils to inject messages"
        else:
            details = (
                f"Type: SocketCAN\n"
                f"Bitrate: {iface.bitrate or 500000} bps\n"
                f"Status: {'Available' if iface.is_available else 'Unavailable'}"
            )

        self._iface_details.setText(details)

    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        index = self._interface_combo.currentIndex()
        if index < 0 or index >= len(self._interfaces):
            QMessageBox.warning(
                self,
                "No Interface",
                "Please select a CAN interface first.\n\n"
                "Connect a SocketCAN adapter and click Rescan.",
            )
            return

        iface = self._interfaces[index]
        self._do_connect(iface)

    def _do_connect(self, interface: InterfaceInfo) -> None:
        """Perform connection."""
        self._connect_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)

        if self._connection_manager.connect(interface):
            self.connection_established.emit()
        else:
            error = self._connection_manager.last_error
            if error:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"{error.message}\n\n{error.suggestion}",
                )
            self._connect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(True)

    def _on_disconnect_clicked(self) -> None:
        """Handle disconnect button click."""
        self._connection_manager.disconnect()
        self.connection_closed.emit()

    def _on_state_change(
        self, old_state: ConnectionState, new_state: ConnectionState
    ) -> None:
        """Handle connection state changes."""
        if new_state == ConnectionState.CONNECTED:
            self._status_label.setText("Connected")
            self._status_label.setStyleSheet("color: #00cc00;")
            iface = self._connection_manager.current_interface
            if iface:
                self._status_detail.setText(f"Connected to {iface.name}")
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(False)
            self._interface_combo.setEnabled(False)

        elif new_state == ConnectionState.CONNECTING:
            self._status_label.setText("Connecting...")
            self._status_label.setStyleSheet("color: #cccc00;")
            self._status_detail.setText("")

        elif new_state == ConnectionState.VALIDATING:
            self._status_label.setText("Validating...")
            self._status_label.setStyleSheet("color: #cccc00;")
            self._status_detail.setText("Checking CAN bus")

        elif new_state == ConnectionState.DISCONNECTED:
            self._status_label.setText("Disconnected")
            self._status_label.setStyleSheet("color: #cc0000;")
            self._status_detail.setText("")
            self._connect_btn.setEnabled(len(self._interfaces) > 0)
            self._disconnect_btn.setEnabled(False)
            self._rescan_btn.setEnabled(True)
            self._interface_combo.setEnabled(True)

        elif new_state == ConnectionState.ERROR:
            self._status_label.setText("Error")
            self._status_label.setStyleSheet("color: #cc0000;")
            error = self._connection_manager.last_error
            if error:
                self._status_detail.setText(error.message)
            self._connect_btn.setEnabled(len(self._interfaces) > 0)
            self._disconnect_btn.setEnabled(False)
            self._rescan_btn.setEnabled(True)

    def _on_test_adapter(self) -> None:
        """Test the CAN adapter without connecting to a vehicle."""
        index = self._interface_combo.currentIndex()
        if index < 0 or index >= len(self._interfaces):
            QMessageBox.warning(
                self,
                "No Interface",
                "Please select a CAN interface first.",
            )
            return

        iface = self._interfaces[index]
        iface_name = iface.name

        # Get detailed interface status
        status = get_interface_status(iface_name)

        # Build test result message
        results = []
        all_ok = True

        # Check interface exists
        if status["exists"]:
            results.append(f"Interface {iface_name}: FOUND")
        else:
            results.append(f"Interface {iface_name}: NOT FOUND")
            all_ok = False

        # Check if it's a CAN interface
        if status["is_can"]:
            results.append("CAN type: OK")
        else:
            results.append("CAN type: NOT DETECTED")
            all_ok = False

        # Check if interface is up
        if status["is_up"]:
            results.append(f"Interface state: UP ({status['state']})")
        else:
            results.append(f"Interface state: DOWN ({status['state']})")
            results.append("Run: sudo ip link set can0 up type can bitrate 500000")
            all_ok = False

        # Check bitrate
        if status["bitrate"]:
            results.append(f"Bitrate: {status['bitrate']} bps")
            if status["bitrate"] != 500000:
                results.append("Warning: BMW requires 500000 bps")
        else:
            results.append("Bitrate: Unknown")

        # Try to open the interface briefly
        if all_ok:
            try:
                import can
                bus = can.interface.Bus(
                    channel=iface_name,
                    interface="socketcan",
                )
                bus_state = bus.state
                bus.shutdown()
                results.append(f"CAN bus open: OK (state: {bus_state})")
                results.append("")
                results.append("ADAPTER TEST PASSED!")
                results.append("Your adapter is ready for vehicle connection.")
            except Exception as e:
                results.append(f"CAN bus open: FAILED ({e})")
                all_ok = False

        # Show results
        if all_ok:
            QMessageBox.information(
                self,
                "Adapter Test Passed",
                "\n".join(results),
            )
        else:
            QMessageBox.warning(
                self,
                "Adapter Test Failed",
                "\n".join(results),
            )
