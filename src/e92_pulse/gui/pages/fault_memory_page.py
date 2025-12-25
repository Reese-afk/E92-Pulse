"""
Fault Memory Page

DTC reading, display, and clearing functionality.
"""

from datetime import datetime
import json

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QApplication,
    QGroupBox,
    QSplitter,
    QTextEdit,
)
from PyQt6.QtGui import QFont, QColor

from e92_pulse.core.vehicle import VehicleProfile, DTCInfo
from e92_pulse.core.safety import SafetyManager
from e92_pulse.bmw.module_registry import ModuleRegistry
from e92_pulse.protocols.uds_client import UDSClient
from e92_pulse.protocols.services import DTCSubFunction, DTCStatusMask
from e92_pulse.core.app_logging import get_logger, log_audit_event

logger = get_logger(__name__)


class DTCReadWorker(QThread):
    """Background worker for DTC reading."""

    progress = pyqtSignal(str, int)  # module_name, dtc_count
    finished = pyqtSignal(list)  # List of DTCInfo

    def __init__(
        self,
        uds_client: UDSClient,
        registry: ModuleRegistry,
        module_filter: str | None = None,
    ):
        super().__init__()
        self._uds = uds_client
        self._registry = registry
        self._module_filter = module_filter

    def run(self) -> None:
        """Read DTCs from modules."""
        dtcs: list[DTCInfo] = []

        modules = self._registry.get_all_modules()
        if self._module_filter and self._module_filter != "All Modules":
            modules = [
                m for m in modules if m.module_id == self._module_filter
            ]

        for module in modules:
            try:
                self._uds.set_target(module.address)

                # Try to read DTCs
                response = self._uds.read_dtc_info(
                    DTCSubFunction.REPORT_DTC_BY_STATUS_MASK,
                    bytes([0xFF]),  # All status bits
                )

                if response.positive and len(response.data) > 2:
                    # Parse DTCs from response
                    data = response.data[2:]  # Skip sub-function and availability mask
                    count = 0

                    while len(data) >= 4:
                        dtc_bytes = data[:3]
                        status = data[3]
                        data = data[4:]

                        dtc_code = int.from_bytes(dtc_bytes, "big")
                        dtc_str = self._format_dtc_code(dtc_code, module.dtc_prefix)

                        status_str = self._get_status_string(status)

                        dtc_info = DTCInfo(
                            code=dtc_str,
                            description=f"DTC 0x{dtc_code:06X}",
                            module_id=module.module_id,
                            module_name=module.name,
                            status=status_str,
                        )
                        dtcs.append(dtc_info)
                        count += 1

                    self.progress.emit(module.name, count)

            except Exception as e:
                logger.debug(f"DTC read failed for {module.module_id}: {e}")

        self.finished.emit(dtcs)

    def _format_dtc_code(self, code: int, prefix: str) -> str:
        """Format DTC code as standard string (e.g., P0171)."""
        # Extract bytes
        first = (code >> 16) & 0xFF
        second = (code >> 8) & 0xFF
        third = code & 0xFF

        # Standard OBD-II format
        type_char = prefix or "U"
        return f"{type_char}{first:02X}{second:02X}"

    def _get_status_string(self, status: int) -> str:
        """Get status string from status byte."""
        if status & DTCStatusMask.CONFIRMED_DTC:
            return "Confirmed"
        elif status & DTCStatusMask.PENDING_DTC:
            return "Pending"
        elif status & DTCStatusMask.TEST_FAILED:
            return "Active"
        else:
            return "Stored"


