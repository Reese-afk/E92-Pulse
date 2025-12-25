"""
Main Application Window

Provides the main window with navigation sidebar and content area.
ISTA-style guided workflow interface.
"""

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QPushButton,
    QLabel,
    QFrame,
    QMessageBox,
    QStatusBar,
)
from PyQt6.QtGui import QFont, QAction

from e92_pulse.core.config import AppConfig, save_config
from e92_pulse.core.connection import ConnectionManager, ConnectionState
from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.core.safety import SafetyManager
from e92_pulse.core.app_logging import get_logger, get_session_id, get_log_dir
from e92_pulse.bmw.module_registry import ModuleRegistry
from e92_pulse.protocols.uds_client import UDSClient
from e92_pulse.bmw.module_scan import ModuleScanner
from e92_pulse.bmw.services import ServiceManager

logger = get_logger(__name__)


class NavigationButton(QPushButton):
    """Styled navigation button for sidebar."""

    def __init__(self, text: str, icon_char: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setText(f"  {icon_char}  {text}" if icon_char else f"  {text}")
        self.setCheckable(True)
        self.setMinimumHeight(50)
        self.setFont(QFont("Sans", 11))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 10px;
                border: none;
                border-radius: 5px;
                background-color: transparent;
                color: #e0e0e0;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton:checked {
                background-color: #0066cc;
                color: white;
            }
            QPushButton:disabled {
                color: #666666;
            }
        """)


class StatusIndicator(QFrame):
    """Connection status indicator widget."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(60)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self._status_label = QLabel("Disconnected")
        self._status_label.setFont(QFont("Sans", 10, QFont.Weight.Bold))

        self._detail_label = QLabel("No connection")
        self._detail_label.setFont(QFont("Sans", 9))
        self._detail_label.setStyleSheet("color: #888888;")

        layout.addWidget(self._status_label)
        layout.addWidget(self._detail_label)

        self.set_disconnected()

    def set_connected(self, interface: str) -> None:
        """Set connected state."""
        self._status_label.setText("Connected")
        self._status_label.setStyleSheet("color: #00cc00;")
        self._detail_label.setText(interface)

    def set_disconnected(self) -> None:
        """Set disconnected state."""
        self._status_label.setText("Disconnected")
        self._status_label.setStyleSheet("color: #cc0000;")
        self._detail_label.setText("No connection")

    def set_connecting(self) -> None:
        """Set connecting state."""
        self._status_label.setText("Connecting...")
        self._status_label.setStyleSheet("color: #cccc00;")
        self._detail_label.setText("")


