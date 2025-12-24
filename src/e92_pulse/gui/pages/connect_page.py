"""
Connect Page

Provides interface for connecting to the diagnostic interface.
Handles port discovery, selection, and connection management.
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

from e92_pulse.core.connection import ConnectionManager, ConnectionState
from e92_pulse.core.discovery import PortInfo
from e92_pulse.core.config import AppConfig
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ConnectPage(QWidget):
    """
    Connection management page.

    Provides:
    - Port discovery and selection
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
        self._ports: list[PortInfo] = []

        self._setup_ui()
        self._connect_signals()

        # Initial port scan
        QTimer.singleShot(100, self._scan_ports)

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
            "Connect your K+DCAN USB cable to begin diagnostics"
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

        # Port selection
        port_group = QGroupBox("Diagnostic Port")
        port_layout = QVBoxLayout(port_group)

        port_row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(300)
        self._port_combo.setPlaceholderText("Select port...")
        port_row.addWidget(self._port_combo, 1)

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setFixedWidth(80)
        self._rescan_btn.clicked.connect(self._scan_ports)
        port_row.addWidget(self._rescan_btn)

        port_layout.addLayout(port_row)

        # Port details
        self._port_details = QLabel("No port selected")
        self._port_details.setStyleSheet("color: #888888; font-size: 11px;")
        self._port_details.setWordWrap(True)
        port_layout.addWidget(self._port_details)

        left_layout.addWidget(port_group)

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
            "K+DCAN USB cable (FTDI recommended)",
            "Vehicle ignition ON (engine OFF)",
            "Linux with dialout group membership",
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
            <b>No ports detected?</b><br>
            - Check USB cable connection<br>
            - Verify user is in 'dialout' group:<br>
            <code style="color: #00cccc;">sudo usermod -aG dialout $USER</code><br>
            - Log out and back in after group change<br><br>
            <b>Connection fails?</b><br>
            - Ensure ignition is ON<br>
            - Try different USB port<br>
            - Check for other diagnostic software
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
        self._port_combo.currentIndexChanged.connect(self._on_port_selected)
        self._connection_manager.add_state_callback(self._on_state_change)

    def _scan_ports(self) -> None:
        """Scan for available ports."""
        self._port_combo.clear()
        self._ports = self._connection_manager.discover_ports(force_rescan=True)

        if not self._ports:
            self._port_combo.addItem("No ports detected")
            self._port_combo.setEnabled(False)
            self._connect_btn.setEnabled(False)
            self._port_details.setText(
                "No USB serial ports found. Check cable connection."
            )
        else:
            self._port_combo.setEnabled(True)
            self._connect_btn.setEnabled(True)

            for port in self._ports:
                display = f"{port.device} - {port.name}"
                if port.score > 50:
                    display += " (Recommended)"
                self._port_combo.addItem(display)

            # Select first (best) port
            self._port_combo.setCurrentIndex(0)
            self._on_port_selected(0)

        logger.info(f"Port scan complete: {len(self._ports)} port(s) found")

    def _on_port_selected(self, index: int) -> None:
        """Handle port selection change."""
        if index < 0 or index >= len(self._ports):
            return

        port = self._ports[index]
        details = (
            f"Chip: {port.name}\n"
            f"Manufacturer: {port.manufacturer or 'Unknown'}\n"
            f"Score: {port.score}"
        )
        if port.by_id_path:
            details += f"\nStable path: {port.by_id_path}"

        self._port_details.setText(details)

    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        index = self._port_combo.currentIndex()
        if index < 0 or index >= len(self._ports):
            if self._config.simulation_mode:
                # Allow connect in simulation mode even without ports
                self._do_connect(None)
            return

        port = self._ports[index]
        self._do_connect(port)

    def _do_connect(self, port: PortInfo | None) -> None:
        """Perform connection."""
        self._connect_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)

        if self._connection_manager.connect(port):
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
            port = self._connection_manager.current_port
            if port:
                self._status_detail.setText(f"Connected to {port.device}")
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(False)
            self._port_combo.setEnabled(False)

        elif new_state == ConnectionState.CONNECTING:
            self._status_label.setText("Connecting...")
            self._status_label.setStyleSheet("color: #cccc00;")
            self._status_detail.setText("")

        elif new_state == ConnectionState.VALIDATING:
            self._status_label.setText("Validating...")
            self._status_label.setStyleSheet("color: #cccc00;")
            self._status_detail.setText("Checking diagnostic link")

        elif new_state == ConnectionState.DISCONNECTED:
            self._status_label.setText("Disconnected")
            self._status_label.setStyleSheet("color: #cc0000;")
            self._status_detail.setText("")
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._rescan_btn.setEnabled(True)
            self._port_combo.setEnabled(True)

        elif new_state == ConnectionState.ERROR:
            self._status_label.setText("Error")
            self._status_label.setStyleSheet("color: #cc0000;")
            error = self._connection_manager.last_error
            if error:
                self._status_detail.setText(error.message)
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._rescan_btn.setEnabled(True)
