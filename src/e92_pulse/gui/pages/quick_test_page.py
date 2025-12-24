"""
Quick Test Page

ISTA-style module scan page that discovers and probes all ECU modules.
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtGui import QFont, QColor

from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.bmw.module_registry import ModuleRegistry
from e92_pulse.bmw.module_scan import ModuleScanner, ScanResult, ModuleScanResult
from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ScanWorker(QThread):
    """Background worker for module scanning."""

    progress = pyqtSignal(int, int, str)  # current, total, module_name
    finished = pyqtSignal(object)  # ScanResult

    def __init__(self, scanner: ModuleScanner):
        super().__init__()
        self._scanner = scanner

    def run(self) -> None:
        """Run the scan."""
        self._scanner.add_progress_callback(
            lambda c, t, m: self.progress.emit(c, t, m)
        )
        result = self._scanner.scan_all()
        self.finished.emit(result)


class QuickTestPage(QWidget):
    """
    Quick Test (Module Scan) page.

    Provides:
    - One-click module scan
    - Progress visualization
    - Results table with module status
    - Summary of faults found
    """

    def __init__(
        self,
        scanner: ModuleScanner | None,
        registry: ModuleRegistry,
        profile: VehicleProfile,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._scanner = scanner
        self._registry = registry
        self._profile = profile
        self._scan_worker: ScanWorker | None = None
        self._last_result: ScanResult | None = None

        self._setup_ui()

    def set_scanner(self, scanner: ModuleScanner) -> None:
        """Set the module scanner."""
        self._scanner = scanner

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Quick Test")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Scan all vehicle modules to check their status")
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # Controls bar
        controls = QHBoxLayout()

        self._scan_btn = QPushButton("Start Scan")
        self._scan_btn.setMinimumHeight(50)
        self._scan_btn.setMinimumWidth(150)
        self._scan_btn.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        self._scan_btn.clicked.connect(self._start_scan)
        controls.addWidget(self._scan_btn)

        self._abort_btn = QPushButton("Abort")
        self._abort_btn.setMinimumHeight(50)
        self._abort_btn.setEnabled(False)
        self._abort_btn.setStyleSheet("""
            QPushButton {
                background-color: #cc3333;
            }
            QPushButton:hover {
                background-color: #dd4444;
            }
        """)
        self._abort_btn.clicked.connect(self._abort_scan)
        controls.addWidget(self._abort_btn)

        controls.addStretch()

        # Summary labels
        self._summary_frame = QFrame()
        self._summary_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        summary_layout = QHBoxLayout(self._summary_frame)
        summary_layout.setSpacing(30)

        self._total_label = QLabel("Modules: --")
        self._responding_label = QLabel("Responding: --")
        self._faults_label = QLabel("With Faults: --")
        self._dtc_label = QLabel("Total DTCs: --")

        for label in [
            self._total_label,
            self._responding_label,
            self._faults_label,
            self._dtc_label,
        ]:
            label.setFont(QFont("Sans", 11))
            summary_layout.addWidget(label)

        controls.addWidget(self._summary_frame)

        layout.addLayout(controls)

        # Progress section
        progress_frame = QFrame()
        progress_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 5px;
                padding: 15px;
            }
        """)
        progress_layout = QVBoxLayout(progress_frame)

        self._progress_label = QLabel("Ready to scan")
        self._progress_label.setFont(QFont("Sans", 11))
        progress_layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimumHeight(25)
        self._progress_bar.setValue(0)
        progress_layout.addWidget(self._progress_bar)

        layout.addWidget(progress_frame)

        # Results table
        self._results_table = QTableWidget()
        self._results_table.setColumnCount(6)
        self._results_table.setHorizontalHeaderLabels(
            ["Module", "Name", "Status", "Faults", "Version", "Time (ms)"]
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                alternate-background-color: #333333;
            }
        """)

        layout.addWidget(self._results_table, 1)

    def _start_scan(self) -> None:
        """Start module scan."""
        if not self._scanner:
            logger.warning("No scanner available")
            return

        self._scan_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._results_table.setRowCount(0)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting scan...")

        # Create and start worker thread
        self._scan_worker = ScanWorker(self._scanner)
        self._scan_worker.progress.connect(self._on_progress)
        self._scan_worker.finished.connect(self._on_scan_complete)
        self._scan_worker.start()

    def _abort_scan(self) -> None:
        """Abort running scan."""
        if self._scanner:
            self._scanner.abort()
        self._abort_btn.setEnabled(False)
        self._progress_label.setText("Aborting...")

    def _on_progress(self, current: int, total: int, module_name: str) -> None:
        """Handle scan progress update."""
        percent = int((current / total) * 100) if total > 0 else 0
        self._progress_bar.setValue(percent)
        self._progress_label.setText(
            f"Scanning {current + 1}/{total}: {module_name}"
        )

    def _on_scan_complete(self, result: ScanResult) -> None:
        """Handle scan completion."""
        self._last_result = result
        self._scan_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)

        if result.aborted:
            self._progress_label.setText("Scan aborted")
        else:
            duration = (
                (result.end_time - result.start_time).total_seconds()
                if result.end_time
                else 0
            )
            self._progress_label.setText(
                f"Scan complete in {duration:.1f} seconds"
            )
            self._progress_bar.setValue(100)

        # Update summary
        self._total_label.setText(f"Modules: {result.total_modules}")
        self._responding_label.setText(f"Responding: {result.responding_modules}")
        self._faults_label.setText(f"With Faults: {result.modules_with_faults}")
        self._dtc_label.setText(f"Total DTCs: {result.total_faults}")

        # Populate table
        self._populate_results(result)

    def _populate_results(self, result: ScanResult) -> None:
        """Populate results table."""
        self._results_table.setRowCount(len(result.modules))

        for row, module in enumerate(result.modules):
            # Module ID
            id_item = QTableWidgetItem(module.module_id)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row, 0, id_item)

            # Name
            name_item = QTableWidgetItem(module.name)
            self._results_table.setItem(row, 1, name_item)

            # Status
            if module.responding:
                if module.has_faults:
                    status_text = "FAULT"
                    status_color = QColor("#cc6600")
                else:
                    status_text = "OK"
                    status_color = QColor("#00cc00")
            else:
                status_text = "NO RESPONSE"
                status_color = QColor("#888888")

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(status_color)
            status_item.setFont(QFont("Sans", 10, QFont.Weight.Bold))
            self._results_table.setItem(row, 2, status_item)

            # Fault count
            fault_item = QTableWidgetItem(
                str(module.fault_count) if module.responding else "-"
            )
            fault_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if module.fault_count > 0:
                fault_item.setForeground(QColor("#cc6600"))
            self._results_table.setItem(row, 3, fault_item)

            # Version
            version_item = QTableWidgetItem(module.software_version or "-")
            self._results_table.setItem(row, 4, version_item)

            # Time
            time_item = QTableWidgetItem(f"{module.scan_time_ms:.0f}")
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._results_table.setItem(row, 5, time_item)