class FaultMemoryPage(QWidget):
    """
    Fault Memory page for DTC management.

    Provides:
    - DTC reading from all modules
    - Filtering and searching
    - DTC details view
    - Clear DTCs (with confirmation)
    - Export to JSON/clipboard
    """

    def __init__(
        self,
        uds_client: UDSClient | None,
        profile: VehicleProfile,
        registry: ModuleRegistry,
        safety_manager: SafetyManager,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._uds = uds_client
        self._profile = profile
        self._registry = registry
        self._safety = safety_manager
        self._dtcs: list[DTCInfo] = []
        self._read_worker: DTCReadWorker | None = None

        self._setup_ui()

    def set_uds_client(self, uds_client: UDSClient) -> None:
        """Set the UDS client."""
        self._uds = uds_client

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Fault Memory")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Read and manage diagnostic trouble codes")
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        # Controls bar
        controls = QHBoxLayout()

        # Module filter
        self._module_combo = QComboBox()
        self._module_combo.addItem("All Modules")
        for module in self._registry.get_all_modules():
            self._module_combo.addItem(module.module_id)
        self._module_combo.setMinimumWidth(150)
        controls.addWidget(QLabel("Module:"))
        controls.addWidget(self._module_combo)

        controls.addSpacing(20)

        # Search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search DTCs...")
        self._search_input.setMinimumWidth(200)
        self._search_input.textChanged.connect(self._filter_dtcs)
        controls.addWidget(self._search_input)

        controls.addStretch()

        # Buttons
        self._read_btn = QPushButton("Read DTCs")
        self._read_btn.setMinimumHeight(40)
        self._read_btn.clicked.connect(self._read_dtcs)
        controls.addWidget(self._read_btn)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setMinimumHeight(40)
        self._clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc6600;
            }
            QPushButton:hover {
                background-color: #dd7711;
            }
        """)
        self._clear_btn.clicked.connect(self._clear_all_dtcs)
        controls.addWidget(self._clear_btn)

        layout.addLayout(controls)

        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        # DTC Table
        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self._dtc_table = QTableWidget()
        self._dtc_table.setColumnCount(5)
        self._dtc_table.setHorizontalHeaderLabels(
            ["Code", "Module", "Status", "Description", "Occurrences"]
        )
        self._dtc_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._dtc_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._dtc_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._dtc_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._dtc_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self._dtc_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._dtc_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._dtc_table.itemSelectionChanged.connect(self._on_dtc_selected)
        self._dtc_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
            }
        """)

        table_layout.addWidget(self._dtc_table)
        splitter.addWidget(table_frame)

        # Details panel
        details_frame = QFrame()
        details_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 5px;
            }
        """)
        details_layout = QVBoxLayout(details_frame)

        details_label = QLabel("DTC Details")
        details_label.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        details_layout.addWidget(details_label)

        self._details_text = QTextEdit()
        self._details_text.setReadOnly(True)
        self._details_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: none;
                font-family: monospace;
            }
        """)
        self._details_text.setPlaceholderText("Select a DTC to view details")
        details_layout.addWidget(self._details_text)

        # Action buttons for selected DTC
        action_layout = QHBoxLayout()

        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        action_layout.addWidget(self._copy_btn)

        self._clear_selected_btn = QPushButton("Clear Selected Module")
        self._clear_selected_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc6600;
            }
        """)
        self._clear_selected_btn.clicked.connect(self._clear_selected_module)
        action_layout.addWidget(self._clear_selected_btn)

        self._export_btn = QPushButton("Export to JSON")
        self._export_btn.clicked.connect(self._export_to_json)
        action_layout.addWidget(self._export_btn)

        action_layout.addStretch()
        details_layout.addLayout(action_layout)

        splitter.addWidget(details_frame)
        splitter.setSizes([400, 200])

        layout.addWidget(splitter, 1)

        # Summary bar
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        summary_layout = QHBoxLayout(summary_frame)

        self._summary_label = QLabel("No DTCs loaded")
        summary_layout.addWidget(self._summary_label)
        summary_layout.addStretch()

        layout.addWidget(summary_frame)

    def _read_dtcs(self) -> None:
        """Read DTCs from vehicle."""
        if not self._uds:
            QMessageBox.warning(self, "Error", "Not connected to vehicle")
            return

        self._read_btn.setEnabled(False)
        self._dtc_table.setRowCount(0)
        self._summary_label.setText("Reading DTCs...")

        module_filter = self._module_combo.currentText()
        if module_filter == "All Modules":
            module_filter = None

        self._read_worker = DTCReadWorker(
            self._uds, self._registry, module_filter
        )
        self._read_worker.progress.connect(self._on_read_progress)
        self._read_worker.finished.connect(self._on_read_complete)
        self._read_worker.start()

    def _on_read_progress(self, module_name: str, count: int) -> None:
        """Handle read progress."""
        self._summary_label.setText(f"Reading {module_name}... ({count} DTCs)")

    def _on_read_complete(self, dtcs: list[DTCInfo]) -> None:
        """Handle read completion."""
        self._dtcs = dtcs
        self._read_btn.setEnabled(True)
        self._populate_table(dtcs)
        self._update_summary()

    def _populate_table(self, dtcs: list[DTCInfo]) -> None:
        """Populate the DTC table."""
        self._dtc_table.setRowCount(len(dtcs))

        for row, dtc in enumerate(dtcs):
            # Code
            code_item = QTableWidgetItem(dtc.code)
            code_item.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
            self._dtc_table.setItem(row, 0, code_item)

            # Module
            module_item = QTableWidgetItem(dtc.module_id)
            self._dtc_table.setItem(row, 1, module_item)

            # Status
            status_item = QTableWidgetItem(dtc.status)
            if dtc.status == "Confirmed" or dtc.status == "Active":
                status_item.setForeground(QColor("#cc0000"))
            elif dtc.status == "Pending":
                status_item.setForeground(QColor("#cccc00"))
            else:
                status_item.setForeground(QColor("#888888"))
            self._dtc_table.setItem(row, 2, status_item)

            # Description
            desc_item = QTableWidgetItem(dtc.description)
            self._dtc_table.setItem(row, 3, desc_item)

            # Occurrences
            occ_item = QTableWidgetItem(str(dtc.occurrence_count))
            occ_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dtc_table.setItem(row, 4, occ_item)

    def _update_summary(self) -> None:
        """Update summary label."""
        if not self._dtcs:
            self._summary_label.setText("No DTCs found")
            return

        active = sum(1 for d in self._dtcs if d.status in ("Confirmed", "Active"))
        pending = sum(1 for d in self._dtcs if d.status == "Pending")
        stored = len(self._dtcs) - active - pending

        self._summary_label.setText(
            f"Total: {len(self._dtcs)} DTCs | "
            f"Active: {active} | Pending: {pending} | Stored: {stored}"
        )

    def _filter_dtcs(self, text: str) -> None:
        """Filter displayed DTCs."""
        text = text.lower()
        for row in range(self._dtc_table.rowCount()):
            match = False
            for col in range(self._dtc_table.columnCount()):
                item = self._dtc_table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            self._dtc_table.setRowHidden(row, not match)

    def _on_dtc_selected(self) -> None:
        """Handle DTC selection."""
        rows = self._dtc_table.selectionModel().selectedRows()
        if not rows:
            self._details_text.clear()
            return

        row = rows[0].row()
        if row < len(self._dtcs):
            dtc = self._dtcs[row]
            self._show_dtc_details(dtc)

    def _show_dtc_details(self, dtc: DTCInfo) -> None:
        """Show DTC details in the details panel."""
        details = f"""