class MainWindow(QMainWindow):
    """
    Main application window.

    Provides ISTA-style navigation with:
    - Connect page
    - Quick Test (module scan)
    - Fault Memory (DTC management)
    - Service Functions
    - Export Session
    """

    connection_changed = pyqtSignal(bool)

    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)

        self._config = config
        self._setup_core_components()
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()

        # Apply window geometry from config
        geom = config.ui.window_geometry
        self.setGeometry(geom["x"], geom["y"], geom["width"], geom["height"])

        logger.info("Main window initialized")

    def _setup_core_components(self) -> None:
        """Initialize core application components."""
        self._safety_manager = SafetyManager()
        self._vehicle_profile = VehicleProfile()
        self._connection_manager = ConnectionManager(self._config)
        self._module_registry = ModuleRegistry(self._config.datapacks_dir)

        # UDS client and services will be created after connection
        self._uds_client: UDSClient | None = None
        self._module_scanner: ModuleScanner | None = None
        self._service_manager: ServiceManager | None = None

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        self.setWindowTitle("E92 Pulse - BMW E92 M3 Diagnostic Tool")
        self.setMinimumSize(1000, 700)

        # Apply dark theme
        self._apply_dark_theme()

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        # Content area
        self._content_stack = QStackedWidget()
        main_layout.addWidget(self._content_stack, 1)

        # Create pages
        self._create_pages()

        # Status bar
        self._setup_status_bar()

    def _apply_dark_theme(self) -> None:
        """Apply dark theme stylesheet."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                color: #e0e0e0;
                font-family: 'Segoe UI', 'Ubuntu', sans-serif;
            }
            QLabel {
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #0066cc;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0077ee;
            }
            QPushButton:pressed {
                background-color: #0055aa;
            }
            QPushButton:disabled {
                background-color: #444444;
                color: #888888;
            }
            QComboBox {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 5px;
                min-height: 25px;
            }
            QComboBox:hover {
                border-color: #0066cc;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 5px;
            }
            QLineEdit:focus {
                border-color: #0066cc;
            }
            QTableWidget {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                gridline-color: #444444;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #0066cc;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                padding: 5px;
                border: none;
                border-bottom: 1px solid #444444;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }
            QProgressBar {
                background-color: #2d2d2d;
                border: 1px solid #444444;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0066cc;
                border-radius: 3px;
            }
            QCheckBox {
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid #444444;
                background-color: #2d2d2d;
            }
            QCheckBox::indicator:checked {
                background-color: #0066cc;
                border-color: #0066cc;
            }
            QGroupBox {
                border: 1px solid #444444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

    def _create_sidebar(self) -> QFrame:
        """Create the navigation sidebar."""
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #252526;
                border-right: 1px solid #3c3c3c;
            }
        """)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # Logo/Title
        title = QLabel("E92 Pulse")
        title.setFont(QFont("Sans", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #0099ff; padding: 10px;")
        layout.addWidget(title)

        subtitle = QLabel("BMW E92 M3 Diagnostics")
        subtitle.setFont(QFont("Sans", 9))
        subtitle.setStyleSheet("color: #888888; padding-left: 10px;")
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Navigation buttons
        self._nav_buttons: dict[str, NavigationButton] = {}

        nav_items = [
            ("connect", "Connect", ""),
            ("quick_test", "Quick Test", ""),
            ("fault_memory", "Fault Memory", ""),
            ("services", "Service Functions", ""),
            ("export", "Export Session", ""),
        ]

        for key, text, icon in nav_items:
            btn = NavigationButton(text, icon)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            self._nav_buttons[key] = btn
            layout.addWidget(btn)

            # Disable pages until connected (except connect page)
            if key != "connect":
                btn.setEnabled(False)

        layout.addStretch()

        # Status indicator
        self._status_indicator = StatusIndicator()
        layout.addWidget(self._status_indicator)

        return sidebar

    def _create_pages(self) -> None:
        """Create content pages."""
        from e92_pulse.gui.pages.connect_page import ConnectPage
        from e92_pulse.gui.pages.quick_test_page import QuickTestPage
        from e92_pulse.gui.pages.fault_memory_page import FaultMemoryPage
        from e92_pulse.gui.pages.services_page import ServicesPage
        from e92_pulse.gui.pages.export_page import ExportPage

        self._pages: dict[str, QWidget] = {}

        # Connect page
        connect_page = ConnectPage(
            self._connection_manager, self._config, self
        )
        connect_page.connection_established.connect(self._on_connected)
        connect_page.connection_closed.connect(self._on_disconnected)
        self._pages["connect"] = connect_page
        self._content_stack.addWidget(connect_page)

        # Quick Test page
        quick_test = QuickTestPage(
            self._module_scanner,
            self._module_registry,
            self._vehicle_profile,
            self,
        )
        self._pages["quick_test"] = quick_test
        self._content_stack.addWidget(quick_test)

        # Fault Memory page
        fault_memory = FaultMemoryPage(
            self._uds_client,
            self._vehicle_profile,
            self._module_registry,
            self._safety_manager,
            self,
        )
        self._pages["fault_memory"] = fault_memory
        self._content_stack.addWidget(fault_memory)

        # Services page
        services = ServicesPage(
            self._service_manager,
            self._vehicle_profile,
            self,
        )
        self._pages["services"] = services
        self._content_stack.addWidget(services)

        # Export page
        export = ExportPage(
            self._vehicle_profile,
            self._config,
            self,
        )
        self._pages["export"] = export
        self._content_stack.addWidget(export)

        # Set initial page
        self._navigate_to("connect")

    def _setup_menu(self) -> None:
        """Set up menu bar."""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #252526;
                border-bottom: 1px solid #3c3c3c;
            }
            QMenuBar::item {
                padding: 5px 10px;
            }
            QMenuBar::item:selected {
                background-color: #3a3a3a;
            }
            QMenu {
                background-color: #2d2d2d;
                border: 1px solid #3c3c3c;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #0066cc;
            }
        """)

        # File menu
        file_menu = menubar.addMenu("&File")

        export_action = QAction("&Export Session...", self)
        export_action.triggered.connect(lambda: self._navigate_to("export"))
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About E92 Pulse", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_status_bar(self) -> None:
        """Set up status bar."""
        self._statusbar = QStatusBar()
        self._statusbar.setStyleSheet("""
            QStatusBar {
                background-color: #007acc;
                color: white;
            }
        """)
        self.setStatusBar(self._statusbar)

        session_label = QLabel(f"Session: {get_session_id()}")
        self._statusbar.addPermanentWidget(session_label)

    def _connect_signals(self) -> None:
        """Connect signals between components."""
        self._connection_manager.add_state_callback(self._on_connection_state_change)

    def _navigate_to(self, page_key: str) -> None:
        """Navigate to a page."""
        if page_key not in self._pages:
            return

        # Update button states
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == page_key)

        # Switch page
        self._content_stack.setCurrentWidget(self._pages[page_key])

        logger.debug(f"Navigated to: {page_key}")

    def _on_connection_state_change(
        self, old_state: ConnectionState, new_state: ConnectionState
    ) -> None:
        """Handle connection state changes."""
        if new_state == ConnectionState.CONNECTED:
            iface = self._connection_manager.current_interface
            if iface:
                self._status_indicator.set_connected(iface.name)
            self._enable_pages(True)
        elif new_state == ConnectionState.CONNECTING:
            self._status_indicator.set_connecting()
        elif new_state == ConnectionState.DISCONNECTED:
            self._status_indicator.set_disconnected()
            self._enable_pages(False)
        elif new_state == ConnectionState.ERROR:
            self._status_indicator.set_disconnected()

    def _on_connected(self) -> None:
        """Handle successful connection."""
        self._enable_pages(True)

        # Create UDS client with actual transport
        transport = self._connection_manager.get_transport()
        if transport:
            self._uds_client = UDSClient(
                transport, self._safety_manager, target_address=0x00
            )
            self._module_scanner = ModuleScanner(
                self._uds_client, self._module_registry, self._vehicle_profile
            )
            self._service_manager = ServiceManager(
                self._uds_client, self._safety_manager, self._vehicle_profile
            )

            # Update pages with new components
            self._pages["quick_test"].set_scanner(self._module_scanner)
            self._pages["fault_memory"].set_uds_client(self._uds_client)
            self._pages["services"].set_service_manager(self._service_manager)

        self.connection_changed.emit(True)
        self._statusbar.showMessage("Connected to vehicle", 3000)

    def _on_disconnected(self) -> None:
        """Handle disconnection."""
        self._enable_pages(False)
        self.connection_changed.emit(False)
        self._statusbar.showMessage("Disconnected", 3000)

    def _enable_pages(self, enabled: bool) -> None:
        """Enable/disable navigation to pages."""
        for key, btn in self._nav_buttons.items():
            if key != "connect":
                btn.setEnabled(enabled)

    def _show_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About E92 Pulse",
            "<h2>E92 Pulse</h2>"
            "<p>Version 0.1.0</p>"
            "<p>BMW E92 M3 Diagnostic Tool</p>"
            "<p>A production-grade diagnostic GUI tool using SocketCAN.</p>"
            "<hr>"
            "<p><b>What this tool does NOT do:</b></p>"
            "<ul>"
            "<li>Immobilizer/key programming</li>"
            "<li>Security bypass</li>"
            "<li>VIN tampering</li>"
            "<li>Odometer changes</li>"
            "<li>ECU flashing/coding</li>"
            "</ul>"
            "<p>These restrictions are by design for safety.</p>",
        )

    def closeEvent(self, event) -> None:
        """Handle window close."""
        # Save window geometry
        geom = self.geometry()
        self._config.ui.window_geometry = {
            "x": geom.x(),
            "y": geom.y(),
            "width": geom.width(),
            "height": geom.height(),
        }
        save_config(self._config)

        # Disconnect if connected
        if self._connection_manager.is_connected:
            self._connection_manager.disconnect()

        logger.info("Application closing")
        event.accept()
