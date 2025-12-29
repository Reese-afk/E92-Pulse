"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Full-featured diagnostic application with proper BMW CAN addressing
"""
import sys
import subprocess
import struct
import time

import can

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame,
    QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex
from PyQt6.QtGui import QFont, QColor


# BMW E92 M3 ECU Configuration
# Format: {"name": (request_id, response_id, description)}
# BMW E-series uses physical diagnostic addressing
# Request ID = base + physical address, Response ID = request + 8
BMW_ECUS = {
    "DME": (0x7E0, 0x7E8, "Engine Control (MSV80)"),
    "EGS": (0x7E1, 0x7E9, "Transmission Control"),
    "DSC": (0x760, 0x768, "Dynamic Stability Control"),
    "KOMBI": (0x720, 0x728, "Instrument Cluster"),
    "CAS": (0x740, 0x748, "Car Access System"),
    "FRM": (0x730, 0x738, "Footwell Module"),
    "JBE": (0x750, 0x758, "Junction Box Electronics"),
    "EPS": (0x7A0, 0x7A8, "Electric Power Steering"),
    "SZL": (0x714, 0x71C, "Steering Column Switch"),
    "IHKA": (0x7A4, 0x7AC, "Climate Control"),
    "PDC": (0x780, 0x788, "Park Distance Control"),
    "CIC": (0x710, 0x718, "iDrive Controller"),
    "TCU": (0x770, 0x778, "Telematics Control"),
    "RLS": (0x724, 0x72C, "Rain/Light Sensor"),
    "SHD": (0x744, 0x74C, "Sunroof Module"),
    "TPMS": (0x754, 0x75C, "Tire Pressure Monitor"),
}

# OBD-II Functional address (broadcasts to all emission-related ECUs)
OBD_FUNCTIONAL_ID = 0x7DF

# UDS Service IDs
UDS_DIAGNOSTIC_SESSION = 0x10
UDS_ECU_RESET = 0x11
UDS_CLEAR_DTC = 0x14
UDS_READ_DTC = 0x19
UDS_READ_DATA_BY_ID = 0x22
UDS_ROUTINE_CONTROL = 0x31
UDS_TESTER_PRESENT = 0x3E

# UDS Session Types
SESSION_DEFAULT = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED = 0x03

# UDS Reset Types
RESET_HARD = 0x01
RESET_KEY_OFF_ON = 0x02
RESET_SOFT = 0x03

# BMW-specific Routine IDs (verified for E-series)
ROUTINE_BATTERY_REGISTER = 0x0203  # Battery registration
ROUTINE_CBS_RESET_BASE = 0x0100   # CBS reset base (add service type)

# CBS Service Types for E92
CBS_OIL_SERVICE = 0x01
CBS_FRONT_BRAKE = 0x06
CBS_REAR_BRAKE = 0x07
CBS_BRAKE_FLUID = 0x02
CBS_SPARK_PLUGS = 0x0A
CBS_COOLANT = 0x0B
CBS_INSPECTION = 0x08
CBS_AIR_FILTER = 0x0C

# Service resets
SERVICE_RESETS = {
    "oil": {"name": "Engine Oil Service", "cbs_type": CBS_OIL_SERVICE},
    "brake_front": {"name": "Front Brake Pads", "cbs_type": CBS_FRONT_BRAKE},
    "brake_rear": {"name": "Rear Brake Pads", "cbs_type": CBS_REAR_BRAKE},
    "brake_fluid": {"name": "Brake Fluid", "cbs_type": CBS_BRAKE_FLUID},
    "spark_plugs": {"name": "Spark Plugs", "cbs_type": CBS_SPARK_PLUGS},
    "coolant": {"name": "Coolant", "cbs_type": CBS_COOLANT},
    "inspection": {"name": "Vehicle Inspection", "cbs_type": CBS_INSPECTION},
    "air_filter": {"name": "Air Filter", "cbs_type": CBS_AIR_FILTER},
}

# Common BMW DTC descriptions
DTC_DESCRIPTIONS = {
    0x0100: "Mass Air Flow Circuit Malfunction",
    0x0101: "Mass Air Flow Circuit Range/Performance",
    0x0102: "Mass Air Flow Circuit Low Input",
    0x0103: "Mass Air Flow Circuit High Input",
    0x0110: "Intake Air Temperature Circuit Malfunction",
    0x0115: "Engine Coolant Temperature Circuit Malfunction",
    0x0120: "Throttle Position Sensor Circuit Malfunction",
    0x0130: "O2 Sensor Circuit Malfunction (Bank 1 Sensor 1)",
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
    0x0420: "Catalyst Efficiency Below Threshold (Bank 1)",
    0x0430: "Catalyst Efficiency Below Threshold (Bank 2)",
    0x0500: "Vehicle Speed Sensor Malfunction",
    # BMW-specific codes
    0x2AAF: "Fuel Pump Control Circuit",
    0x2DFC: "DME: Internal Error",
    0x30FF: "O2 Sensor Heater Control Circuit",
    0x4010: "DSC: System Malfunction",
    0xA0A0: "FRM: Internal Error",
    0xA0B0: "FRM: Light Output Error",
    0xD000: "Communication Bus Error",
}


def detect_usb_adapters():
    """Detect USB CAN adapters and CAN interfaces."""
    adapters = []
    usb_info = []

    # Check for CAN interfaces
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

    # Check USB devices
    try:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            line_lower = line.lower()
            if any(x in line_lower for x in ['can', 'innomaker', 'canable', 'peak', '1d50:606f', 'geschwister']):
                usb_info.append(line.strip())
    except Exception:
        pass

    return adapters, usb_info


class IsoTpHandler:
    """Simple ISO-TP (ISO 15765-2) handler for multi-frame messages."""

    def __init__(self, bus, tx_id, rx_id):
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id

    def send_receive(self, data, timeout=1.0):
        """Send data and receive response using ISO-TP framing."""
        data = list(data)

        # Single frame (up to 7 bytes)
        if len(data) <= 7:
            frame = [len(data)] + data + [0x00] * (7 - len(data))
            msg = can.Message(arbitration_id=self.tx_id, data=frame, is_extended_id=False)
            self.bus.send(msg)
        else:
            # Multi-frame: First Frame
            length = len(data)
            first_frame = [0x10 | ((length >> 8) & 0x0F), length & 0xFF] + data[:6]
            msg = can.Message(arbitration_id=self.tx_id, data=first_frame, is_extended_id=False)
            self.bus.send(msg)

            # Wait for Flow Control
            fc = self._recv_frame(timeout=0.5)
            if not fc or (fc[0] & 0xF0) != 0x30:
                return None

            # Send Consecutive Frames
            seq = 1
            offset = 6
            while offset < len(data):
                cf = [0x20 | (seq & 0x0F)] + data[offset:offset+7]
                cf += [0x00] * (8 - len(cf))
                msg = can.Message(arbitration_id=self.tx_id, data=cf, is_extended_id=False)
                self.bus.send(msg)
                seq = (seq + 1) & 0x0F
                offset += 7
                time.sleep(0.001)  # Small delay between frames

        # Receive response
        return self._receive_isotp(timeout)

    def _recv_frame(self, timeout=0.5):
        """Receive a single CAN frame."""
        response = self.bus.recv(timeout=timeout)
        if response and response.arbitration_id == self.rx_id:
            return list(response.data)
        return None

    def _receive_isotp(self, timeout=1.0):
        """Receive and reassemble ISO-TP message."""
        frame = self._recv_frame(timeout)
        if not frame:
            return None

        frame_type = frame[0] & 0xF0

        # Single Frame
        if frame_type == 0x00:
            length = frame[0] & 0x0F
            return frame[1:1+length]

        # First Frame (multi-frame response)
        elif frame_type == 0x10:
            length = ((frame[0] & 0x0F) << 8) | frame[1]
            data = frame[2:8]

            # Send Flow Control
            fc = can.Message(
                arbitration_id=self.tx_id,
                data=[0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                is_extended_id=False
            )
            self.bus.send(fc)

            # Receive Consecutive Frames
            while len(data) < length:
                cf = self._recv_frame(timeout=0.5)
                if not cf or (cf[0] & 0xF0) != 0x20:
                    break
                data.extend(cf[1:8])

            return data[:length]

        # Negative response might come as single frame
        return frame[1:] if frame[0] > 0 else None


class CANWorker(QThread):
    """Worker thread for CAN operations with proper BMW addressing."""
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str, int)  # message, percentage

    _mutex = QMutex()
    _is_running = False

    def __init__(self, operation, interface, params=None):
        super().__init__()
        self.operation = operation
        self.interface = interface
        self.params = params or {}

    def run(self):
        if not CANWorker._mutex.tryLock():
            self.finished.emit({"error": "Another operation is in progress"})
            return

        CANWorker._is_running = True
        try:
            bus = can.interface.Bus(channel=self.interface, interface='socketcan')

            if self.operation == "scan":
                results = self._scan_ecus(bus)
            elif self.operation == "read_vin":
                results = self._read_vin(bus)
            elif self.operation == "read_dtc":
                results = self._read_dtcs(bus, self.params.get("ecu_name"))
            elif self.operation == "clear_dtc":
                results = self._clear_dtcs(bus, self.params.get("ecu_name"))
            elif self.operation == "reset_ecu":
                results = self._reset_ecu(bus, self.params.get("ecu_name"), self.params.get("reset_type", RESET_SOFT))
            elif self.operation == "battery_reset":
                results = self._battery_registration(bus)
            elif self.operation == "service_reset":
                results = self._service_reset(bus, self.params.get("cbs_type"))
            else:
                results = {"error": "Unknown operation"}

            bus.shutdown()
            self.finished.emit(results)

        except Exception as e:
            self.finished.emit({"error": str(e)})
        finally:
            CANWorker._is_running = False
            CANWorker._mutex.unlock()

    def _enter_session(self, bus, tx_id, rx_id, session_type=SESSION_EXTENDED):
        """Enter diagnostic session."""
        isotp = IsoTpHandler(bus, tx_id, rx_id)
        response = isotp.send_receive([UDS_DIAGNOSTIC_SESSION, session_type], timeout=1.0)
        if response and len(response) >= 2 and response[0] == UDS_DIAGNOSTIC_SESSION + 0x40:
            return True
        return False

    def _send_tester_present(self, bus, tx_id, rx_id):
        """Send TesterPresent to keep session alive."""
        isotp = IsoTpHandler(bus, tx_id, rx_id)
        response = isotp.send_receive([UDS_TESTER_PRESENT, 0x00], timeout=0.5)
        return response is not None

    def _scan_ecus(self, bus):
        """Scan for ECUs using TesterPresent."""
        found = {}
        responding = 0
        total = len(BMW_ECUS)

        for i, (name, (tx_id, rx_id, desc)) in enumerate(BMW_ECUS.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Scanning {name}...", percent)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            response = isotp.send_receive([UDS_TESTER_PRESENT, 0x00], timeout=0.3)

            if response and len(response) >= 1:
                # Check for positive response (0x7E) or negative response (0x7F)
                if response[0] == UDS_TESTER_PRESENT + 0x40:
                    found[name] = {"status": "OK", "tx_id": tx_id, "rx_id": rx_id, "desc": desc}
                    responding += 1
                elif response[0] == 0x7F:
                    # Negative response - ECU exists but rejected request
                    found[name] = {"status": "Busy", "tx_id": tx_id, "rx_id": rx_id, "desc": desc}
                    responding += 1
                else:
                    found[name] = {"status": "No Response", "tx_id": tx_id, "rx_id": rx_id, "desc": desc}
            else:
                found[name] = {"status": "No Response", "tx_id": tx_id, "rx_id": rx_id, "desc": desc}

        self.progress.emit("Scan complete", 100)
        return {"ecus": found, "responding": responding}

    def _read_vin(self, bus):
        """Read VIN using ReadDataByIdentifier (0x22)."""
        # Try DME, then CAS, then KOMBI
        for ecu_name in ["DME", "CAS", "KOMBI"]:
            if ecu_name not in BMW_ECUS:
                continue

            tx_id, rx_id, _ = BMW_ECUS[ecu_name]
            self.progress.emit(f"Reading VIN from {ecu_name}...", 50)

            # Enter extended session first
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ReadDataByIdentifier - VIN is 0xF190
            response = isotp.send_receive([UDS_READ_DATA_BY_ID, 0xF1, 0x90], timeout=1.0)

            if response and len(response) >= 4 and response[0] == UDS_READ_DATA_BY_ID + 0x40:
                # Response: 62 F1 90 [VIN bytes...]
                vin_bytes = response[3:20]
                vin = ''.join(chr(b) for b in vin_bytes if 32 <= b <= 126)
                if len(vin) >= 10:
                    self.progress.emit("VIN read complete", 100)
                    return {"vin": vin, "source": ecu_name}

        self.progress.emit("VIN read failed", 100)
        return {"vin": None, "error": "Could not read VIN from any ECU"}

    def _read_dtcs(self, bus, ecu_name=None):
        """Read DTCs from ECU(s)."""
        dtcs = []
        ecus_to_scan = {ecu_name: BMW_ECUS[ecu_name]} if ecu_name and ecu_name in BMW_ECUS else BMW_ECUS
        total = len(ecus_to_scan)

        for i, (name, (tx_id, rx_id, desc)) in enumerate(ecus_to_scan.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Reading DTCs from {name}...", percent)

            # Enter extended session
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ReadDTCInformation - reportDTCByStatusMask (0x02), all DTCs (0xFF)
            response = isotp.send_receive([UDS_READ_DTC, 0x02, 0xFF], timeout=1.0)

            if response and len(response) >= 3 and response[0] == UDS_READ_DTC + 0x40:
                # Response: 59 02 [availability_mask] [DTC1_HI DTC1_MID DTC1_LO STATUS]...
                dtc_data = response[3:]

                # Parse DTC entries (4 bytes each: 3 bytes DTC + 1 byte status)
                i = 0
                while i + 3 < len(dtc_data):
                    dtc_hi = dtc_data[i]
                    dtc_mid = dtc_data[i+1]
                    dtc_lo = dtc_data[i+2]
                    status = dtc_data[i+3] if i+3 < len(dtc_data) else 0

                    if dtc_hi == 0 and dtc_mid == 0 and dtc_lo == 0:
                        break

                    # Format as standard P/C/B/U code
                    dtc_num = (dtc_hi << 16) | (dtc_mid << 8) | dtc_lo
                    dtc_type = (dtc_hi >> 6) & 0x03
                    type_char = ['P', 'C', 'B', 'U'][dtc_type]
                    dtc_str = f"{type_char}{((dtc_hi & 0x3F) << 8 | dtc_mid):04X}"

                    # Look up description
                    lookup_code = (dtc_mid << 8) | dtc_lo
                    description = DTC_DESCRIPTIONS.get(lookup_code, f"Unknown fault (0x{dtc_num:06X})")

                    dtcs.append({
                        "ecu": name,
                        "code": dtc_str,
                        "raw": dtc_num,
                        "status": status,
                        "active": bool(status & 0x01),
                        "description": description
                    })
                    i += 4

        self.progress.emit("DTC read complete", 100)
        return {"dtcs": dtcs}

    def _clear_dtcs(self, bus, ecu_name=None):
        """Clear DTCs from ECU(s)."""
        cleared = 0
        failed = 0
        ecus_to_clear = {ecu_name: BMW_ECUS[ecu_name]} if ecu_name and ecu_name in BMW_ECUS else BMW_ECUS
        total = len(ecus_to_clear)

        for i, (name, (tx_id, rx_id, _)) in enumerate(ecus_to_clear.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Clearing DTCs from {name}...", percent)

            # Enter extended session
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ClearDiagnosticInformation - all groups (0xFF 0xFF 0xFF)
            response = isotp.send_receive([UDS_CLEAR_DTC, 0xFF, 0xFF, 0xFF], timeout=1.0)

            if response and len(response) >= 1 and response[0] == UDS_CLEAR_DTC + 0x40:
                cleared += 1
            else:
                failed += 1

        self.progress.emit("DTC clear complete", 100)
        return {"cleared": cleared, "failed": failed}

    def _reset_ecu(self, bus, ecu_name, reset_type=RESET_SOFT):
        """Reset ECU using UDS ECUReset service."""
        if ecu_name not in BMW_ECUS:
            return {"success": False, "error": f"Unknown ECU: {ecu_name}"}

        tx_id, rx_id, desc = BMW_ECUS[ecu_name]
        self.progress.emit(f"Resetting {ecu_name}...", 50)

        # Enter extended session first
        if not self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED):
            return {"success": False, "ecu": ecu_name, "error": "Could not enter diagnostic session"}

        isotp = IsoTpHandler(bus, tx_id, rx_id)
        response = isotp.send_receive([UDS_ECU_RESET, reset_type], timeout=2.0)

        self.progress.emit("Reset complete", 100)

        if response and len(response) >= 1:
            if response[0] == UDS_ECU_RESET + 0x40:
                return {"success": True, "ecu": ecu_name}
            elif response[0] == 0x7F and len(response) >= 3:
                nrc = response[2]
                nrc_desc = {
                    0x12: "Sub-function not supported",
                    0x13: "Incorrect message length",
                    0x22: "Conditions not correct",
                    0x33: "Security access denied",
                }.get(nrc, f"Error 0x{nrc:02X}")
                return {"success": False, "ecu": ecu_name, "error": nrc_desc}

        return {"success": False, "ecu": ecu_name, "error": "No response"}

    def _battery_registration(self, bus):
        """Perform battery registration via DME."""
        results = []

        # Battery registration is typically done through DME or power management ECU
        if "DME" not in BMW_ECUS:
            return {"success": False, "error": "DME not found in ECU list"}

        tx_id, rx_id, _ = BMW_ECUS["DME"]
        self.progress.emit("Connecting to DME...", 10)

        # Enter extended session
        if not self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED):
            return {"success": False, "error": "Could not enter diagnostic session"}

        self.progress.emit("Registering battery...", 50)

        isotp = IsoTpHandler(bus, tx_id, rx_id)

        # RoutineControl - Start Routine (0x01) - Battery Registration (0x0203)
        response = isotp.send_receive([
            UDS_ROUTINE_CONTROL, 0x01,
            (ROUTINE_BATTERY_REGISTER >> 8) & 0xFF,
            ROUTINE_BATTERY_REGISTER & 0xFF
        ], timeout=2.0)

        if response and len(response) >= 1 and response[0] == UDS_ROUTINE_CONTROL + 0x40:
            results.append("Battery registration successful")
        else:
            # Try alternative method - clear battery adaptations
            self.progress.emit("Trying alternative method...", 75)
            response = isotp.send_receive([
                UDS_ROUTINE_CONTROL, 0x01, 0x02, 0x00  # Clear adaptation
            ], timeout=2.0)
            if response and response[0] == UDS_ROUTINE_CONTROL + 0x40:
                results.append("Battery adaptation cleared")

        self.progress.emit("Complete", 100)

        if results:
            return {"success": True, "results": results}
        return {"success": False, "error": "Battery registration failed - ensure ignition ON, engine OFF"}

    def _service_reset(self, bus, cbs_type):
        """Reset service indicator via KOMBI."""
        service_name = next(
            (v["name"] for v in SERVICE_RESETS.values() if v["cbs_type"] == cbs_type),
            f"Service 0x{cbs_type:02X}"
        )

        if "KOMBI" not in BMW_ECUS:
            return {"success": False, "service": service_name, "error": "KOMBI not found"}

        tx_id, rx_id, _ = BMW_ECUS["KOMBI"]
        self.progress.emit(f"Connecting to KOMBI...", 20)

        # Enter extended session
        if not self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED):
            return {"success": False, "service": service_name, "error": "Could not enter diagnostic session"}

        self.progress.emit(f"Resetting {service_name}...", 60)

        isotp = IsoTpHandler(bus, tx_id, rx_id)

        # RoutineControl - Start Routine for CBS reset
        routine_id = ROUTINE_CBS_RESET_BASE + cbs_type
        response = isotp.send_receive([
            UDS_ROUTINE_CONTROL, 0x01,
            (routine_id >> 8) & 0xFF,
            routine_id & 0xFF
        ], timeout=2.0)

        self.progress.emit("Complete", 100)

        if response and len(response) >= 1 and response[0] == UDS_ROUTINE_CONTROL + 0x40:
            return {"success": True, "service": service_name}
        elif response and response[0] == 0x7F and len(response) >= 3:
            nrc = response[2]
            return {"success": False, "service": service_name, "error": f"Rejected (NRC 0x{nrc:02X})"}

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
            QComboBox QAbstractItemView { background-color: #2d2d2d; selection-background-color: #0066cc; }
            QTableWidget { background-color: #2d2d2d; border: 1px solid #444; gridline-color: #444; }
            QHeaderView::section { background-color: #383838; padding: 8px; border: none; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { background-color: #2d2d2d; padding: 10px 20px; border: 1px solid #444; }
            QTabBar::tab:selected { background-color: #0066cc; }
            QProgressBar { background-color: #2d2d2d; border: none; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #0066cc; border-radius: 4px; }
            QFrame#sidebar { background-color: #252525; border-right: 1px solid #333; }
            QGroupBox { border: 1px solid #444; border-radius: 4px; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

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
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.ecu_table = QTableWidget()
        self.ecu_table.setColumnCount(4)
        self.ecu_table.setHorizontalHeaderLabels(["ECU", "Description", "CAN IDs", "Status"])
        self.ecu_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ecu_table.setColumnWidth(0, 80)
        self.ecu_table.setColumnWidth(2, 120)
        self.ecu_table.setColumnWidth(3, 100)
        layout.addWidget(self.ecu_table)

        return tab

    def _create_dtc_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("ECU:"))
        self.dtc_ecu_combo = QComboBox()
        self.dtc_ecu_combo.addItem("All ECUs", None)
        for name, (tx, rx, desc) in BMW_ECUS.items():
            self.dtc_ecu_combo.addItem(f"{name} - {desc}", name)
        self.dtc_ecu_combo.setMinimumWidth(300)
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

        self.dtc_progress = QProgressBar()
        self.dtc_progress.setMinimumHeight(20)
        self.dtc_progress.setRange(0, 100)
        self.dtc_progress.hide()
        layout.addWidget(self.dtc_progress)

        self.dtc_table = QTableWidget()
        self.dtc_table.setColumnCount(4)
        self.dtc_table.setHorizontalHeaderLabels(["ECU", "Code", "Status", "Description"])
        self.dtc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.dtc_table.setColumnWidth(0, 80)
        self.dtc_table.setColumnWidth(1, 100)
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
        # Add FRM first as it's most commonly reset
        if "FRM" in BMW_ECUS:
            self.reset_ecu_combo.addItem("FRM - Footwell Module", "FRM")
        for name, (tx, rx, desc) in BMW_ECUS.items():
            if name != "FRM":
                self.reset_ecu_combo.addItem(f"{name} - {desc}", name)
        self.reset_ecu_combo.setMinimumWidth(280)
        ecu_reset_row.addWidget(self.reset_ecu_combo)

        ecu_reset_row.addWidget(QLabel("Type:"))
        self.reset_type_combo = QComboBox()
        self.reset_type_combo.addItem("Soft Reset", RESET_SOFT)
        self.reset_type_combo.addItem("Key Off/On Reset", RESET_KEY_OFF_ON)
        self.reset_type_combo.addItem("Hard Reset", RESET_HARD)
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

        battery_info = QLabel("Use after replacing the battery to reset the IBS sensor.\nRequires: Ignition ON, Engine OFF")
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
        service_group = QGroupBox("Service Reset (CBS)")
        service_layout = QVBoxLayout(service_group)

        service_row = QHBoxLayout()
        service_row.addWidget(QLabel("Service:"))
        self.service_combo = QComboBox()
        for key, info in SERVICE_RESETS.items():
            self.service_combo.addItem(info["name"], info["cbs_type"])
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

        # Progress and output
        self.reset_progress = QProgressBar()
        self.reset_progress.setMinimumHeight(20)
        self.reset_progress.setRange(0, 100)
        self.reset_progress.hide()
        layout.addWidget(self.reset_progress)

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
            self.log(f"Found interface: {self.interface}")
        else:
            self.adapter_label.setText("No adapter")
            self.adapter_label.setStyleSheet("color: #cc6600;")
            self.log("No CAN interface found")
            self.log("Run: sudo ip link set can0 up type can bitrate 500000")

    def connect_vehicle(self):
        if not self.interface:
            return

        self.log("Connecting to vehicle...")
        self.connect_btn.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)

        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_connect_complete)
        self.worker.start()

    def _on_progress(self, msg, percent):
        self.log(f"  {msg}")
        self.progress.setValue(percent)

    def _on_connect_complete(self, results):
        self.progress.hide()

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

            self._enable_controls(True)
            self.log(f"Connected! {responding} ECUs responding.")
            self._update_ecu_table(self.found_ecus)
            self._read_vin()
        else:
            self.log("No ECUs responded. Check ignition and connections.")
            self.connect_btn.setEnabled(True)
            QMessageBox.warning(self, "No Response",
                "No ECUs responded.\n\nCheck:\n- Ignition ON\n- OBD cable connected\n- CAN interface up (500kbps)")

    def _enable_controls(self, enabled):
        self.scan_btn.setEnabled(enabled)
        self.read_dtc_btn.setEnabled(enabled)
        self.clear_dtc_btn.setEnabled(enabled)
        self.reset_ecu_btn.setEnabled(enabled)
        self.battery_btn.setEnabled(enabled)
        self.service_btn.setEnabled(enabled)

    def _update_ecu_table(self, ecus):
        self.ecu_table.setRowCount(0)
        for name, info in ecus.items():
            row = self.ecu_table.rowCount()
            self.ecu_table.insertRow(row)

            self.ecu_table.setItem(row, 0, QTableWidgetItem(name))
            self.ecu_table.setItem(row, 1, QTableWidgetItem(info.get("desc", "")))
            self.ecu_table.setItem(row, 2, QTableWidgetItem(f"0x{info['tx_id']:03X}/0x{info['rx_id']:03X}"))

            status_item = QTableWidgetItem(info["status"])
            color = "#00cc00" if info["status"] == "OK" else "#cc8800" if info["status"] == "Busy" else "#cc0000"
            status_item.setForeground(QColor(color))
            self.ecu_table.setItem(row, 3, status_item)

    def _read_vin(self):
        self.log("Reading VIN...")
        self.worker = CANWorker("read_vin", self.interface)
        self.worker.progress.connect(lambda m, p: self.log(f"  {m}"))
        self.worker.finished.connect(self._on_vin_complete)
        self.worker.start()

    def _on_vin_complete(self, results):
        vin = results.get("vin")
        if vin:
            self.vin_label.setText(f"VIN: {vin}")
            self.log(f"VIN: {vin} (from {results.get('source', 'unknown')})")
        else:
            self.vin_label.setText("VIN: --")
            self.log("Could not read VIN")

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

        self._enable_controls(False)
        self.ecu_table.setRowCount(0)
        self.dtc_table.setRowCount(0)
        self.log("Disconnected.")

    def scan_ecus(self):
        self.scan_btn.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)
        self.log("Scanning ECUs...")

        self.worker = CANWorker("scan", self.interface)
        self.worker.progress.connect(self._on_scan_progress)
        self.worker.finished.connect(self._on_scan_complete)
        self.worker.start()

    def _on_scan_progress(self, msg, percent):
        self.log(f"  {msg}")
        self.progress.setValue(percent)

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
        self.log(f"Scan complete. {responding} ECUs responding.")

    def read_dtcs(self):
        ecu_name = self.dtc_ecu_combo.currentData()
        self.read_dtc_btn.setEnabled(False)
        self.dtc_table.setRowCount(0)
        self.dtc_progress.show()
        self.dtc_progress.setValue(0)
        self.log("Reading DTCs...")

        self.worker = CANWorker("read_dtc", self.interface, {"ecu_name": ecu_name})
        self.worker.progress.connect(self._on_dtc_progress)
        self.worker.finished.connect(self._on_dtc_read_complete)
        self.worker.start()

    def _on_dtc_progress(self, msg, percent):
        self.log(f"  {msg}")
        self.dtc_progress.setValue(percent)

    def _on_dtc_read_complete(self, results):
        self.dtc_progress.hide()
        self.read_dtc_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        dtcs = results.get("dtcs", [])
        self.dtc_table.setRowCount(0)

        for dtc in dtcs:
            row = self.dtc_table.rowCount()
            self.dtc_table.insertRow(row)

            self.dtc_table.setItem(row, 0, QTableWidgetItem(dtc.get("ecu", "")))
            self.dtc_table.setItem(row, 1, QTableWidgetItem(dtc.get("code", "")))

            status_text = "Active" if dtc.get("active") else "Stored"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#cc0000" if dtc.get("active") else "#cc8800"))
            self.dtc_table.setItem(row, 2, status_item)

            self.dtc_table.setItem(row, 3, QTableWidgetItem(dtc.get("description", "")))

        self.log(f"Found {len(dtcs)} fault codes.")

    def clear_dtcs(self):
        ecu_name = self.dtc_ecu_combo.currentData()
        target = ecu_name if ecu_name else "all ECUs"

        reply = QMessageBox.question(self, "Confirm", f"Clear all fault codes from {target}?")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.clear_dtc_btn.setEnabled(False)
        self.dtc_progress.show()
        self.log(f"Clearing DTCs from {target}...")

        self.worker = CANWorker("clear_dtc", self.interface, {"ecu_name": ecu_name})
        self.worker.progress.connect(self._on_dtc_progress)
        self.worker.finished.connect(self._on_dtc_clear_complete)
        self.worker.start()

    def _on_dtc_clear_complete(self, results):
        self.dtc_progress.hide()
        self.clear_dtc_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        cleared = results.get("cleared", 0)
        self.log(f"Cleared DTCs from {cleared} ECUs.")
        QMessageBox.information(self, "Done", f"Cleared fault codes from {cleared} ECUs")
        self.dtc_table.setRowCount(0)

    def reset_ecu(self):
        ecu_name = self.reset_ecu_combo.currentData()
        reset_type = self.reset_type_combo.currentData()

        reply = QMessageBox.question(self, "Confirm ECU Reset",
            f"Reset {ecu_name}?\n\nThis will restart the module.")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.reset_ecu_btn.setEnabled(False)
        self.reset_progress.show()
        self.reset_output.append(f"Resetting {ecu_name}...")
        self.log(f"Resetting {ecu_name}...")

        self.worker = CANWorker("reset_ecu", self.interface, {"ecu_name": ecu_name, "reset_type": reset_type})
        self.worker.progress.connect(self._on_reset_progress)
        self.worker.finished.connect(self._on_reset_complete)
        self.worker.start()

    def _on_reset_progress(self, msg, percent):
        self.reset_output.append(f"  {msg}")
        self.reset_progress.setValue(percent)

    def _on_reset_complete(self, results):
        self.reset_progress.hide()
        self.reset_ecu_btn.setEnabled(True)

        if results.get("success"):
            self.reset_output.append(f"✓ {results.get('ecu')} reset successful!")
            self.log(f"ECU reset successful: {results.get('ecu')}")
            QMessageBox.information(self, "Success", f"{results.get('ecu')} has been reset!")
        else:
            error = results.get("error", "Unknown error")
            self.reset_output.append(f"✗ Reset failed: {error}")
            self.log(f"ECU reset failed: {error}")

    def battery_registration(self):
        reply = QMessageBox.question(self, "Battery Registration",
            "Register new battery?\n\nThis resets the IBS sensor.\nRequires: Ignition ON, Engine OFF")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.battery_btn.setEnabled(False)
        self.reset_progress.show()
        self.reset_output.append("Starting battery registration...")
        self.log("Battery registration started...")

        self.worker = CANWorker("battery_reset", self.interface)
        self.worker.progress.connect(self._on_reset_progress)
        self.worker.finished.connect(self._on_battery_complete)
        self.worker.start()

    def _on_battery_complete(self, results):
        self.reset_progress.hide()
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
        cbs_type = self.service_combo.currentData()
        service_name = self.service_combo.currentText()

        reply = QMessageBox.question(self, "Service Reset",
            f"Reset {service_name}?\n\nThis will reset the service indicator.")
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.service_btn.setEnabled(False)
        self.reset_progress.show()
        self.reset_output.append(f"Resetting {service_name}...")
        self.log(f"Service reset: {service_name}...")

        self.worker = CANWorker("service_reset", self.interface, {"cbs_type": cbs_type})
        self.worker.progress.connect(self._on_reset_progress)
        self.worker.finished.connect(self._on_service_complete)
        self.worker.start()

    def _on_service_complete(self, results):
        self.reset_progress.hide()
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
