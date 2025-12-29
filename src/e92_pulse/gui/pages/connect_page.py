"""
Connect Page - Simple plug and play interface.
"""

from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QMessageBox
from PyQt6.QtGui import QFont

from e92_pulse.core.connection import ConnectionManager, ConnectionState, InterfaceInfo
from e92_pulse.core.config import AppConfig
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ConnectPage(QWidget):
    """Simple connect page - plug and play."""

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
        self._connection_manager.add_state_callback(self._on_state_change)

        # Auto-scan on startup
        QTimer.singleShot(500, self._auto_scan)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 50, 50, 50)
        layout.setSpacing(30)

        # Title
        title = QLabel("E92 Pulse")
        title.setFont(QFont("Sans", 32, QFont.Weight.Bold))
        layout.addWidget(title)

        # Status
        self._status = QLabel("Scanning for CAN adapter...")
        self._status.setFont(QFont("Sans", 18))
        layout.addWidget(self._status)

        # Interface found
        self._interface_info = QLabel("")
        self._interface_info.setFont(QFont("Sans", 14))
        layout.addWidget(self._interface_info)

        # Buttons
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setMinimumHeight(60)
        self._connect_btn.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        self._connect_btn.clicked.connect(self._connect)
        self._connect_btn.setEnabled(False)
        layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setMinimumHeight(60)
        self._disconnect_btn.setFont(QFont("Sans", 14))
        self._disconnect_btn.clicked.connect(self._disconnect)
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.hide()
        layout.addWidget(self._disconnect_btn)

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setMinimumHeight(40)
        self._rescan_btn.clicked.connect(self._auto_scan)
        layout.addWidget(self._rescan_btn)

        # Instructions
        instructions = QLabel(
            "Setup: sudo ip link set can0 up type can bitrate 500000"
        )
        instructions.setFont(QFont("Monospace", 11))
        layout.addWidget(instructions)

        layout.addStretch()

    def _auto_scan(self) -> None:
        """Scan for CAN interfaces."""
        self._interfaces = self._connection_manager.discover_interfaces()

        if self._interfaces:
            iface = self._interfaces[0]
            self._status.setText(f"Found: {iface.name}")
            self._interface_info.setText(f"SocketCAN @ 500kbps")
            self._connect_btn.setEnabled(True)
        else:
            self._status.setText("No CAN interface found")
            self._interface_info.setText("Connect adapter and run setup command")
            self._connect_btn.setEnabled(False)

    def _connect(self) -> None:
        """Connect to first available interface."""
        if not self._interfaces:
            return

        self._connect_btn.setEnabled(False)
        self._rescan_btn.setEnabled(False)

        if self._connection_manager.connect(self._interfaces[0]):
            self.connection_established.emit()
        else:
            error = self._connection_manager.last_error
            if error:
                QMessageBox.warning(self, "Error", f"{error.message}\n\n{error.suggestion}")
            self._connect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(True)

    def _disconnect(self) -> None:
        """Disconnect."""
        self._connection_manager.disconnect()
        self.connection_closed.emit()

    def _on_state_change(self, old: ConnectionState, new: ConnectionState) -> None:
        """Handle state changes."""
        if new == ConnectionState.CONNECTED:
            self._status.setText("Connected")
            self._connect_btn.hide()
            self._disconnect_btn.show()
            self._disconnect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(False)
        elif new == ConnectionState.DISCONNECTED:
            self._status.setText("Disconnected")
            self._disconnect_btn.hide()
            self._connect_btn.show()
            self._connect_btn.setEnabled(len(self._interfaces) > 0)
            self._rescan_btn.setEnabled(True)
        elif new == ConnectionState.CONNECTING:
            self._status.setText("Connecting...")
        elif new == ConnectionState.ERROR:
            self._status.setText("Error")
            self._connect_btn.setEnabled(True)
            self._rescan_btn.setEnabled(True)
