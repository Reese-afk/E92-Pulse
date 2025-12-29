"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Full-featured diagnostic application
"""
import sys
import subprocess

import can

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame,
    QComboBox, QGroupBox, QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# BMW E92 M3 ECU addresses (UDS diagnostic addresses)
ECU_LIST = {
    0x12: "DME (Engine)",
    0x18: "EGS (Transmission)",
    0x00: "ZGM (Gateway)",
    0x40: "KOMBI (Instrument Cluster)",
    0x60: "CAS (Car Access System)",
    0x6C: "DSC (Stability Control)",
    0x6F: "FRM (Footwell Module)",  # Critical for lights/windows
    0x72: "EPS (Power Steering)",
    0x78: "SZL (Steering Column)",
    0x80: "MFL (Steering Wheel)",
    0xA0: "IHKA (Climate Control)",
    0xA4: "SHD (Sunroof)",
    0xB0: "PDC (Park Distance)",
    0xB8: "JBE (Junction Box)",
    0xBF: "RLS (Rain/Light Sensor)",
    0xE0: "CIC/CCC (iDrive)",
    0xED: "TEL (Bluetooth/Phone)",
}

# Common BMW DTC descriptions
DTC_DESCRIPTIONS = {
    # DME codes
    0x0100: "Mass Air Flow Circuit Malfunction",
    0x0101: "Mass Air Flow Circuit Range/Performance",
    0x0102: "Mass Air Flow Circuit Low Input",
    0x0103: "Mass Air Flow Circuit High Input",
    0x0110: "Intake Air Temperature Circuit Malfunction",
    0x0115: "Engine Coolant Temperature Circuit Malfunction",
    0x0120: "Throttle Position Sensor Circuit Malfunction",
    0x0130: "O2 Sensor Circuit Malfunction (Bank 1 Sensor 1)",
    0x0135: "O2 Sensor Heater Circuit Malfunction (Bank 1 Sensor 1)",
    0x0150: "O2 Sensor Circuit Malfunction (Bank 2 Sensor 1)",
    0x0171: "System Too Lean (Bank 1)",
    0x0172: "System Too Rich (Bank 1)",
    0x0174: "System Too Lean (Bank 2)",
    0x0175: "System Too Rich (Bank 2)",
    0x0300: "Random/Multiple Cylinder Misfire Detected",
    0x0301: "Cylinder 1 Misfire Detected",
    0x0302: "Cylinder 2 Misfire Detected",
    0x0303: "Cylinder 3 Misfire Detected",
    0x0304: "Cylinder 4 Misfire Detected",
    0x0305: "Cylinder 5 Misfire Detected",
    0x0306: "Cylinder 6 Misfire Detected",
    0x0307: "Cylinder 7 Misfire Detected",
    0x0308: "Cylinder 8 Misfire Detected",
    0x0420: "Catalyst System Efficiency Below Threshold (Bank 1)",
    0x0430: "Catalyst System Efficiency Below Threshold (Bank 2)",
    0x0440: "Evaporative Emission Control System Malfunction",
    0x0500: "Vehicle Speed Sensor Malfunction",
    # FRM codes
    0x9CA0: "FRM: Footwell Module Internal Error",
    0x9CA1: "FRM: Communication Error",
    0x9CA2: "FRM: Light Circuit Malfunction",
    # DSC codes
    0x5DE0: "DSC: Wheel Speed Sensor Error",
    0x5DF0: "DSC: Yaw Rate Sensor Error",
    # Generic
    0xE000: "Internal Control Module Memory Error",
}

# Service reset types
SERVICE_RESETS = {
    "oil": {"name": "Engine Oil Service", "id": 0x01},
    "brake_front": {"name": "Front Brake Pads", "id": 0x06},
    "brake_rear": {"name": "Rear Brake Pads", "id": 0x07},
    "brake_fluid": {"name": "Brake Fluid", "id": 0x02},
    "spark_plugs": {"name": "Spark Plugs", "id": 0x0A},
    "coolant": {"name": "Coolant", "id": 0x0B},
    "inspection": {"name": "Vehicle Inspection", "id": 0x08},
    "air_filter": {"name": "Air Filter", "id": 0x0C},
}


def detect_usb_adapters():
    """Detect USB CAN adapters."""
    adapters = []
    usb_info = []

    try:
        result = subprocess.run(["ip", "link", "show"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'can' in line.lower():
                parts = line.split(':')
                if len(parts) >= 2:
                    name = parts[1].strip().split('@')[0].strip()
                    if name.startswith('can') or name.startswith('vcan'):
                        adapters.append(name)
    except Exception:
        pass

    try:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            line_lower = line.lower()
            if any(x in line_lower for x in ['can', 'innomaker', 'canable', 'peak', '1d50:606f', 'geschwister']):
                usb_info.append(line.strip())
    except Exception:
        pass

    return adapters, usb_info


class CANWorker(QThread):
    """Worker thread for CAN operations."""
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, operation, interface, params=None):
        super().__init__()
        self.operation = operation
        self.interface = interface
        self.params = params or {}

    def run(self):
        try:
            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            if self.operation == "scan":
                results = self._scan_ecus(bus)
            elif self.operation == "read_vin":
                results = self._read_vin(bus)
            elif self.operation == "read_dtc":
                results = self._read_dtcs(bus, self.params.get("ecu_addr"))
            elif self.operation == "clear_dtc":
                results = self._clear_dtcs(bus, self.params.get("ecu_addr"))
            elif self.operation == "reset_ecu":
                results = self._reset_ecu(bus, self.params.get("ecu_addr"), self.params.get("reset_type", 0x01))
            elif self.operation == "battery_reset":
                results = self._battery_registration(bus)
            elif self.operation == "service_reset":
                results = self._service_reset(bus, self.params.get("service_id"))
            else:
                results = {"error": "Unknown operation"}

            bus.shutdown()
            self.finished.emit(results)

        except Exception as e:
            self.finished.emit({"error": str(e)})

    def _send_uds(self, bus, ecu_addr, data, timeout=0.5):
        """Send UDS message and get response."""
        tx_id = 0x600 + ecu_addr
        rx_id = 0x600 + ecu_addr + 8

        # Pad data to 8 bytes
        padded = list(data) + [0x00] * (8 - len(data))

        msg = can.Message(arbitration_id=tx_id, data=padded, is_extended_id=False)
        bus.send(msg)

        response = bus.recv(timeout=timeout)
        if response and response.arbitration_id == rx_id:
            return list(response.data)
        return None

    def _scan_ecus(self, bus):
        """Scan for ECUs using TesterPresent."""
        found = {}
        responding = 0

        for addr, name in ECU_LIST.items():
            self.progress.emit(f"Scanning {name}...")

            # TesterPresent (0x3E 0x00)
            response = self._send_uds(bus, addr, [0x02, 0x3E, 0x00], timeout=0.2)

            if response and response[1] == 0x7E:  # Positive response
                found[addr] = {"name": name, "status": "OK"}
                responding += 1
            else:
                found[addr] = {"name": name, "status": "No Response"}

        return {"ecus": found, "responding": responding}

    def _read_vin(self, bus):
        """Read VIN from vehicle."""
        for ecu_addr in [0x60, 0x40, 0x12]:  # CAS, KOMBI, DME
            try:
                # ReadDataByIdentifier - VIN (0xF190)
                response = self._send_uds(bus, ecu_addr, [0x03, 0x22, 0xF1, 0x90], timeout=0.5)

                if response and response[1] == 0x62:  # Positive response
                    vin_bytes = response[4:8]

                    # Get remaining bytes (multi-frame)
                    for _ in range(3):
                        extra = bus.recv(timeout=0.2)
                        if extra:
                            vin_bytes.extend(extra.data[1:])

                    vin = ''.join(chr(b) for b in vin_bytes[:17] if 32 <= b <= 126)
                    if len(vin) >= 10:
                        return {"vin": vin}
            except Exception:
                continue

        return {"vin": None}

    def _read_dtcs(self, bus, ecu_addr=None):
        """Read DTCs from ECU(s)."""
        dtcs = []

        ecus_to_scan = {ecu_addr: ECU_LIST.get(ecu_addr, "Unknown")} if ecu_addr is not None else ECU_LIST

        for addr, name in ecus_to_scan.items():
            self.progress.emit(f"Reading DTCs from {name}...")

            # ReadDTCByStatusMask (0x19 0x02 0xFF)
            response = self._send_uds(bus, addr, [0x04, 0x19, 0x02, 0xFF, 0x00], timeout=0.5)

            if response and response[1] == 0x59:  # Positive response
                # Parse DTCs from response
                # Format: 59 02 FF [DTC1_HIGH DTC1_LOW STATUS] [DTC2...]
                dtc_data = response[4:]

                # Try to get more frames
                for _ in range(5):
                    extra = bus.recv(timeout=0.2)
                    if extra:
                        dtc_data.extend(extra.data[1:])
                    else:
                        break

                # Parse DTC triplets
                i = 0
                while i + 2 < len(dtc_data):
                    dtc_high = dtc_data[i]
                    dtc_low = dtc_data[i+1]
                    status = dtc_data[i+2]

                    if dtc_high == 0 and dtc_low == 0:
                        break

                    dtc_code = (dtc_high << 8) | dtc_low
                    dtc_str = f"P{dtc_code:04X}"

                    description = DTC_DESCRIPTIONS.get(dtc_code, "Unknown fault")

                    dtcs.append({
                        "ecu": name,
                        "ecu_addr": addr,
                        "code": dtc_str,
                        "raw": dtc_code,
                        "status": status,
                        "description": description
                    })
                    i += 3
            elif response is None:
                dtcs.append({
                    "ecu": name,
                    "ecu_addr": addr,
                    "code": "NO_RESPONSE",
                    "description": "ECU did not respond"
                })

        return {"dtcs": dtcs}

    def _clear_dtcs(self, bus, ecu_addr=None):
        """Clear DTCs from ECU(s)."""
        cleared = 0
        failed = 0

        ecus_to_clear = {ecu_addr: ECU_LIST.get(ecu_addr, "Unknown")} if ecu_addr is not None else ECU_LIST

        for addr, name in ecus_to_clear.items():
            self.progress.emit(f"Clearing DTCs from {name}...")

            # ClearDiagnosticInformation (0x14 0xFF 0xFF 0xFF)
            response = self._send_uds(bus, addr, [0x04, 0x14, 0xFF, 0xFF, 0xFF], timeout=0.5)

            if response and response[1] == 0x54:  # Positive response
                cleared += 1
            else:
                failed += 1

        return {"cleared": cleared, "failed": failed}

    def _reset_ecu(self, bus, ecu_addr, reset_type=0x01):
        """Reset ECU using UDS ECUReset service.

        Reset types:
        0x01 = Hard Reset (power cycle simulation)
        0x02 = Key Off/On Reset
        0x03 = Soft Reset (restart software)
        """
        name = ECU_LIST.get(ecu_addr, f"ECU 0x{ecu_addr:02X}")
        self.progress.emit(f"Resetting {name}...")

        # ECUReset (0x11 [resetType])
        response = self._send_uds(bus, ecu_addr, [0x02, 0x11, reset_type], timeout=1.0)

        if response and response[1] == 0x51:  # Positive response
            return {"success": True, "ecu": name}
        elif response and response[1] == 0x7F:  # Negative response
            nrc = response[3] if len(response) > 3 else 0
            nrc_desc = {
                0x12: "Sub-function not supported",
                0x13: "Incorrect message length",
                0x22: "Conditions not correct",
                0x33: "Security access denied",
            }.get(nrc, f"Unknown error (0x{nrc:02X})")
            return {"success": False, "ecu": name, "error": nrc_desc}
        else:
            return {"success": False, "ecu": name, "error": "No response"}

    def _battery_registration(self, bus):
        """Perform battery registration (IBS reset).

        This tells the car a new battery was installed so it can
        recalibrate charging and power management.
        """
        self.progress.emit("Registering new battery...")

        # Battery registration is done through the DME (0x12) or JBE (0xB8)
        # Using routine control to reset IBS (Intelligent Battery Sensor)

        results = []

        # Method 1: Reset IBS via DME
        self.progress.emit("Resetting IBS via DME...")
        response = self._send_uds(bus, 0x12, [0x04, 0x31, 0x01, 0x20, 0x00], timeout=1.0)
        if response and response[1] == 0x71:
            results.append("DME: Battery registration successful")

        # Method 2: Reset power management via JBE
        self.progress.emit("Resetting power management via JBE...")
        response = self._send_uds(bus, 0xB8, [0x04, 0x31, 0x01, 0x20, 0x00], timeout=1.0)
        if response and response[1] == 0x71:
            results.append("JBE: Power management reset successful")

        # Method 3: Clear adaptation values
        self.progress.emit("Clearing battery adaptation...")
        response = self._send_uds(bus, 0x12, [0x04, 0x31, 0x01, 0x10, 0x00], timeout=1.0)
        if response and response[1] == 0x71:
            results.append("Battery adaptation cleared")

        if results:
            return {"success": True, "results": results}
        else:
            return {"success": False, "error": "Battery registration failed - try with ignition ON, engine OFF"}

    def _service_reset(self, bus, service_id):
        """Reset service indicator.

        Service reset is done through the KOMBI (instrument cluster).
        """
        service_name = next((v["name"] for v in SERVICE_RESETS.values() if v["id"] == service_id), f"Service 0x{service_id:02X}")
        self.progress.emit(f"Resetting {service_name}...")

        # Service reset via KOMBI (0x40)
        # RoutineControl - Start Routine (0x31 0x01 [service_id])
        response = self._send_uds(bus, 0x40, [0x04, 0x31, 0x01, service_id, 0x00], timeout=1.0)

        if response and response[1] == 0x71:
            return {"success": True, "service": service_name}
        elif response and response[1] == 0x7F:
            nrc = response[3] if len(response) > 3 else 0
            return {"success": False, "service": service_name, "error": f"Rejected (0x{nrc:02X})"}
        else:
            return {"success": False, "service": service_name, "error": "No response"}


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("E92 Pulse - BMW E92 M3 Diagnostics")
        self.setMinimumSize(1100, 700)

        self.interface = None
        self.worker = None
        self.connected = False
        self.vehicle_vin = None
        self.found_ecus = {}

        self._setup_ui()
        self._apply_style()

        QTimer.singleShot(500, self.detect_adapter)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1e1e1e; color: #ffffff; font-family: sans-serif; }
            QPushButton { background-color: #0066cc; color: white; border: none; padding: 10px 20px; font-size: 13px; border-radius: 4px; }
            QPushButton:hover { background-color: #0077ee; }
            QPushButton:disabled { background-color: #444; color: #888; }
            QPushButton#danger { background-color: #cc3333; }
            QPushButton#danger:hover { background-color: #ee4444; }
            QPushButton#success { background-color: #00aa44; }
            QPushButton#success:hover { background-color: #00cc55; }
            QPushButton#warning { background-color: #cc8800; }
            QPushButton#warning:hover { background-color: #ee9900; }
            QTextEdit, QComboBox { background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px; padding: 5px; }
            QComboBox::drop-down { border: none; width: 20px; }
            QTableWidget { background-color: #2d2d2d; border: 1px solid #444; gridline-color: #444; }
            QHeaderView::section { background-color: #383838; padding: 8px; border: none; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { background-color: #2d2d2d; padding: 10px 20px; border: 1px solid #444; }
            QTabBar::tab:selected { background-color: #0066cc; }
            QProgressBar { background-color: #2d2d2d; border: none; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #0066cc; }
            QFrame#sidebar { background-color: #252525; border-right: 1px solid #333; }
            QGroupBox { border: 1px solid #444; border-radius: 4px; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QSpinBox { background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px; padding: 5px; }
        """)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        # Main content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        tabs = QTabWidget()
        tabs.addTab(self._create_scan_tab(), "Scan ECUs")
        tabs.addTab(self._create_dtc_tab(), "Fault Codes")
        tabs.addTab(self._create_reset_tab(), "Reset / Service")
        tabs.addTab(self._create_log_tab(), "Log")

        content_layout.addWidget(tabs)
        main_layout.addWidget(content, 1)

    def _create_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 20, 15, 20)
        layout.setSpacing(10)

        logo = QLabel("E92 Pulse")
        logo.setFont(QFont("sans-serif", 20, QFont.Weight.Bold))
        logo.setStyleSheet("color: #00aaff;")
        layout.addWidget(logo)

        layout.addWidget(QLabel("BMW E92 M3"))

        layout.addSpacing(20)

        layout.addWidget(QLabel("Connection"))
        self.adapter_label = QLabel("No adapter")
        self.adapter_label.setStyleSheet("color: #cc6600;")
        layout.addWidget(self.adapter_label)

        self.conn_status = QLabel("Disconnected")
        self.conn_status.setStyleSheet("color: #cc0000;")
        layout.addWidget(self.conn_status)

        layout.addSpacing(15)

        layout.addWidget(QLabel("Vehicle"))
        self.vin_label = QLabel("VIN: --")
        self.vin_label.setStyleSheet("font-size: 10px;")
        self.vin_label.setWordWrap(True)
        layout.addWidget(self.vin_label)

        self.ecus_label = QLabel("ECUs: --")
        layout.addWidget(self.ecus_label)

        layout.addSpacing(20)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_vehicle)
        self.connect_btn.setEnabled(False)
        layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("danger")
        self.disconnect_btn.clicked.connect(self.disconnect_vehicle)
        self.disconnect_btn.hide()
        layout.addWidget(self.disconnect_btn)

        layout.addStretch()

        self.detect_btn = QPushButton("Detect Adapter")
        self.detect_btn.clicked.connect(self.detect_adapter)
        layout.addWidget(self.detect_btn)

        return sidebar

    def _create_scan_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Scan All ECUs")
        self.scan_btn.clicked.connect(self.scan_ecus)
        self.scan_btn.setEnabled(False)
        btn_layout.addWidget(self.scan_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.progress = QProgressBar()
        self.progress.setMinimumHeight(25)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.ecu_table = QTableWidget()
        self.ecu_table.setColumnCount(3)
        self.ecu_table.setHorizontalHeaderLabels(["ECU Module", "Address", "Status"])
        self.ecu_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.ecu_table)

        return tab

    def _create_dtc_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ECU selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("ECU:"))
        self.dtc_ecu_combo = QComboBox()
        self.dtc_ecu_combo.addItem("All ECUs", None)
        for addr, name in ECU_LIST.items():
            self.dtc_ecu_combo.addItem(f"{name} (0x{addr:02X})", addr)
        self.dtc_ecu_combo.setMinimumWidth(250)
        selector_layout.addWidget(self.dtc_ecu_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)

        btn_layout = QHBoxLayout()
        self.read_dtc_btn = QPushButton("Read DTCs")
        self.read_dtc_btn.clicked.connect(self.read_dtcs)
        self.read_dtc_btn.setEnabled(False)
        btn_layout.addWidget(self.read_dtc_btn)

        self.clear_dtc_btn = QPushButton("Clear DTCs")
        self.clear_dtc_btn.setObjectName("danger")
        self.clear_dtc_btn.clicked.connect(self.clear_dtcs)
        self.clear_dtc_btn.setEnabled(False)
        btn_layout.addWidget(self.clear_dtc_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # DTC table
        self.dtc_table = QTableWidget()
        self.dtc_table.setColumnCount(4)
        self.dtc_table.setHorizontalHeaderLabels(["ECU", "Code", "Status", "Description"])
        self.dtc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.dtc_table.setColumnWidth(0, 150)
        self.dtc_table.setColumnWidth(1, 80)
        self.dtc_table.setColumnWidth(2, 80)
        layout.addWidget(self.dtc_table)

        return tab

    def _create_reset_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ECU Reset section
        reset_group = QGroupBox("ECU Reset")
        reset_layout = QVBoxLayout(reset_group)

        ecu_reset_row = QHBoxLayout()
        ecu_reset_row.addWidget(QLabel("ECU:"))
        self.reset_ecu_combo = QComboBox()
        self.reset_ecu_combo.addItem("FRM (Footwell Module)", 0x6F)  # FRM first - most common
        for addr, name in ECU_LIST.items():
            if addr != 0x6F:  # Skip FRM since it's already added
                self.reset_ecu_combo.addItem(f"{name}", addr)
        self.reset_ecu_combo.setMinimumWidth(250)
        ecu_reset_row.addWidget(self.reset_ecu_combo)

        ecu_reset_row.addWidget(QLabel("Type:"))
        self.reset_type_combo = QComboBox()
        self.reset_type_combo.addItem("Soft Reset (0x03)", 0x03)
        self.reset_type_combo.addItem("Key Off/On (0x02)", 0x02)
        self.reset_type_combo.addItem("Hard Reset (0x01)", 0x01)
        ecu_reset_row.addWidget(self.reset_type_combo)

        self.reset_ecu_btn = QPushButton("Reset ECU")
        self.reset_ecu_btn.setObjectName("warning")
        self.reset_ecu_btn.clicked.connect(self.reset_ecu)
        self.reset_ecu_btn.setEnabled(False)
        ecu_reset_row.addWidget(self.reset_ecu_btn)

        ecu_reset_row.addStretch()
        reset_layout.addLayout(ecu_reset_row)

        layout.addWidget(reset_group)

        # Battery Registration section
        battery_group = QGroupBox("Battery Registration")
        battery_layout = QVBoxLayout(battery_group)

        battery_info = QLabel("Use after replacing the battery to reset the IBS sensor and power management.")
        battery_info.setStyleSheet("color: #888;")
        battery_info.setWordWrap(True)
        battery_layout.addWidget(battery_info)

        self.battery_btn = QPushButton("Register New Battery")
        self.battery_btn.setObjectName("success")
        self.battery_btn.clicked.connect(self.battery_registration)
        self.battery_btn.setEnabled(False)
        battery_layout.addWidget(self.battery_btn)

        layout.addWidget(battery_group)

        # Service Reset section
        service_group = QGroupBox("Service Reset")
        service_layout = QVBoxLayout(service_group)

        service_row = QHBoxLayout()
        service_row.addWidget(QLabel("Service:"))
        self.service_combo = QComboBox()
        for key, info in SERVICE_RESETS.items():
            self.service_combo.addItem(info["name"], info["id"])
        self.service_combo.setMinimumWidth(200)
        service_row.addWidget(self.service_combo)

        self.service_btn = QPushButton("Reset Service")
        self.service_btn.setObjectName("success")
        self.service_btn.clicked.connect(self.service_reset)
        self.service_btn.setEnabled(False)
        service_row.addWidget(self.service_btn)

        service_row.addStretch()
        service_layout.addLayout(service_row)

        layout.addWidget(service_group)

        # Status output
        self.reset_output = QTextEdit()
        self.reset_output.setReadOnly(True)
        self.reset_output.setMaximumHeight(150)
        layout.addWidget(self.reset_output)

        layout.addStretch()

        return tab

    def _create_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(lambda: self.log_output.clear())
        layout.addWidget(clear_btn)

        return tab

    def log(self, msg):
        self.log_output.append(msg)

    def detect_adapter(self):
        self.log("Detecting USB CAN adapters...")
        adapters, usb_info = detect_usb_adapters()

        for info in usb_info:
            self.log(f"  USB: {info}")

        if adapters:
            self.interface = adapters[0]
            self.adapter_label.setText(self.interface)
            self.adapter_label.setStyleSheet("color: #00cc00;")
            self.connect_btn.setEnabled(True)
            self.log(f"Found: {self.interface}")
        else:
            self.adapter_label.setText("No adapter")
            self.adapter_label.setStyleSheet("color: #cc6600;")
            self.log("No CAN interface found")

    def connect_vehicle(self):
        if not self.interface:
            return

        self.log("Connecting to vehicle...")
        self.connect_btn.setEnabled(False)

        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_connect_complete)
        self.worker.start()

    def _on_connect_complete(self, results):
        if "error" in results:
            self.log(f"Error: {results['error']}")
            self.connect_btn.setEnabled(True)
            QMessageBox.warning(self, "Connection Failed", results['error'])
            return

        responding = results.get("responding", 0)
        self.found_ecus = results.get("ecus", {})

        if responding > 0:
            self.connected = True
            self.conn_status.setText("Connected")
            self.conn_status.setStyleSheet("color: #00cc00;")
            self.ecus_label.setText(f"ECUs: {responding} online")

            self.connect_btn.hide()
            self.disconnect_btn.show()

            # Enable all controls
            self.scan_btn.setEnabled(True)
            self.read_dtc_btn.setEnabled(True)
            self.clear_dtc_btn.setEnabled(True)
            self.reset_ecu_btn.setEnabled(True)
            self.battery_btn.setEnabled(True)
            self.service_btn.setEnabled(True)

            self.log(f"Connected! {responding} ECUs responding.")

            # Update ECU table
            self._update_ecu_table(self.found_ecus)

            # Read VIN
            self._read_vin()
        else:
            self.log("No ECUs responded. Check ignition and connections.")
            self.connect_btn.setEnabled(True)
            QMessageBox.warning(self, "No Response", "No ECUs responded.\n\nCheck:\n- Ignition ON\n- OBD cable connected\n- CAN interface up")

    def _update_ecu_table(self, ecus):
        self.ecu_table.setRowCount(0)
        for addr, info in ecus.items():
            row = self.ecu_table.rowCount()
            self.ecu_table.insertRow(row)
            self.ecu_table.setItem(row, 0, QTableWidgetItem(info["name"]))
            self.ecu_table.setItem(row, 1, QTableWidgetItem(f"0x{addr:02X}"))
            status_item = QTableWidgetItem(info["status"])
            status_item.setForeground(QColor("#00cc00" if info["status"] == "OK" else "#cc0000"))
            self.ecu_table.setItem(row, 2, status_item)

    def _read_vin(self):
        self.worker = CANWorker("read_vin", self.interface)
        self.worker.finished.connect(self._on_vin_complete)
        self.worker.start()

    def _on_vin_complete(self, results):
        vin = results.get("vin")
        if vin:
            self.vin_label.setText(f"VIN: {vin}")
            self.log(f"VIN: {vin}")
        else:
            self.vin_label.setText("VIN: --")

    def disconnect_vehicle(self):
        self.connected = False
        self.conn_status.setText("Disconnected")
        self.conn_status.setStyleSheet("color: #cc0000;")
        self.ecus_label.setText("ECUs: --")
        self.vin_label.setText("VIN: --")
        self.found_ecus = {}

        self.disconnect_btn.hide()
        self.connect_btn.show()
        self.connect_btn.setEnabled(True)

        self.scan_btn.setEnabled(False)
        self.read_dtc_btn.setEnabled(False)
        self.clear_dtc_btn.setEnabled(False)
        self.reset_ecu_btn.setEnabled(False)
        self.battery_btn.setEnabled(False)
        self.service_btn.setEnabled(False)

        self.ecu_table.setRowCount(0)
        self.dtc_table.setRowCount(0)
        self.log("Disconnected.")

    def scan_ecus(self):
        self.scan_btn.setEnabled(False)
        self.progress.show()
        self.log("Scanning ECUs...")

        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_scan_complete)
        self.worker.start()

    def _on_scan_complete(self, results):
        self.progress.hide()
        self.scan_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        self.found_ecus = results.get("ecus", {})
        responding = results.get("responding", 0)
        self._update_ecu_table(self.found_ecus)
        self.ecus_label.setText(f"ECUs: {responding} online")
        self.log(f"Scan complete. {responding} responding.")

    def read_dtcs(self):
        ecu_addr = self.dtc_ecu_combo.currentData()
        self.read_dtc_btn.setEnabled(False)
        self.dtc_table.setRowCount(0)
        self.log(f"Reading DTCs...")

        self.worker = CANWorker("read_dtc", self.interface, {"ecu_addr": ecu_addr})
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_dtc_read_complete)
        self.worker.start()

    def _on_dtc_read_complete(self, results):
        self.read_dtc_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        dtcs = results.get("dtcs", [])
        self.dtc_table.setRowCount(0)

        fault_count = 0
        for dtc in dtcs:
            if dtc.get("code") == "NO_RESPONSE":
                continue

            row = self.dtc_table.rowCount()
            self.dtc_table.insertRow(row)

            self.dtc_table.setItem(row, 0, QTableWidgetItem(dtc.get("ecu", "")))
            self.dtc_table.setItem(row, 1, QTableWidgetItem(dtc.get("code", "")))

            status = dtc.get("status", 0)
            status_text = "Active" if status & 0x01 else "Stored"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#cc0000" if status & 0x01 else "#cc8800"))
            self.dtc_table.setItem(row, 2, status_item)

            self.dtc_table.setItem(row, 3, QTableWidgetItem(dtc.get("description", "")))
            fault_count += 1

        self.log(f"Found {fault_count} fault codes.")

    def clear_dtcs(self):
        ecu_addr = self.dtc_ecu_combo.currentData()
        target = "all ECUs" if ecu_addr is None else ECU_LIST.get(ecu_addr, f"0x{ecu_addr:02X}")

        reply = QMessageBox.question(self, "Confirm", f"Clear all fault codes from {target}?")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.clear_dtc_btn.setEnabled(False)
        self.log(f"Clearing DTCs from {target}...")

        self.worker = CANWorker("clear_dtc", self.interface, {"ecu_addr": ecu_addr})
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_dtc_clear_complete)
        self.worker.start()

    def _on_dtc_clear_complete(self, results):
        self.clear_dtc_btn.setEnabled(True)
        cleared = results.get("cleared", 0)
        self.log(f"Cleared DTCs from {cleared} ECUs.")
        QMessageBox.information(self, "Done", f"Cleared fault codes from {cleared} ECUs")
        self.dtc_table.setRowCount(0)

    def reset_ecu(self):
        ecu_addr = self.reset_ecu_combo.currentData()
        reset_type = self.reset_type_combo.currentData()
        ecu_name = ECU_LIST.get(ecu_addr, f"0x{ecu_addr:02X}")

        reply = QMessageBox.question(self, "Confirm ECU Reset",
            f"Reset {ecu_name}?\n\nThis will restart the module.")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.reset_ecu_btn.setEnabled(False)
        self.reset_output.append(f"Resetting {ecu_name}...")
        self.log(f"Resetting {ecu_name} (type 0x{reset_type:02X})...")

        self.worker = CANWorker("reset_ecu", self.interface, {"ecu_addr": ecu_addr, "reset_type": reset_type})
        self.worker.progress.connect(lambda m: self.reset_output.append(m))
        self.worker.finished.connect(self._on_reset_complete)
        self.worker.start()

    def _on_reset_complete(self, results):
        self.reset_ecu_btn.setEnabled(True)

        if results.get("success"):
            self.reset_output.append(f"✓ {results.get('ecu')} reset successful!")
            self.log(f"ECU reset successful: {results.get('ecu')}")
        else:
            error = results.get("error", "Unknown error")
            self.reset_output.append(f"✗ Reset failed: {error}")
            self.log(f"ECU reset failed: {error}")

    def battery_registration(self):
        reply = QMessageBox.question(self, "Battery Registration",
            "Register new battery?\n\nThis resets the IBS sensor and power management.\n"
            "Use after installing a new battery.")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.battery_btn.setEnabled(False)
        self.reset_output.append("Starting battery registration...")
        self.log("Battery registration started...")

        self.worker = CANWorker("battery_reset", self.interface)
        self.worker.progress.connect(lambda m: self.reset_output.append(m))
        self.worker.finished.connect(self._on_battery_complete)
        self.worker.start()

    def _on_battery_complete(self, results):
        self.battery_btn.setEnabled(True)

        if results.get("success"):
            for msg in results.get("results", []):
                self.reset_output.append(f"✓ {msg}")
            self.log("Battery registration complete!")
            QMessageBox.information(self, "Done", "Battery registration complete!")
        else:
            error = results.get("error", "Unknown error")
            self.reset_output.append(f"✗ {error}")
            self.log(f"Battery registration failed: {error}")

    def service_reset(self):
        service_id = self.service_combo.currentData()
        service_name = self.service_combo.currentText()

        reply = QMessageBox.question(self, "Service Reset",
            f"Reset {service_name}?\n\nThis will reset the service indicator.")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.service_btn.setEnabled(False)
        self.reset_output.append(f"Resetting {service_name}...")
        self.log(f"Service reset: {service_name}...")

        self.worker = CANWorker("service_reset", self.interface, {"service_id": service_id})
        self.worker.progress.connect(lambda m: self.reset_output.append(m))
        self.worker.finished.connect(self._on_service_complete)
        self.worker.start()

    def _on_service_complete(self, results):
        self.service_btn.setEnabled(True)

        if results.get("success"):
            self.reset_output.append(f"✓ {results.get('service')} reset successful!")
            self.log(f"Service reset complete: {results.get('service')}")
            QMessageBox.information(self, "Done", f"{results.get('service')} has been reset!")
        else:
            error = results.get("error", "Unknown error")
            self.reset_output.append(f"✗ Reset failed: {error}")
            self.log(f"Service reset failed: {error}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("E92 Pulse")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