<h3>{dtc.code}</h3>
<p><b>Module:</b> {dtc.module_id} ({dtc.module_name})</p>
<p><b>Status:</b> {dtc.status}</p>
<p><b>Description:</b> {dtc.description}</p>
<p><b>Occurrences:</b> {dtc.occurrence_count}</p>
"""
        if dtc.first_seen:
            details += f"<p><b>First Seen:</b> {dtc.first_seen.isoformat()}</p>"
        if dtc.last_seen:
            details += f"<p><b>Last Seen:</b> {dtc.last_seen.isoformat()}</p>"

        self._details_text.setHtml(details)

    def _clear_all_dtcs(self) -> None:
        """Clear all DTCs with confirmation."""
        if not self._uds:
            return

        # Two-step confirmation
        reply = QMessageBox.warning(
            self,
            "Clear All DTCs",
            "Are you sure you want to clear ALL diagnostic trouble codes?\n\n"
            "This action will be logged for audit purposes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Second confirmation
        reply = QMessageBox.warning(
            self,
            "Confirm Clear All DTCs",
            "FINAL CONFIRMATION\n\n"
            "Clearing DTCs will reset fault memory across all modules.\n"
            "This cannot be undone.\n\n"
            "Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        log_audit_event(
            "dtc_clear_all",
            "User initiated clear all DTCs",
            {"dtc_count": len(self._dtcs)},
        )

        # Clear DTCs on all modules
        cleared_count = 0
        for module in self._registry.get_all_modules():
            try:
                self._uds.set_target(module.address)
                response = self._uds.clear_dtc_info()
                if response.positive:
                    cleared_count += 1
            except Exception as e:
                logger.debug(f"Clear failed for {module.module_id}: {e}")

        self._dtcs.clear()
        self._dtc_table.setRowCount(0)
        self._details_text.clear()

        QMessageBox.information(
            self,
            "DTCs Cleared",
            f"Successfully cleared DTCs from {cleared_count} module(s)",
        )

        self._update_summary()

    def _clear_selected_module(self) -> None:
        """Clear DTCs from selected module."""
        rows = self._dtc_table.selectionModel().selectedRows()
        if not rows or not self._uds:
            return

        row = rows[0].row()
        if row >= len(self._dtcs):
            return

        dtc = self._dtcs[row]
        module = self._registry.get_module(dtc.module_id)
        if not module:
            return

        reply = QMessageBox.warning(
            self,
            f"Clear {dtc.module_id} DTCs",
            f"Clear all DTCs from {dtc.module_id} ({dtc.module_name})?\n\n"
            "This action will be logged.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        log_audit_event(
            "dtc_clear_module",
            f"User cleared DTCs from {dtc.module_id}",
            {"module": dtc.module_id},
        )

        try:
            self._uds.set_target(module.address)
            response = self._uds.clear_dtc_info()

            if response.positive:
                # Remove from list
                self._dtcs = [d for d in self._dtcs if d.module_id != dtc.module_id]
                self._populate_table(self._dtcs)
                self._update_summary()
                QMessageBox.information(
                    self,
                    "Success",
                    f"DTCs cleared from {dtc.module_id}",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Failed",
                    f"Failed to clear DTCs: {response.error_message}",
                )

        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _copy_to_clipboard(self) -> None:
        """Copy DTCs to clipboard."""
        if not self._dtcs:
            return

        text = "Code\tModule\tStatus\tDescription\n"
        for dtc in self._dtcs:
            text += f"{dtc.code}\t{dtc.module_id}\t{dtc.status}\t{dtc.description}\n"

        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        self._summary_label.setText("Copied to clipboard!")

    def _export_to_json(self) -> None:
        """Export DTCs to JSON file."""
        if not self._dtcs:
            return

        from PyQt6.QtWidgets import QFileDialog

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export DTCs",
            f"dtcs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)",
        )

        if not filename:
            return

        data = {
            "export_time": datetime.now().isoformat(),
            "dtcs": [
                {
                    "code": d.code,
                    "module": d.module_id,
                    "module_name": d.module_name,
                    "status": d.status,
                    "description": d.description,
                    "occurrences": d.occurrence_count,
                }
                for d in self._dtcs
            ],
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        QMessageBox.information(
            self,
            "Export Complete",
            f"DTCs exported to:\n{filename}",
        )
