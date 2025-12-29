"""
Connect Page

Provides interface for connecting to the diagnostic interface.
Handles CAN interface discovery and connection management.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QMessageBox,
)
from PyQt6.QtGui import QFont

from e92_pulse.core.connection import ConnectionManager, ConnectionState, InterfaceInfo
from e92_pulse.core.config import AppConfig
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ConnectPage(QWidget):
    """
    Connection management page.

    Simple interface showing detected CAN interface and connect/disconnect buttons.
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

        subtitle = QLabel("Connect your Innomaker USB2CAN adapter to begin")
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Main content frame
        main_frame = QFrame()
        main_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
            }
        """)
        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # Interface status
        iface_title = QLabel("CAN Interface")
        iface_title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        main_layout.addWidget(iface_title)

        self._interface_label = QLabel("Scanning...")
        self._interface_label.setFont(QFont("Sans", 16))
        self._interface_label.setStyleSheet("color: #888888;")
        main_layout.addWidget(self._interface_label)

        self._interface_detail = QLabel("")
        self._interface_detail.setStyleSheet("color: #666666; font-size: 11px;")
        main_layout.addWidget(self._interface_detail)

        main_layout.addSpacing(10)

        # Connection status
        status_title = QLabel("Status")
        status_title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        main_layout.addWidget(status_title)

        self._status_label = QLabel("Disconnected")
        self._status_label.setFont(QFont("Sans", 18, QFont.Weight.Bold))
        self._status_label.setStyleSheet("color: #cc0000;")
        main_layout.addWidget(self._status_label)

        self._status_detail = QLabel("")
        self._status_detail.setStyleSheet("color: #666666;")
        main_layout.addWidget(self._status_detail)

        main_layout.addSpacing(20)

        # Buttons
        btn_layout = QHBoxLayout()

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setMinimumHeight(50)
        self._rescan_btn.setMinimumWidth(120)
        self._rescan_btn.clicked.connect(self._scan_interfaces)
        btn_layout.addWidget(self._rescan_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setMinimumHeight(50)
        self._connect_btn.setMinimumWidth(150)
        self._connect_btn.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._connect_btn.setEnabled(False)
        btn_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setMinimumHeight(50)
        self._disconnect_btn.setMinimumWidth(150)
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

        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

        layout.addWidget(main_frame)

        # Setup instructions
        setup_frame = QFrame()
        setup_frame.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border-radius: 10px;
            }
        """)
        setup_layout = QVBoxLayout(setup_frame)
        setup_layout.setContentsMargins(20, 20, 20, 20)

        setup_title = QLabel("Setup Instructions")
        setup_title.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        setup_layout.addWidget(setup_title)

        instructions = QLabel(
            "1. Connect Innomaker USB2CAN to laptop\n"
            "2. Connect DB9-to-OBD2 cable to adapter and vehicle\n"
            "3. Turn ignition ON (engine OFF)\n"
            "4. Run: sudo ip link set can0 up type can bitrate 500000\n"
            "5. Click Rescan, then Connect"
        )
        instructions.setStyleSheet("color: #aaaaaa; font-family: monospace;")
        setup_layout.addWidget(instructions)

        layout.addWidget(setup_frame)

        # Warning banner
        warning_frame = QFrame()
        warning_frame.setStyleSheet("""
            QFrame {
                background-color: #664400;
                border-radius: 5px;
            }
        """)
        warning_layout = QHBoxLayout(warning_frame)
        warning_layout.setContentsMargins(15, 10, 15, 10)

        warning_text = QLabel(
            "This tool does NOT support immobilizer, key programming, "
            "VIN changes, or ECU flashing. These operations are blocked."
        )
        warning_text.setWordWrap(True)
        warning_text.setStyleSheet("color: #ffcc00;")
        warning_layout.addWidget(warning_text)

        layout.addWidget(warning_frame)

        layout.addStretch()

    def _connect_signals(self) -> None:
        """Connect widget signals."""
        self._connection_manager.add_state_callback(self._on_state_change)

    def _scan_interfaces(self) -> None:
        """Scan for available CAN interfaces."""
        self._interfaces = self._connection_manager.discover_interfaces()

        if not self._interfaces:
            self._interface_label.setText("No CAN interface detected")
            self._interface_label.setStyleSheet("color: #cc6600;")
            self._interface_detail.setText(
                "Connect USB2CAN adapter and run: sudo ip link set can0 up type can bitrate 500000"
            )
            self._connect_btn.setEnabled(False)
        else:
            iface = self._interfaces[0]
            if iface.interface_type == "virtual":
                self._interface_label.setText(f"{iface.name} (Virtual CAN)")
                self._interface_label.setStyleSheet("color: #00cccc;")
                self._interface_detail.setText("Virtual interface for testing")
            else:
                self._interface_label.setText(f"{iface.name}")
                self._interface_label.setStyleSheet("color: #00cc00;")
                self._interface_detail.setText(f"SocketCAN @ {iface.bitrate or 500000} bps")

            self._connect_btn.setEnabled(True)

        logger.info(f"Interface scan: {len(self._interfaces)} CAN interface(s) found")

    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        if not self._interfaces:
            QMessageBox.warning(
                self,
                "No Interface",
                "No CAN interface detected.\n\n"
                "Connect your USB2CAN adapter and click Rescan.",
            )
            return

        iface = self._interfaces[0]
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

        elif new_state == ConnectionState.ERROR:
            self._status_label.setText("Error")
            self._status_label.setStyleSheet("color: #cc0000;")
            error = self._connection_manager.last_error
            if error:
                self._status_detail.setText(error.message)
            self._connect_btn.setEnabled(len(self._interfaces) > 0)
            self._disconnect_btn.setEnabled(False)
            self._rescan_btn.setEnabled(True)
