"""
Services Page

Service functions including Battery Registration and ECU Reset.
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QStackedWidget,
    QGroupBox,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QProgressBar,
    QTextEdit,
    QMessageBox,
)
from PyQt6.QtGui import QFont

from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.bmw.services import (
    ServiceManager,
    BatteryRegistrationService,
    ServiceResult,
)
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ServiceWorker(QThread):
    """Background worker for service execution."""

    progress = pyqtSignal(str, int)  # message, percent
    finished = pyqtSignal(object)  # ServiceResult

    def __init__(
        self,
        service: BatteryRegistrationService,
        capacity: int,
        battery_type: str,
    ):
        super().__init__()
        self._service = service
        self._capacity = capacity
        self._battery_type = battery_type

    def run(self) -> None:
        """Execute the service."""
        self._service.add_progress_callback(
            lambda msg, pct: self.progress.emit(msg, pct)
        )
        result = self._service.execute(self._capacity, self._battery_type)
        self.finished.emit(result)


class ServicesPage(QWidget):
    """
    Service Functions page.

    Provides guided wizards for:
    - Battery Registration
    - ECU Reset
    """

    def __init__(
        self,
        service_manager: ServiceManager | None,
        profile: VehicleProfile,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._service_manager = service_manager
        self._profile = profile
        self._service_worker: ServiceWorker | None = None

        self._setup_ui()

    def set_service_manager(self, service_manager: ServiceManager) -> None:
        """Set the service manager."""
        self._service_manager = service_manager

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Service Functions")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Perform vehicle service operations")
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

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
        warning_text = QLabel(
            "<b>Note:</b> Only safe, user-serviceable functions are available. "
            "ECU flashing, coding, and security-related operations are blocked."
        )
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        layout.addWidget(warning_frame)

        # Main content
        content_layout = QHBoxLayout()
        content_layout.setSpacing(30)

        # Service selection (left)
        selection_frame = QFrame()
        selection_frame.setFixedWidth(250)
        selection_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
            }
        """)
        selection_layout = QVBoxLayout(selection_frame)

        selection_label = QLabel("Available Services")
        selection_label.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        selection_layout.addWidget(selection_label)

        # Service buttons
        self._battery_btn = QPushButton("Battery Registration")
        self._battery_btn.setMinimumHeight(50)
        self._battery_btn.setCheckable(True)
        self._battery_btn.setChecked(True)
        self._battery_btn.clicked.connect(lambda: self._select_service(0))
        selection_layout.addWidget(self._battery_btn)

        self._reset_btn = QPushButton("ECU Reset")
        self._reset_btn.setMinimumHeight(50)
        self._reset_btn.setCheckable(True)
        self._reset_btn.clicked.connect(lambda: self._select_service(1))
        selection_layout.addWidget(self._reset_btn)

        selection_layout.addStretch()
        content_layout.addWidget(selection_frame)

        # Service wizard (right)
        self._wizard_stack = QStackedWidget()
        self._wizard_stack.setStyleSheet("""
            QStackedWidget {
                background-color: #2d2d2d;
                border-radius: 10px;
            }
        """)

        # Battery registration wizard
        self._battery_wizard = self._create_battery_wizard()
        self._wizard_stack.addWidget(self._battery_wizard)

        # ECU reset wizard
        self._reset_wizard = self._create_reset_wizard()
        self._wizard_stack.addWidget(self._reset_wizard)

        content_layout.addWidget(self._wizard_stack, 1)

        layout.addLayout(content_layout, 1)

    def _create_battery_wizard(self) -> QWidget:
        """Create battery registration wizard."""
        wizard = QWidget()
        layout = QVBoxLayout(wizard)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("Battery Registration")
        title.setFont(QFont("Sans", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel(
            "Register a new battery with the vehicle's power management system. "
            "This is required after replacing the battery to ensure proper charging "
            "and power management."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(desc)

        layout.addSpacing(20)

        # Step 1: Parameters
        params_group = QGroupBox("Step 1: Battery Parameters")
        params_layout = QVBoxLayout(params_group)

        # Capacity
        cap_layout = QHBoxLayout()
        cap_layout.addWidget(QLabel("Battery Capacity (Ah):"))
        self._capacity_spin = QSpinBox()
        self._capacity_spin.setRange(50, 120)
        self._capacity_spin.setValue(80)
        self._capacity_spin.setSuffix(" Ah")
        cap_layout.addWidget(self._capacity_spin)
        cap_layout.addStretch()
        params_layout.addLayout(cap_layout)

        # Type
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Battery Type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["AGM", "EFB", "Standard"])
        type_layout.addWidget(self._type_combo)
        type_layout.addStretch()
        params_layout.addLayout(type_layout)

        layout.addWidget(params_group)

        # Step 2: Preconditions
        precond_group = QGroupBox("Step 2: Preconditions")
        precond_layout = QVBoxLayout(precond_group)

        self._precond_checks = []
        preconditions = [
            ("Ignition is ON (engine OFF)", True),
            ("Battery charger disconnected", True),
            ("Vehicle is stationary", True),
            ("I understand this operation will be logged", True),
        ]

        for text, required in preconditions:
            check = QCheckBox(text)
            check.stateChanged.connect(self._check_preconditions)
            self._precond_checks.append(check)
            precond_layout.addWidget(check)

        layout.addWidget(precond_group)

        # Step 3: Execute
        exec_group = QGroupBox("Step 3: Execute")
        exec_layout = QVBoxLayout(exec_group)

        self._battery_progress = QProgressBar()
        self._battery_progress.setValue(0)
        exec_layout.addWidget(self._battery_progress)

        self._battery_status = QLabel("Ready")
        self._battery_status.setStyleSheet("color: #888888;")
        exec_layout.addWidget(self._battery_status)

        self._execute_btn = QPushButton("Execute Battery Registration")
        self._execute_btn.setMinimumHeight(50)
        self._execute_btn.setEnabled(False)
        self._execute_btn.clicked.connect(self._execute_battery_registration)
        exec_layout.addWidget(self._execute_btn)

        layout.addWidget(exec_group)

        # Result log
        self._battery_log = QTextEdit()
        self._battery_log.setReadOnly(True)
        self._battery_log.setMaximumHeight(100)
        self._battery_log.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                font-family: monospace;
            }
        """)
        layout.addWidget(self._battery_log)

        layout.addStretch()

        return wizard

    def _create_reset_wizard(self) -> QWidget:
        """Create ECU reset wizard."""
        wizard = QWidget()
        layout = QVBoxLayout(wizard)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("ECU Reset")
        title.setFont(QFont("Sans", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        desc = QLabel(
            "Perform a safe reset of an ECU module. Only soft and key-off/on "
            "resets are available. Hard resets that could damage the ECU are blocked."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(desc)

        layout.addSpacing(20)

        # Module selection
        module_group = QGroupBox("Step 1: Select Module")
        module_layout = QVBoxLayout(module_group)

        self._reset_module_combo = QComboBox()
        # Will be populated from scan results
        module_layout.addWidget(self._reset_module_combo)

        self._refresh_modules_btn = QPushButton("Refresh Module List")
        self._refresh_modules_btn.clicked.connect(self._refresh_module_list)
        module_layout.addWidget(self._refresh_modules_btn)

        layout.addWidget(module_group)

        # Initial population
        self._refresh_module_list()

        # Reset type
        type_group = QGroupBox("Step 2: Reset Type")
        type_layout = QVBoxLayout(type_group)

        self._soft_reset_radio = QCheckBox("Soft Reset (recommended)")
        self._soft_reset_radio.setChecked(True)
        type_layout.addWidget(self._soft_reset_radio)

        self._keyoff_reset_radio = QCheckBox("Key Off/On Reset")
        type_layout.addWidget(self._keyoff_reset_radio)

        layout.addWidget(type_group)

        # Confirmation
        confirm_group = QGroupBox("Step 3: Confirmation")
        confirm_layout = QVBoxLayout(confirm_group)

        self._reset_confirm = QCheckBox(
            "I confirm I want to reset this ECU and understand the vehicle "
            "may need recalibration after reset"
        )
        confirm_layout.addWidget(self._reset_confirm)

        layout.addWidget(confirm_group)

        # Execute button
        self._reset_execute_btn = QPushButton("Execute ECU Reset")
        self._reset_execute_btn.setMinimumHeight(50)
        self._reset_execute_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc6600;
            }
            QPushButton:hover {
                background-color: #dd7711;
            }
        """)
        self._reset_execute_btn.clicked.connect(self._execute_ecu_reset)
        layout.addWidget(self._reset_execute_btn)

        # Status
        self._reset_status = QLabel("")
        self._reset_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._reset_status)

        layout.addStretch()

        return wizard

    def _select_service(self, index: int) -> None:
        """Select a service."""
        self._wizard_stack.setCurrentIndex(index)
        self._battery_btn.setChecked(index == 0)
        self._reset_btn.setChecked(index == 1)

    def _refresh_module_list(self) -> None:
        """Refresh the module list from scan results."""
        self._reset_module_combo.clear()

        # Get modules from vehicle profile
        if self._profile and self._profile.modules:
            for module_id, status in self._profile.modules.items():
                if status.responding:
                    self._reset_module_combo.addItem(
                        f"{module_id} - {status.name}",
                        module_id
                    )

        # If no modules from profile, add defaults
        if self._reset_module_combo.count() == 0:
            default_modules = [
                ("DME", "Digital Motor Electronics"),
                ("DSC", "Dynamic Stability Control"),
                ("KOMBI", "Instrument Cluster"),
                ("FRM", "Footwell Module"),
                ("CAS", "Car Access System"),
                ("EGS", "Electronic Transmission Control"),
            ]
            for module_id, name in default_modules:
                self._reset_module_combo.addItem(f"{module_id} - {name}", module_id)

        logger.info(f"Module list refreshed: {self._reset_module_combo.count()} modules")

    def _check_preconditions(self) -> None:
        """Check if all preconditions are met."""
        all_checked = all(check.isChecked() for check in self._precond_checks)
        self._execute_btn.setEnabled(all_checked)

    def _execute_battery_registration(self) -> None:
        """Execute battery registration."""
        if not self._service_manager:
            QMessageBox.warning(self, "Error", "Not connected to vehicle")
            return

        # Final confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Battery Registration",
            f"Register battery with:\n\n"
            f"Capacity: {self._capacity_spin.value()} Ah\n"
            f"Type: {self._type_combo.currentText()}\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._execute_btn.setEnabled(False)
        self._battery_progress.setValue(0)
        self._battery_status.setText("Starting...")
        self._battery_log.clear()

        # Execute in background
        self._service_worker = ServiceWorker(
            self._service_manager.battery_registration,
            self._capacity_spin.value(),
            self._type_combo.currentText(),
        )
        self._service_worker.progress.connect(self._on_battery_progress)
        self._service_worker.finished.connect(self._on_battery_complete)
        self._service_worker.start()

    def _on_battery_progress(self, message: str, percent: int) -> None:
        """Handle battery registration progress."""
        self._battery_progress.setValue(percent)
        self._battery_status.setText(message)
        self._battery_log.append(f"[{percent}%] {message}")

    def _on_battery_complete(self, result: ServiceResult) -> None:
        """Handle battery registration completion."""
        self._execute_btn.setEnabled(True)

        if result.success:
            self._battery_status.setText("Success!")
            self._battery_status.setStyleSheet("color: #00cc00;")
            self._battery_log.append(f"\n SUCCESS: {result.message}")
            QMessageBox.information(
                self,
                "Battery Registration Complete",
                result.message,
            )
        else:
            self._battery_status.setText("Failed")
            self._battery_status.setStyleSheet("color: #cc0000;")
            self._battery_log.append(f"\n FAILED: {result.message}")
            QMessageBox.warning(
                self,
                "Battery Registration Failed",
                result.message,
            )

        # Reset precondition checks
        for check in self._precond_checks:
            check.setChecked(False)

    def _execute_ecu_reset(self) -> None:
        """Execute ECU reset."""
        if not self._service_manager:
            QMessageBox.warning(self, "Error", "Not connected to vehicle")
            return

        if not self._reset_confirm.isChecked():
            QMessageBox.warning(
                self,
                "Confirmation Required",
                "Please confirm the reset operation",
            )
            return

        # Get selected module
        module_id = self._reset_module_combo.currentData()
        if not module_id:
            # Fallback to parsing from text
            module_text = self._reset_module_combo.currentText()
            module_id = module_text.split(" - ")[0] if module_text else None

        if not module_id:
            QMessageBox.warning(self, "Error", "Please select a module")
            return

        # Get reset type
        reset_type = 0x03 if self._soft_reset_radio.isChecked() else 0x02

        # Final confirmation
        reply = QMessageBox.warning(
            self,
            "Confirm ECU Reset",
            f"Reset {module_id}?\n\n"
            "This may temporarily interrupt vehicle functions.\n"
            "The ECU will restart after reset.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Get module address
        from e92_pulse.bmw.module_registry import ModuleRegistry
        registry = ModuleRegistry()
        module = registry.get_module(module_id)

        if not module:
            QMessageBox.warning(self, "Error", f"Module {module_id} not found")
            return

        # Execute reset
        result = self._service_manager.ecu_reset.execute(
            module_id, module.address, reset_type
        )

        if result.success:
            self._reset_status.setText("Reset successful!")
            self._reset_status.setStyleSheet("color: #00cc00;")
            QMessageBox.information(self, "Success", result.message)
        else:
            self._reset_status.setText("Reset failed")
            self._reset_status.setStyleSheet("color: #cc0000;")
            QMessageBox.warning(self, "Failed", result.message)

        self._reset_confirm.setChecked(False)
