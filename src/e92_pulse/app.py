"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Single-file application for simplicity
"""
import sys
import subprocess

import can

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# BMW E92 M3 ECU addresses (UDS)
ECU_LIST = {
    0x12: "DME (Engine)",
    0x18: "EGS (Transmission)",
    0x00: "ZGM (Gateway)",
    0x40: "KOMBI (Instrument Cluster)",
    0x60: "CAS (Car Access System)",
    0x6C: "DSC (Stability Control)",
    0x72: "EPS (Power Steering)",
    0x78: "SZL (Steering Column)",
    0xA0: "IHKA (Climate)",
    0xB8: "JBE (Junction Box)",
}


def detect_usb_adapters():
    """Detect USB CAN adapters."""
    adapters = []
    usb_info = []

    # Check for CAN interfaces
    try:
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split('\n'):
            if 'can' in line.lower():
                parts = line.split(':')
                if len(parts) >= 2:
                    name = parts[1].strip().split('@')[0].strip()
                    if name.startswith('can') or name.startswith('vcan'):
                        adapters.append(name)
    except Exception:
        pass

    # Check USB devices
    try:
        result = subprocess.run(
            ["lsusb"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split('\n'):
            line_lower = line.lower()
            if any(x in line_lower for x in ['can', 'innomaker', 'canable', 'peak', 'gs_usb', '1d50:606f', 'geschwister']):
                usb_info.append(line.strip())
    except Exception:
        pass

    return adapters, usb_info


def setup_can_interface(interface="can0", bitrate=500000):
    """Setup CAN interface."""
    try:
        subprocess.run(["sudo", "ip", "link", "set", interface, "down"], capture_output=True, timeout=5)
        subprocess.run(["sudo", "ip", "link", "set", interface, "type", "can", "bitrate", str(bitrate)], capture_output=True, timeout=5)
        result = subprocess.run(["sudo", "ip", "link", "set", interface, "up"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


class CANWorker(QThread):
    """Worker thread for CAN operations."""
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, operation, interface, ecu_address=None):
        super().__init__()
        self.operation = operation
        self.interface = interface
        self.ecu_address = ecu_address

    def run(self):
        try:
            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            if self.operation == "scan":
                results = self._scan_ecus(bus)
            elif self.operation == "read_vin":
                results = self._read_vin(bus)
            elif self.operation == "read_dtc":
                results = self._read_dtcs(bus, self.ecu_address)
            elif self.operation == "clear_dtc":
                results = self._clear_dtcs(bus, self.ecu_address)
            else:
                results = {"error": "Unknown operation"}

            bus.shutdown()
            self.finished.emit(results)

        except Exception as e:
            self.finished.emit({"error": str(e)})

    def _scan_ecus(self, bus):
        """Scan for ECUs."""
        found = {}
        responding = 0

        for addr, name in ECU_LIST.items():
            self.progress.emit(f"Scanning {name}...")

            tx_id = 0x600 + addr
            rx_id = 0x600 + addr + 8

            msg = can.Message(
                arbitration_id=tx_id,
                data=[0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                is_extended_id=False
            )

            try:
                bus.send(msg)
                response = bus.recv(timeout=0.2)
                if response and response.arbitration_id == rx_id:
                    found[addr] = {"name": name, "status": "OK"}
                    responding += 1
                else:
                    found[addr] = {"name": name, "status": "No Response"}
            except Exception:
                found[addr] = {"name": name, "status": "Error"}

        return {"ecus": found, "responding": responding}

    def _read_vin(self, bus):
        """Read VIN from vehicle."""
        # Try to read VIN from CAS (0x60) using UDS ReadDataByIdentifier (0x22) for VIN (0xF190)
        tx_id = 0x6F1  # Diagnostic tester address
        rx_filter = 0x600  # Response base

        # Try different ECUs for VIN
        for ecu_addr in [0x60, 0x40, 0x12]:  # CAS, KOMBI, DME
            try:
                # Read Data By Identifier - VIN (0xF190)
                msg = can.Message(
                    arbitration_id=0x600 + ecu_addr,
                    data=[0x03, 0x22, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00],
                    is_extended_id=False
                )
                bus.send(msg)

                # Collect response (may be multi-frame)
                vin_bytes = []
                for _ in range(5):  # Try to get multiple frames
                    response = bus.recv(timeout=0.3)
                    if response:
                        vin_bytes.extend(response.data[3:])  # Skip header bytes

                if len(vin_bytes) >= 17:
                    vin = ''.join(chr(b) for b in vin_bytes[:17] if 32 <= b <= 126)
                    if len(vin) >= 10:
                        return {"vin": vin, "source": ECU_LIST.get(ecu_addr, "Unknown")}

            except Exception:
                continue

        return {"vin": None, "error": "Could not read VIN"}

    def _read_dtcs(self, bus, addr):
        """Read DTCs from ECU."""
        tx_id = 0x600 + addr
        msg = can.Message(
            arbitration_id=tx_id,
            data=[0x04, 0x19, 0x02, 0xFF, 0x00, 0x00, 0x00, 0x00],
            is_extended_id=False
        )

        try:
            bus.send(msg)
            response = bus.recv(timeout=0.5)
            if response:
                return {"dtcs": list(response.data), "raw": response.data.hex()}
            return {"dtcs": [], "error": "No response"}
        except Exception as e:
            return {"error": str(e)}

    def _clear_dtcs(self, bus, addr):
        """Clear DTCs from ECU."""
        tx_id = 0x600 + addr
        msg = can.Message(
            arbitration_id=tx_id,
            data=[0x04, 0x14, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00],
            is_extended_id=False
        )

        try:
            bus.send(msg)
            response = bus.recv(timeout=0.5)
            if response and len(response.data) > 1 and response.data[1] == 0x54:
                return {"success": True}
            return {"success": False, "error": "No positive response"}
        except Exception as e:
            return {"error": str(e)}


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("E92 Pulse - BMW E92 M3 Diagnostics")
        self.setMinimumSize(1000, 650)

        self.interface = None
        self.worker = None
        self.connected = False
        self.vehicle_vin = None

        self._setup_ui()
        self._apply_style()

        # Auto-detect on startup
        QTimer.singleShot(500, self.detect_adapter)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: sans-serif;
            }
            QPushButton {
                background-color: #0066cc;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 4px;
                min-height: 20px;
            }
            QPushButton:hover { background-color: #0077ee; }
            QPushButton:disabled { background-color: #444; color: #888; }
            QPushButton#danger { background-color: #cc3333; }
            QPushButton#danger:hover { background-color: #ee4444; }
            QPushButton#success { background-color: #00aa44; }
            QTextEdit {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
            }
            QTableWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #383838;
                padding: 8px;
                border: none;
            }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background-color: #2d2d2d;
                padding: 10px 20px;
                border: 1px solid #444;
            }
            QTabBar::tab:selected { background-color: #0066cc; }
            QProgressBar {
                background-color: #2d2d2d;
                border: none;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk { background-color: #0066cc; }
            QFrame#sidebar {
                background-color: #252525;
                border-right: 1px solid #333;
            }
        """)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar with vehicle info
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 20, 15, 20)
        sidebar_layout.setSpacing(10)

        # Logo
        logo = QLabel("E92 Pulse")
        logo.setFont(QFont("sans-serif", 20, QFont.Weight.Bold))
        logo.setStyleSheet("color: #00aaff;")
        sidebar_layout.addWidget(logo)

        model_label = QLabel("BMW E92 M3")
        model_label.setStyleSheet("color: #888;")
        sidebar_layout.addWidget(model_label)

        sidebar_layout.addSpacing(20)

        # Connection status
        conn_title = QLabel("Connection")
        conn_title.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
        sidebar_layout.addWidget(conn_title)

        self.adapter_label = QLabel("No adapter")
        self.adapter_label.setStyleSheet("color: #cc6600;")
        sidebar_layout.addWidget(self.adapter_label)

        self.conn_status = QLabel("Disconnected")
        self.conn_status.setStyleSheet("color: #cc0000;")
        sidebar_layout.addWidget(self.conn_status)

        sidebar_layout.addSpacing(20)

        # Vehicle info
        vehicle_title = QLabel("Vehicle")
        vehicle_title.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
        sidebar_layout.addWidget(vehicle_title)

        self.vin_label = QLabel("VIN: --")
        self.vin_label.setStyleSheet("color: #888; font-size: 11px;")
        self.vin_label.setWordWrap(True)
        sidebar_layout.addWidget(self.vin_label)

        self.ecus_label = QLabel("ECUs: --")
        self.ecus_label.setStyleSheet("color: #888;")
        sidebar_layout.addWidget(self.ecus_label)

        sidebar_layout.addSpacing(20)

        # Action buttons in sidebar
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_vehicle)
        self.connect_btn.setEnabled(False)
        sidebar_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("danger")
        self.disconnect_btn.clicked.connect(self.disconnect_vehicle)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.hide()
        sidebar_layout.addWidget(self.disconnect_btn)

        sidebar_layout.addStretch()

        # Detect button at bottom
        self.detect_btn = QPushButton("Detect Adapter")
        self.detect_btn.clicked.connect(self.detect_adapter)
        sidebar_layout.addWidget(self.detect_btn)

        main_layout.addWidget(sidebar)

        # Main content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # Tabs
        tabs = QTabWidget()

        # Tab 1: Scan ECUs
        scan_tab = QWidget()
        scan_layout = QVBoxLayout(scan_tab)

        scan_btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Scan All ECUs")
        self.scan_btn.clicked.connect(self.scan_ecus)
        self.scan_btn.setEnabled(False)
        scan_btn_layout.addWidget(self.scan_btn)
        scan_btn_layout.addStretch()
        scan_layout.addLayout(scan_btn_layout)

        self.progress = QProgressBar()
        self.progress.setMinimumHeight(25)
        self.progress.hide()
        scan_layout.addWidget(self.progress)

        self.ecu_table = QTableWidget()
        self.ecu_table.setColumnCount(3)
        self.ecu_table.setHorizontalHeaderLabels(["ECU Module", "Address", "Status"])
        self.ecu_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scan_layout.addWidget(self.ecu_table)

        tabs.addTab(scan_tab, "Scan ECUs")

        # Tab 2: Fault Codes
        dtc_tab = QWidget()
        dtc_layout = QVBoxLayout(dtc_tab)

        dtc_btn_layout = QHBoxLayout()
        self.read_dtc_btn = QPushButton("Read All DTCs")
        self.read_dtc_btn.clicked.connect(self.read_all_dtcs)
        self.read_dtc_btn.setEnabled(False)
        dtc_btn_layout.addWidget(self.read_dtc_btn)

        self.clear_dtc_btn = QPushButton("Clear All DTCs")
        self.clear_dtc_btn.setObjectName("danger")
        self.clear_dtc_btn.clicked.connect(self.clear_all_dtcs)
        self.clear_dtc_btn.setEnabled(False)
        dtc_btn_layout.addWidget(self.clear_dtc_btn)

        dtc_btn_layout.addStretch()
        dtc_layout.addLayout(dtc_btn_layout)

        self.dtc_output = QTextEdit()
        self.dtc_output.setReadOnly(True)
        dtc_layout.addWidget(self.dtc_output)

        tabs.addTab(dtc_tab, "Fault Codes")

        # Tab 3: Log
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(lambda: self.log_output.clear())
        log_layout.addWidget(clear_log_btn)

        tabs.addTab(log_tab, "Log")

        content_layout.addWidget(tabs)
        main_layout.addWidget(content, 1)

    def log(self, msg):
        self.log_output.append(msg)

    def detect_adapter(self):
        """Detect USB CAN adapter."""
        self.log("Detecting USB CAN adapters...")

        adapters, usb_info = detect_usb_adapters()

        if usb_info:
            for info in usb_info:
                self.log(f"  USB: {info}")

        if adapters:
            self.interface = adapters[0]
            self.adapter_label.setText(f"{self.interface}")
            self.adapter_label.setStyleSheet("color: #00cc00;")
            self.connect_btn.setEnabled(True)
            self.log(f"CAN interface found: {self.interface}")
        else:
            self.adapter_label.setText("No adapter")
            self.adapter_label.setStyleSheet("color: #cc6600;")
            self.connect_btn.setEnabled(False)
            self.log("No CAN interface detected.")
            self.log("Plug in USB CAN adapter and click Detect")

    def connect_vehicle(self):
        """Connect to vehicle and read info."""
        if not self.interface:
            return

        self.log("Connecting to vehicle...")
        self.connect_btn.setEnabled(False)

        # First try to scan for ECUs to verify connection
        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_connect_scan_complete)
        self.worker.start()

    def _on_connect_scan_complete(self, results):
        """Handle connection scan results."""
        if "error" in results:
            self.log(f"Connection error: {results['error']}")
            self.connect_btn.setEnabled(True)
            QMessageBox.warning(self, "Connection Failed", results['error'])
            return

        responding = results.get("responding", 0)

        if responding > 0:
            self.connected = True
            self.conn_status.setText("Connected")
            self.conn_status.setStyleSheet("color: #00cc00;")
            self.ecus_label.setText(f"ECUs: {responding} responding")

            self.connect_btn.hide()
            self.disconnect_btn.show()
            self.disconnect_btn.setEnabled(True)

            self.scan_btn.setEnabled(True)
            self.read_dtc_btn.setEnabled(True)
            self.clear_dtc_btn.setEnabled(True)

            self.log(f"Connected! {responding} ECUs responding.")

            # Populate ECU table
            ecus = results.get("ecus", {})
            self.ecu_table.setRowCount(0)
            for addr, info in ecus.items():
                row = self.ecu_table.rowCount()
                self.ecu_table.insertRow(row)
                self.ecu_table.setItem(row, 0, QTableWidgetItem(info["name"]))
                self.ecu_table.setItem(row, 1, QTableWidgetItem(f"0x{addr:02X}"))
                status_item = QTableWidgetItem(info["status"])
                if info["status"] == "OK":
                    status_item.setForeground(QColor("#00cc00"))
                else:
                    status_item.setForeground(QColor("#cc0000"))
                self.ecu_table.setItem(row, 2, status_item)

            # Try to read VIN
            self._read_vehicle_vin()
        else:
            self.log("No ECUs responded - is ignition ON?")
            self.connect_btn.setEnabled(True)
            QMessageBox.warning(
                self, "No Response",
                "No ECUs responded.\n\nMake sure:\n"
                "- Ignition is ON\n"
                "- OBD cable is connected\n"
                "- CAN interface is up (sudo ip link set can0 up type can bitrate 500000)"
            )

    def _read_vehicle_vin(self):
        """Read VIN from vehicle."""
        self.log("Reading VIN...")
        self.worker = CANWorker("read_vin", self.interface)
        self.worker.finished.connect(self._on_vin_read)
        self.worker.start()

    def _on_vin_read(self, results):
        """Handle VIN read results."""
        vin = results.get("vin")
        if vin:
            self.vehicle_vin = vin
            self.vin_label.setText(f"VIN: {vin}")
            self.log(f"VIN: {vin}")
        else:
            self.vin_label.setText("VIN: (could not read)")
            self.log("Could not read VIN")

    def disconnect_vehicle(self):
        """Disconnect from vehicle."""
        self.connected = False
        self.conn_status.setText("Disconnected")
        self.conn_status.setStyleSheet("color: #cc0000;")
        self.ecus_label.setText("ECUs: --")
        self.vin_label.setText("VIN: --")
        self.vehicle_vin = None

        self.disconnect_btn.hide()
        self.connect_btn.show()
        self.connect_btn.setEnabled(True)

        self.scan_btn.setEnabled(False)
        self.read_dtc_btn.setEnabled(False)
        self.clear_dtc_btn.setEnabled(False)

        self.ecu_table.setRowCount(0)
        self.log("Disconnected.")

    def scan_ecus(self):
        """Scan for ECUs."""
        if not self.interface:
            return

        self.scan_btn.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)
        self.ecu_table.setRowCount(0)
        self.log(f"Scanning ECUs on {self.interface}...")

        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(lambda m: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_scan_complete)
        self.worker.start()

    def _on_scan_complete(self, results):
        self.progress.hide()
        self.scan_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Scan error: {results['error']}")
            QMessageBox.warning(self, "Scan Error", results['error'])
            return

        ecus = results.get("ecus", {})
        responding = results.get("responding", 0)

        for addr, info in ecus.items():
            row = self.ecu_table.rowCount()
            self.ecu_table.insertRow(row)

            self.ecu_table.setItem(row, 0, QTableWidgetItem(info["name"]))
            self.ecu_table.setItem(row, 1, QTableWidgetItem(f"0x{addr:02X}"))

            status_item = QTableWidgetItem(info["status"])
            if info["status"] == "OK":
                status_item.setForeground(QColor("#00cc00"))
            else:
                status_item.setForeground(QColor("#cc0000"))
            self.ecu_table.setItem(row, 2, status_item)

        self.ecus_label.setText(f"ECUs: {responding} responding")
        self.log(f"Scan complete. {responding} ECUs responding.")

    def read_all_dtcs(self):
        """Read DTCs from all ECUs."""
        if not self.interface:
            return

        self.dtc_output.clear()
        self.log("Reading fault codes from all ECUs...")

        try:
            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            for addr, name in ECU_LIST.items():
                self.dtc_output.append(f"\n{name} (0x{addr:02X}):")

                tx_id = 0x600 + addr
                msg = can.Message(
                    arbitration_id=tx_id,
                    data=[0x04, 0x19, 0x02, 0xFF, 0x00, 0x00, 0x00, 0x00],
                    is_extended_id=False
                )

                try:
                    bus.send(msg)
                    response = bus.recv(timeout=0.3)
                    if response:
                        self.dtc_output.append(f"  Response: {response.data.hex()}")
                    else:
                        self.dtc_output.append("  No response")
                except Exception as e:
                    self.dtc_output.append(f"  Error: {e}")

            bus.shutdown()
            self.log("DTC read complete.")

        except Exception as e:
            self.log(f"Error reading DTCs: {e}")
            QMessageBox.warning(self, "Error", str(e))

    def clear_all_dtcs(self):
        """Clear DTCs from all ECUs."""
        if not self.interface:
            return

        reply = QMessageBox.question(
            self, "Confirm",
            "Clear all fault codes from all ECUs?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.log("Clearing fault codes from all ECUs...")

        try:
            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            cleared = 0
            for addr, name in ECU_LIST.items():
                tx_id = 0x600 + addr
                msg = can.Message(
                    arbitration_id=tx_id,
                    data=[0x04, 0x14, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00],
                    is_extended_id=False
                )

                try:
                    bus.send(msg)
                    response = bus.recv(timeout=0.2)
                    if response:
                        cleared += 1
                except Exception:
                    pass

            bus.shutdown()
            self.log(f"Cleared DTCs from {cleared} ECUs.")
            QMessageBox.information(self, "Done", f"Cleared fault codes from {cleared} ECUs")

        except Exception as e:
            self.log(f"Error clearing DTCs: {e}")
            QMessageBox.warning(self, "Error", str(e))


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("E92 Pulse")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
