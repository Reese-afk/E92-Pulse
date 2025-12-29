"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Single-file application for simplicity
"""
import sys
import os
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget
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

    # Check /dev for CAN devices
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

    # Check USB devices for known CAN adapters
    usb_info = []
    try:
        result = subprocess.run(
            ["lsusb"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split('\n'):
            line_lower = line.lower()
            if any(x in line_lower for x in ['can', 'innomaker', 'canable', 'peak', 'gs_usb']):
                usb_info.append(line.strip())
    except Exception:
        pass

    return adapters, usb_info


def setup_can_interface(interface="can0", bitrate=500000):
    """Setup CAN interface."""
    try:
        # Bring down first
        subprocess.run(
            ["sudo", "ip", "link", "set", interface, "down"],
            capture_output=True, timeout=5
        )
        # Set type and bitrate
        subprocess.run(
            ["sudo", "ip", "link", "set", interface, "type", "can", "bitrate", str(bitrate)],
            capture_output=True, timeout=5
        )
        # Bring up
        result = subprocess.run(
            ["sudo", "ip", "link", "set", interface, "up"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception as e:
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
            import can

            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            if self.operation == "scan":
                results = self._scan_ecus(bus)
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

        for addr, name in ECU_LIST.items():
            self.progress.emit(f"Scanning {name}...")

            # Send TesterPresent (0x3E)
            tx_id = 0x600 + addr
            rx_id = 0x600 + addr + 8

            msg = can.Message(
                arbitration_id=tx_id,
                data=[0x02, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                is_extended_id=False
            )

            try:
                bus.send(msg)
                # Wait for response
                response = bus.recv(timeout=0.2)
                if response and response.arbitration_id == rx_id:
                    found[addr] = {"name": name, "status": "OK"}
                else:
                    found[addr] = {"name": name, "status": "No Response"}
            except Exception:
                found[addr] = {"name": name, "status": "Error"}

        return {"ecus": found}

    def _read_dtcs(self, bus, addr):
        """Read DTCs from ECU."""
        # UDS Read DTC (0x19 0x02 0xFF 0x00)
        tx_id = 0x600 + addr
        rx_id = 0x600 + addr + 8

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
        # UDS Clear DTC (0x14 0xFF 0xFF 0xFF)
        tx_id = 0x600 + addr

        msg = can.Message(
            arbitration_id=tx_id,
            data=[0x04, 0x14, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00],
            is_extended_id=False
        )

        try:
            bus.send(msg)
            response = bus.recv(timeout=0.5)
            if response and response.data[1] == 0x54:  # Positive response
                return {"success": True}
            return {"success": False, "error": "No positive response"}
        except Exception as e:
            return {"error": str(e)}


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("E92 Pulse - BMW E92 M3 Diagnostics")
        self.setMinimumSize(900, 600)

        self.interface = None
        self.worker = None

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
        """)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        header = QLabel("E92 Pulse")
        header.setFont(QFont("sans-serif", 28, QFont.Weight.Bold))
        header.setStyleSheet("color: #00aaff;")
        layout.addWidget(header)

        subtitle = QLabel("BMW E92 M3 Diagnostic Tool")
        subtitle.setStyleSheet("color: #888;")
        layout.addWidget(subtitle)

        # Status bar
        status_layout = QHBoxLayout()

        self.status_label = QLabel("Detecting adapter...")
        self.status_label.setStyleSheet("color: #ffaa00;")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.detect_btn = QPushButton("Detect Adapter")
        self.detect_btn.clicked.connect(self.detect_adapter)
        status_layout.addWidget(self.detect_btn)

        self.setup_btn = QPushButton("Setup CAN")
        self.setup_btn.clicked.connect(self.setup_can)
        self.setup_btn.setEnabled(False)
        status_layout.addWidget(self.setup_btn)

        layout.addLayout(status_layout)

        # Tabs
        tabs = QTabWidget()

        # Tab 1: Scan
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
        self.ecu_table.setHorizontalHeaderLabels(["ECU", "Address", "Status"])
        self.ecu_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scan_layout.addWidget(self.ecu_table)

        tabs.addTab(scan_tab, "Scan ECUs")

        # Tab 2: DTCs
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

        layout.addWidget(tabs)

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
            self.status_label.setText(f"Found: {self.interface}")
            self.status_label.setStyleSheet("color: #00cc00;")
            self.setup_btn.setEnabled(True)
            self.scan_btn.setEnabled(True)
            self.read_dtc_btn.setEnabled(True)
            self.clear_dtc_btn.setEnabled(True)
            self.log(f"CAN interface found: {self.interface}")
        else:
            self.status_label.setText("No CAN interface - plug in adapter")
            self.status_label.setStyleSheet("color: #cc6600;")
            self.log("No CAN interface detected.")
            self.log("Connect USB CAN adapter and click 'Setup CAN'")

    def setup_can(self):
        """Setup CAN interface."""
        self.log("Setting up CAN interface at 500kbps...")

        # Try can0
        if setup_can_interface("can0", 500000):
            self.interface = "can0"
            self.status_label.setText("Ready: can0 @ 500kbps")
            self.status_label.setStyleSheet("color: #00cc00;")
            self.scan_btn.setEnabled(True)
            self.read_dtc_btn.setEnabled(True)
            self.clear_dtc_btn.setEnabled(True)
            self.log("CAN interface configured successfully!")
        else:
            self.log("Failed to setup CAN. Run manually:")
            self.log("  sudo ip link set can0 up type can bitrate 500000")
            QMessageBox.warning(
                self, "Setup Failed",
                "Could not setup CAN interface.\n\n"
                "Run this command manually:\n"
                "sudo ip link set can0 up type can bitrate 500000"
            )

    def scan_ecus(self):
        """Scan for ECUs."""
        if not self.interface:
            QMessageBox.warning(self, "Error", "No CAN interface detected")
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

        self.log(f"Scan complete. Found {sum(1 for e in ecus.values() if e['status'] == 'OK')} responding ECUs.")

    def read_all_dtcs(self):
        """Read DTCs from all ECUs."""
        if not self.interface:
            return

        self.dtc_output.clear()
        self.log("Reading fault codes from all ECUs...")

        # Simple sequential read
        try:
            import can
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
            import can
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
