"""
Export Page

Session export and report generation.
"""

import json
import platform
import zipfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGroupBox,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QCheckBox,
)
from PyQt6.QtGui import QFont

from e92_pulse.core.vehicle import VehicleProfile
from e92_pulse.core.config import AppConfig
from e92_pulse.core.app_logging import get_logger, get_session_id, get_log_dir

logger = get_logger(__name__)


class ExportPage(QWidget):
    """
    Export Session page.

    Provides:
    - Session summary
    - Export options
    - ZIP creation with logs and reports
    """

    def __init__(
        self,
        profile: VehicleProfile,
        config: AppConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._profile = profile
        self._config = config

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Export Session")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Export diagnostic session data and logs")
        subtitle.setFont(QFont("Sans", 12))
        subtitle.setStyleSheet("color: #888888;")
        layout.addWidget(subtitle)

        # Main content
        content_layout = QHBoxLayout()
        content_layout.setSpacing(30)

        # Left side - Session summary
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
            }
        """)
        summary_layout = QVBoxLayout(summary_frame)

        summary_title = QLabel("Session Summary")
        summary_title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        summary_layout.addWidget(summary_title)

        # Session info
        session_group = QGroupBox("Session Information")
        session_layout = QVBoxLayout(session_group)

        self._session_info = QTextEdit()
        self._session_info.setReadOnly(True)
        self._session_info.setMaximumHeight(200)
        self._session_info.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: none;
            }
        """)
        session_layout.addWidget(self._session_info)

        summary_layout.addWidget(session_group)

        # Vehicle info
        vehicle_group = QGroupBox("Vehicle Profile")
        vehicle_layout = QVBoxLayout(vehicle_group)

        self._vehicle_info = QTextEdit()
        self._vehicle_info.setReadOnly(True)
        self._vehicle_info.setMaximumHeight(150)
        self._vehicle_info.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: none;
            }
        """)
        vehicle_layout.addWidget(self._vehicle_info)

        summary_layout.addWidget(vehicle_group)

        # Fault summary
        fault_group = QGroupBox("Fault Summary")
        fault_layout = QVBoxLayout(fault_group)

        self._fault_info = QTextEdit()
        self._fault_info.setReadOnly(True)
        self._fault_info.setMaximumHeight(150)
        self._fault_info.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: none;
            }
        """)
        fault_layout.addWidget(self._fault_info)

        summary_layout.addWidget(fault_group)
        summary_layout.addStretch()

        content_layout.addWidget(summary_frame, 1)

        # Right side - Export options
        export_frame = QFrame()
        export_frame.setFixedWidth(350)
        export_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 10px;
            }
        """)
        export_layout = QVBoxLayout(export_frame)

        export_title = QLabel("Export Options")
        export_title.setFont(QFont("Sans", 14, QFont.Weight.Bold))
        export_layout.addWidget(export_title)

        # Include options
        options_group = QGroupBox("Include in Export")
        options_layout = QVBoxLayout(options_group)

        self._include_logs = QCheckBox("Session logs (JSONL)")
        self._include_logs.setChecked(True)
        options_layout.addWidget(self._include_logs)

        self._include_profile = QCheckBox("Vehicle profile")
        self._include_profile.setChecked(True)
        options_layout.addWidget(self._include_profile)

        self._include_dtcs = QCheckBox("DTC report")
        self._include_dtcs.setChecked(True)
        options_layout.addWidget(self._include_dtcs)

        self._include_system = QCheckBox("System information")
        self._include_system.setChecked(True)
        options_layout.addWidget(self._include_system)

        self._include_services = QCheckBox("Service history")
        self._include_services.setChecked(True)
        options_layout.addWidget(self._include_services)

        export_layout.addWidget(options_group)

        # Privacy notice
        privacy_frame = QFrame()
        privacy_frame.setStyleSheet("""
            QFrame {
                background-color: #334455;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        privacy_layout = QVBoxLayout(privacy_frame)
        privacy_label = QLabel(
            "<b>Privacy Note:</b><br>"
            "VIN is masked in exports. No personal data is included. "
            "System info contains only OS/kernel version."
        )
        privacy_label.setWordWrap(True)
        privacy_label.setStyleSheet("font-size: 11px;")
        privacy_layout.addWidget(privacy_label)
        export_layout.addWidget(privacy_frame)

        export_layout.addSpacing(20)

        # Export buttons
        self._export_zip_btn = QPushButton("Export as ZIP")
        self._export_zip_btn.setMinimumHeight(50)
        self._export_zip_btn.setFont(QFont("Sans", 12, QFont.Weight.Bold))
        self._export_zip_btn.clicked.connect(self._export_zip)
        export_layout.addWidget(self._export_zip_btn)

        self._export_json_btn = QPushButton("Export as JSON")
        self._export_json_btn.setMinimumHeight(40)
        self._export_json_btn.clicked.connect(self._export_json)
        export_layout.addWidget(self._export_json_btn)

        self._open_logs_btn = QPushButton("Open Logs Folder")
        self._open_logs_btn.setMinimumHeight(40)
        self._open_logs_btn.setStyleSheet("""
            QPushButton {
                background-color: #444444;
            }
            QPushButton:hover {
                background-color: #555555;
            }
        """)
        self._open_logs_btn.clicked.connect(self._open_logs_folder)
        export_layout.addWidget(self._open_logs_btn)

        export_layout.addStretch()

        content_layout.addWidget(export_frame)

        layout.addLayout(content_layout, 1)

        # Refresh summary
        self._refresh_summary()

    def showEvent(self, event) -> None:
        """Handle page show event."""
        super().showEvent(event)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Refresh the session summary."""
        # Session info
        session_text = f"""
<b>Session ID:</b> {get_session_id()}<br>
<b>Started:</b> {self._profile.session_start.strftime('%Y-%m-%d %H:%M:%S')}<br>
<b>Log Directory:</b> {get_log_dir()}<br>
<b>Mode:</b> {'Simulation' if self._config.simulation_mode else 'Live'}<br>
"""
        self._session_info.setHtml(session_text)

        # Vehicle info
        vehicle_text = f"""
<b>Series:</b> {self._profile.series.value}<br>
<b>Engine:</b> {self._profile.engine.value}<br>
<b>Scan Complete:</b> {'Yes' if self._profile.scan_complete else 'No'}<br>
<b>Modules Found:</b> {len(self._profile.modules)}<br>
"""
        self._vehicle_info.setHtml(vehicle_text)

        # Fault summary
        summary = self._profile.get_fault_summary()
        fault_text = f"""
<b>Total Modules:</b> {summary['total_modules']}<br>
<b>Responding:</b> {summary['modules_responding']}<br>
<b>With Faults:</b> {summary['modules_with_faults']}<br>
<b>Total DTCs:</b> {summary['total_dtcs']}<br>
<b>Active DTCs:</b> {summary['active_dtcs']}<br>
<b>Stored DTCs:</b> {summary['stored_dtcs']}<br>
"""
        self._fault_info.setHtml(fault_text)

    def _export_zip(self) -> None:
        """Export session as ZIP file."""
        default_name = f"e92_pulse_session_{get_session_id()}.zip"

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Session",
            default_name,
            "ZIP Files (*.zip)",
        )

        if not filename:
            return

        try:
            with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zf:
                # Session manifest
                manifest = {
                    "export_time": datetime.now().isoformat(),
                    "session_id": get_session_id(),
                    "app_version": "0.1.0",
                    "contents": [],
                }

                # Logs
                if self._include_logs.isChecked():
                    log_dir = get_log_dir()
                    if log_dir.exists():
                        for log_file in log_dir.glob(f"*{get_session_id()}*"):
                            arcname = f"logs/{log_file.name}"
                            zf.write(log_file, arcname)
                            manifest["contents"].append(arcname)

                # Vehicle profile
                if self._include_profile.isChecked():
                    profile_data = self._profile.to_export_dict()
                    profile_json = json.dumps(profile_data, indent=2)
                    zf.writestr("vehicle_profile.json", profile_json)
                    manifest["contents"].append("vehicle_profile.json")

                # DTC report
                if self._include_dtcs.isChecked():
                    dtc_data = {
                        "export_time": datetime.now().isoformat(),
                        "dtcs": [
                            {
                                "code": d.code,
                                "module": d.module_id,
                                "status": d.status,
                                "description": d.description,
                            }
                            for d in self._profile.dtcs
                        ],
                    }
                    zf.writestr("dtc_report.json", json.dumps(dtc_data, indent=2))
                    manifest["contents"].append("dtc_report.json")

                # System info
                if self._include_system.isChecked():
                    system_data = {
                        "os": platform.system(),
                        "os_version": platform.release(),
                        "python_version": platform.python_version(),
                        "machine": platform.machine(),
                    }
                    zf.writestr("system_info.json", json.dumps(system_data, indent=2))
                    manifest["contents"].append("system_info.json")

                # Service history
                if self._include_services.isChecked():
                    services_data = {
                        "services": [
                            {
                                "name": s.service_name,
                                "module": s.module_id,
                                "timestamp": s.timestamp.isoformat(),
                                "success": s.success,
                                "details": s.details,
                            }
                            for s in self._profile.service_history
                        ],
                    }
                    zf.writestr("service_history.json", json.dumps(services_data, indent=2))
                    manifest["contents"].append("service_history.json")

                # Write manifest
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            QMessageBox.information(
                self,
                "Export Complete",
                f"Session exported to:\n{filename}",
            )

            logger.info(f"Session exported to {filename}")

        except Exception as e:
            logger.error(f"Export failed: {e}")
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Failed to export session:\n{e}",
            )

    def _export_json(self) -> None:
        """Export session as JSON file."""
        default_name = f"e92_pulse_session_{get_session_id()}.json"

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Session",
            default_name,
            "JSON Files (*.json)",
        )

        if not filename:
            return

        try:
            data = {
                "export_time": datetime.now().isoformat(),
                "session_id": get_session_id(),
                "app_version": "0.1.0",
                "vehicle": self._profile.to_export_dict(),
            }

            if self._include_system.isChecked():
                data["system"] = {
                    "os": platform.system(),
                    "os_version": platform.release(),
                    "python_version": platform.python_version(),
                }

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            QMessageBox.information(
                self,
                "Export Complete",
                f"Session exported to:\n{filename}",
            )

        except Exception as e:
            logger.error(f"Export failed: {e}")
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Failed to export session:\n{e}",
            )

    def _open_logs_folder(self) -> None:
        """Open the logs folder in file manager."""
        import subprocess

        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(["xdg-open", str(log_dir)], check=True)
        except Exception as e:
            QMessageBox.information(
                self,
                "Logs Folder",
                f"Logs are stored in:\n{log_dir}",
            )
