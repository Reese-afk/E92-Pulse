"""
E92 Pulse - BMW E92 M3 Diagnostic Tool
Full-featured diagnostic application with proper BMW CAN addressing
"""
import sys
import subprocess
import struct
import time
import os
from datetime import datetime
from pathlib import Path

import can

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QFrame,
    QComboBox, QGroupBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex
from PyQt6.QtGui import QFont, QColor


# BMW E92 M3 ECU Configuration
# Format: {"name": (request_id, response_id, description, timeout_ms)}
# BMW E-series uses physical diagnostic addressing
# Request ID = base + physical address, Response ID = request + 8
# Timeout: Some ECUs (like FRM) are slower and need longer timeouts
BMW_ECUS = {
    "DME": (0x7E0, 0x7E8, "Engine Control (MSV80)", 1.0),
    "EGS": (0x7E1, 0x7E9, "Transmission Control", 1.0),
    "DSC": (0x760, 0x768, "Dynamic Stability Control", 1.5),
    "KOMBI": (0x720, 0x728, "Instrument Cluster", 1.5),
    "CAS": (0x740, 0x748, "Car Access System", 2.0),
    "FRM": (0x730, 0x738, "Footwell Module", 2.5),  # FRM is slow
    "JBE": (0x750, 0x758, "Junction Box Electronics", 2.0),
    "EPS": (0x7A0, 0x7A8, "Electric Power Steering", 1.0),
    "SZL": (0x714, 0x71C, "Steering Column Switch", 1.0),
    "IHKA": (0x7A4, 0x7AC, "Climate Control", 1.5),
    "PDC": (0x780, 0x788, "Park Distance Control", 1.0),
    "CIC": (0x710, 0x718, "iDrive Controller", 2.0),
    "TCU": (0x770, 0x778, "Telematics Control", 1.5),
    "RLS": (0x724, 0x72C, "Rain/Light Sensor", 1.0),
    "SHD": (0x744, 0x74C, "Sunroof Module", 1.0),
    "TPMS": (0x754, 0x75C, "Tire Pressure Monitor", 1.0),
}

# Default timeout for unknown ECUs
DEFAULT_TIMEOUT = 1.5

# OBD-II Functional address (broadcasts to all emission-related ECUs)
OBD_FUNCTIONAL_ID = 0x7DF

# UDS Service IDs
UDS_DIAGNOSTIC_SESSION = 0x10
UDS_ECU_RESET = 0x11
UDS_SECURITY_ACCESS = 0x27
UDS_CLEAR_DTC = 0x14
UDS_READ_DTC = 0x19
UDS_READ_DATA_BY_ID = 0x22
UDS_ROUTINE_CONTROL = 0x31
UDS_TESTER_PRESENT = 0x3E

# Security Access Levels (BMW E-series)
SECURITY_LEVEL_01 = 0x01  # Standard diagnostics
SECURITY_LEVEL_03 = 0x03  # Extended diagnostics
SECURITY_LEVEL_11 = 0x11  # Programming (flash)

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

# Comprehensive BMW E92 M3 DTC Database
# Organized by system for easy lookup
DTC_DESCRIPTIONS = {
    # === Engine/DME (S65 V8) ===
    0x0100: "Mass Air Flow Circuit Malfunction",
    0x0101: "Mass Air Flow Circuit Range/Performance",
    0x0102: "Mass Air Flow Circuit Low Input",
    0x0103: "Mass Air Flow Circuit High Input",
    0x0110: "Intake Air Temperature Circuit Malfunction",
    0x0115: "Engine Coolant Temperature Circuit Malfunction",
    0x0116: "Engine Coolant Temp Circuit Range/Performance",
    0x0117: "Engine Coolant Temp Circuit Low",
    0x0118: "Engine Coolant Temp Circuit High",
    0x0120: "Throttle Position Sensor Circuit Malfunction",
    0x0121: "Throttle Position Sensor Range/Performance",
    0x0122: "Throttle Position Sensor Low",
    0x0123: "Throttle Position Sensor High",
    0x0130: "O2 Sensor Circuit Malfunction (Bank 1 Sensor 1)",
    0x0131: "O2 Sensor Low Voltage (Bank 1 Sensor 1)",
    0x0132: "O2 Sensor High Voltage (Bank 1 Sensor 1)",
    0x0133: "O2 Sensor Slow Response (Bank 1 Sensor 1)",
    0x0134: "O2 Sensor No Activity (Bank 1 Sensor 1)",
    0x0135: "O2 Sensor Heater Circuit (Bank 1 Sensor 1)",
    0x0150: "O2 Sensor Circuit Malfunction (Bank 2 Sensor 1)",
    0x0151: "O2 Sensor Low Voltage (Bank 2 Sensor 1)",
    0x0152: "O2 Sensor High Voltage (Bank 2 Sensor 1)",
    0x0171: "System Too Lean (Bank 1)",
    0x0172: "System Too Rich (Bank 1)",
    0x0174: "System Too Lean (Bank 2)",
    0x0175: "System Too Rich (Bank 2)",
    0x0201: "Injector Circuit Malfunction - Cylinder 1",
    0x0202: "Injector Circuit Malfunction - Cylinder 2",
    0x0203: "Injector Circuit Malfunction - Cylinder 3",
    0x0204: "Injector Circuit Malfunction - Cylinder 4",
    0x0205: "Injector Circuit Malfunction - Cylinder 5",
    0x0206: "Injector Circuit Malfunction - Cylinder 6",
    0x0207: "Injector Circuit Malfunction - Cylinder 7",
    0x0208: "Injector Circuit Malfunction - Cylinder 8",
    0x0300: "Random/Multiple Cylinder Misfire Detected",
    0x0301: "Cylinder 1 Misfire Detected",
    0x0302: "Cylinder 2 Misfire Detected",
    0x0303: "Cylinder 3 Misfire Detected",
    0x0304: "Cylinder 4 Misfire Detected",
    0x0305: "Cylinder 5 Misfire Detected",
    0x0306: "Cylinder 6 Misfire Detected",
    0x0307: "Cylinder 7 Misfire Detected",
    0x0308: "Cylinder 8 Misfire Detected",
    0x0335: "Crankshaft Position Sensor A Circuit",
    0x0336: "Crankshaft Position Sensor A Range/Performance",
    0x0340: "Camshaft Position Sensor A Circuit (Bank 1)",
    0x0341: "Camshaft Position Sensor A Range/Performance (Bank 1)",
    0x0345: "Camshaft Position Sensor A Circuit (Bank 2)",
    0x0365: "Camshaft Position Sensor B Circuit (Bank 1)",
    0x0390: "Camshaft Position Sensor B Circuit (Bank 2)",
    0x0420: "Catalyst Efficiency Below Threshold (Bank 1)",
    0x0430: "Catalyst Efficiency Below Threshold (Bank 2)",
    0x0442: "EVAP System Leak Detected (Small)",
    0x0455: "EVAP System Leak Detected (Large)",
    0x0500: "Vehicle Speed Sensor Malfunction",
    0x0505: "Idle Control System Malfunction",
    0x0506: "Idle Control System RPM Lower Than Expected",
    0x0507: "Idle Control System RPM Higher Than Expected",

    # === S65 V8 Specific (VANOS/Throttle) ===
    0x1520: "VANOS Exhaust Timing Over-Retarded (Bank 1)",
    0x1521: "VANOS Exhaust Timing Over-Advanced (Bank 1)",
    0x1523: "VANOS Intake Timing Over-Retarded (Bank 1)",
    0x1524: "VANOS Intake Timing Over-Advanced (Bank 1)",
    0x1530: "VANOS Exhaust Timing Over-Retarded (Bank 2)",
    0x1531: "VANOS Exhaust Timing Over-Advanced (Bank 2)",
    0x1533: "VANOS Intake Timing Over-Retarded (Bank 2)",
    0x1534: "VANOS Intake Timing Over-Advanced (Bank 2)",
    0x2A05: "Throttle Actuator Control Motor Circuit Open",
    0x2A07: "Throttle Actuator Control Motor Performance",
    0x2AAE: "Electric Fuel Pump Control Circuit",
    0x2AAF: "Fuel Pump Control Circuit",
    0x2DFC: "DME: Internal Error",

    # === Transmission/EGS (SMG/DCT) ===
    0x0700: "Transmission Control System Malfunction",
    0x0705: "Transmission Range Sensor Circuit",
    0x0710: "Transmission Fluid Temperature Sensor Circuit",
    0x0715: "Input/Turbine Speed Sensor Circuit",
    0x0720: "Output Speed Sensor Circuit",
    0x0730: "Incorrect Gear Ratio",
    0x0740: "Torque Converter Clutch Solenoid",
    0x0750: "Shift Solenoid A Malfunction",
    0x0755: "Shift Solenoid B Malfunction",
    0x0760: "Shift Solenoid C Malfunction",
    0x0765: "Shift Solenoid D Malfunction",
    0x17F0: "SMG Hydraulic Pump Motor",
    0x17F1: "SMG Clutch Position Sensor",
    0x17F2: "SMG Gear Position Sensor",

    # === DSC/ABS ===
    0x0562: "System Voltage Low",
    0x0563: "System Voltage High",
    0x4010: "DSC: System Malfunction",
    0xC000: "ABS Hydraulic Pump Motor",
    0xC100: "Wheel Speed Sensor Front Left",
    0xC110: "Wheel Speed Sensor Front Right",
    0xC120: "Wheel Speed Sensor Rear Left",
    0xC130: "Wheel Speed Sensor Rear Right",
    0xC150: "ABS Control Module Internal Error",
    0xC200: "Steering Angle Sensor",
    0xC210: "Yaw Rate Sensor",
    0xC220: "Lateral Acceleration Sensor",
    0xC230: "Longitudinal Acceleration Sensor",

    # === FRM (Footwell Module) ===
    0xA0A0: "FRM: Internal Error",
    0xA0A1: "FRM: EEPROM Error",
    0xA0B0: "FRM: Light Output Error",
    0xA0B1: "FRM: Headlight Left Short Circuit",
    0xA0B2: "FRM: Headlight Right Short Circuit",
    0xA0B3: "FRM: Turn Signal Left Malfunction",
    0xA0B4: "FRM: Turn Signal Right Malfunction",
    0xA0B5: "FRM: Brake Light Left Error",
    0xA0B6: "FRM: Brake Light Right Error",
    0xA0B7: "FRM: Tail Light Error",
    0xA0C0: "FRM: Window Regulator Front Left",
    0xA0C1: "FRM: Window Regulator Front Right",
    0xA0C2: "FRM: Window Regulator Rear Left",
    0xA0C3: "FRM: Window Regulator Rear Right",
    0xA0D0: "FRM: Central Locking Malfunction",
    0xA0E0: "FRM: Wiper Motor Error",

    # === CAS (Car Access System) ===
    0xA100: "CAS: EWS Manipulation Detected",
    0xA101: "CAS: Key Not Detected",
    0xA102: "CAS: Key Battery Low",
    0xA103: "CAS: Starter Signal Error",
    0xA104: "CAS: Terminal 15 Error",
    0xA105: "CAS: Terminal 50 Error",

    # === KOMBI (Instrument Cluster) ===
    0xA200: "KOMBI: Internal Error",
    0xA201: "KOMBI: Fuel Level Sensor",
    0xA202: "KOMBI: Coolant Level Sensor",
    0xA203: "KOMBI: Oil Level Sensor",
    0xA204: "KOMBI: Ambient Temperature Sensor",

    # === Communication Bus ===
    0xD000: "Communication Bus Error",
    0xD001: "PT-CAN Communication Error",
    0xD002: "K-CAN Communication Error",
    0xD003: "MOST Bus Communication Error",
    0xD100: "Lost Communication with DME",
    0xD101: "Lost Communication with EGS",
    0xD102: "Lost Communication with DSC",
    0xD103: "Lost Communication with FRM",
    0xD104: "Lost Communication with CAS",

    # === Airbag/SRS ===
    0xB1000: "Airbag Control Module Internal Error",
    0xB1001: "Driver Airbag Circuit",
    0xB1002: "Passenger Airbag Circuit",
    0xB1003: "Side Airbag Driver Circuit",
    0xB1004: "Side Airbag Passenger Circuit",
    0xB1010: "Seatbelt Pretensioner Driver",
    0xB1011: "Seatbelt Pretensioner Passenger",
    0xB1020: "Crash Sensor Front",
    0xB1021: "Crash Sensor Side Left",
    0xB1022: "Crash Sensor Side Right",

    # === O2 Sensors (Post-Cat) ===
    0x0136: "O2 Sensor Circuit Malfunction (Bank 1 Sensor 2)",
    0x0137: "O2 Sensor Low Voltage (Bank 1 Sensor 2)",
    0x0138: "O2 Sensor High Voltage (Bank 1 Sensor 2)",
    0x0140: "O2 Sensor No Activity (Bank 1 Sensor 2)",
    0x0156: "O2 Sensor Circuit Malfunction (Bank 2 Sensor 2)",
    0x0157: "O2 Sensor Low Voltage (Bank 2 Sensor 2)",
    0x0158: "O2 Sensor High Voltage (Bank 2 Sensor 2)",
    0x0160: "O2 Sensor No Activity (Bank 2 Sensor 2)",

    # === O2 Heater Circuits ===
    0x0030: "O2 Sensor Heater Circuit (Bank 1 Sensor 1)",
    0x0031: "O2 Sensor Heater Low (Bank 1 Sensor 1)",
    0x0032: "O2 Sensor Heater High (Bank 1 Sensor 1)",
    0x0036: "O2 Sensor Heater Circuit (Bank 1 Sensor 2)",
    0x0050: "O2 Sensor Heater Circuit (Bank 2 Sensor 1)",
    0x0056: "O2 Sensor Heater Circuit (Bank 2 Sensor 2)",
    0x30FF: "O2 Sensor Heater Control Circuit",
}

# Live Data PIDs (BMW ReadDataByIdentifier)
# Format: {pid: (name, unit, scale_func)}
# Scale functions convert raw bytes to display value
LIVE_DATA_PIDS = {
    # Engine data (from DME)
    0x1001: ("Engine RPM", "RPM", lambda b: ((b[0] << 8) | b[1]) / 4),
    0x1002: ("Coolant Temp", "°C", lambda b: b[0] - 40),
    0x1003: ("Intake Air Temp", "°C", lambda b: b[0] - 40),
    0x1004: ("Engine Load", "%", lambda b: b[0] * 100 / 255),
    0x1005: ("Throttle Position", "%", lambda b: b[0] * 100 / 255),
    0x1006: ("Vehicle Speed", "km/h", lambda b: b[0]),
    0x1007: ("Ignition Timing", "°", lambda b: (b[0] - 128) / 2),
    0x1008: ("MAF Sensor", "g/s", lambda b: ((b[0] << 8) | b[1]) / 100),
    0x1009: ("Fuel Pressure", "kPa", lambda b: ((b[0] << 8) | b[1]) * 0.1),
    0x100A: ("Oil Temp", "°C", lambda b: b[0] - 40),
    0x100B: ("Oil Pressure", "bar", lambda b: b[0] * 0.1),
    0x100C: ("Battery Voltage", "V", lambda b: ((b[0] << 8) | b[1]) * 0.001),

    # Standard OBD-II PIDs (via functional request)
    0xF40C: ("Engine RPM (OBD)", "RPM", lambda b: ((b[0] << 8) | b[1]) / 4),
    0xF405: ("Coolant Temp (OBD)", "°C", lambda b: b[0] - 40),
    0xF40F: ("Intake Air Temp (OBD)", "°C", lambda b: b[0] - 40),
    0xF404: ("Engine Load (OBD)", "%", lambda b: b[0] * 100 / 255),
    0xF411: ("Throttle Position (OBD)", "%", lambda b: b[0] * 100 / 255),
    0xF40D: ("Vehicle Speed (OBD)", "km/h", lambda b: b[0]),
}

# ECU Identification DIDs (Data Identifiers)
ECU_INFO_DIDS = {
    0xF190: "VIN",
    0xF191: "ECU Hardware Number",
    0xF192: "ECU Software Number",
    0xF193: "ECU Part Number",
    0xF194: "ECU Serial Number",
    0xF195: "ECU Hardware Version",
    0xF187: "Supplier ECU Software Version",
    0xF18C: "ECU Serial Number",
    0xF1A0: "Bootloader Version",
}


class SessionLogger:
    """
    Logs all diagnostic session activity to file.
    Creates timestamped log files in the logs directory.
    """

    def __init__(self, log_dir=None):
        """Initialize session logger."""
        if log_dir is None:
            # Default to ~/.e92pulse/logs
            log_dir = Path.home() / ".e92pulse" / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create session log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}.log"
        self.file_handle = None
        self._start_session()

    def _start_session(self):
        """Start a new logging session."""
        self.file_handle = open(self.log_file, 'w')
        self._write_header()

    def _write_header(self):
        """Write session header."""
        self.file_handle.write("=" * 60 + "\n")
        self.file_handle.write("E92 Pulse - Diagnostic Session Log\n")
        self.file_handle.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.file_handle.write("=" * 60 + "\n\n")
        self.file_handle.flush()

    def log(self, message, level="INFO"):
        """Log a message with timestamp."""
        if self.file_handle:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.file_handle.write(f"[{timestamp}] [{level}] {message}\n")
            self.file_handle.flush()

    def log_can_frame(self, direction, can_id, data):
        """Log a CAN frame."""
        data_hex = ' '.join(f'{b:02X}' for b in data)
        self.log(f"{direction} ID=0x{can_id:03X} DATA=[{data_hex}]", "CAN")

    def log_operation(self, operation, ecu=None, result=None):
        """Log a diagnostic operation."""
        msg = f"Operation: {operation}"
        if ecu:
            msg += f" ECU={ecu}"
        if result:
            msg += f" Result={result}"
        self.log(msg, "OP")

    def log_dtc(self, ecu, code, description, active):
        """Log a DTC reading."""
        status = "ACTIVE" if active else "STORED"
        self.log(f"DTC: {ecu} {code} [{status}] {description}", "DTC")

    def close(self):
        """Close the session log."""
        if self.file_handle:
            self.file_handle.write("\n" + "=" * 60 + "\n")
            self.file_handle.write(f"Session ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.file_handle.write("=" * 60 + "\n")
            self.file_handle.close()
            self.file_handle = None

    def get_log_path(self):
        """Get the current log file path."""
        return str(self.log_file)


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
    """
    ISO-TP (ISO 15765-2) handler for multi-frame CAN messages.
    Supports full flow control with configurable parameters.
    """

    # Flow Control flags
    FC_CONTINUE = 0x30  # Continue To Send
    FC_WAIT = 0x31      # Wait
    FC_OVERFLOW = 0x32  # Overflow/Abort

    def __init__(self, bus, tx_id, rx_id, block_size=0, st_min=0):
        """
        Initialize ISO-TP handler.

        Args:
            bus: python-can bus instance
            tx_id: CAN ID to transmit on
            rx_id: CAN ID to receive on
            block_size: Number of frames to receive before sending FC (0 = no limit)
            st_min: Minimum separation time between frames in ms (0-127) or us (0xF1-0xF9)
        """
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.block_size = block_size
        self.st_min = st_min

    def send_receive(self, data, timeout=1.0):
        """Send data and receive response using ISO-TP framing."""
        data = list(data)

        # Clear any pending messages
        self._flush_rx()

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

            # Parse flow control parameters
            fc_flag = fc[0] & 0x0F
            fc_block_size = fc[1] if len(fc) > 1 else 0
            fc_st_min = fc[2] if len(fc) > 2 else 0

            # Calculate delay between frames
            if fc_st_min <= 127:
                delay = fc_st_min / 1000.0  # milliseconds
            elif 0xF1 <= fc_st_min <= 0xF9:
                delay = (fc_st_min - 0xF0) / 10000.0  # 100-900 microseconds
            else:
                delay = 0.001  # default 1ms

            # Send Consecutive Frames
            seq = 1
            offset = 6
            frames_sent = 0
            while offset < len(data):
                cf = [0x20 | (seq & 0x0F)] + data[offset:offset+7]
                cf += [0x00] * (8 - len(cf))
                msg = can.Message(arbitration_id=self.tx_id, data=cf, is_extended_id=False)
                self.bus.send(msg)
                seq = (seq + 1) & 0x0F
                offset += 7
                frames_sent += 1

                # Wait for next flow control if block size reached
                if fc_block_size > 0 and frames_sent >= fc_block_size and offset < len(data):
                    fc = self._recv_frame(timeout=0.5)
                    if not fc or (fc[0] & 0xF0) != 0x30:
                        return None
                    frames_sent = 0

                time.sleep(delay)

        # Receive response
        return self._receive_isotp(timeout)

    def _flush_rx(self):
        """Flush any pending receive messages."""
        while True:
            msg = self.bus.recv(timeout=0.01)
            if msg is None:
                break

    def _recv_frame(self, timeout=0.5):
        """Receive a single CAN frame matching our rx_id."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            response = self.bus.recv(timeout=min(0.1, end_time - time.time()))
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

            # Send Flow Control - Continue To Send, no block limit, no delay
            fc = can.Message(
                arbitration_id=self.tx_id,
                data=[self.FC_CONTINUE, self.block_size, self.st_min, 0x00, 0x00, 0x00, 0x00, 0x00],
                is_extended_id=False
            )
            self.bus.send(fc)

            # Receive Consecutive Frames
            expected_seq = 1
            while len(data) < length:
                cf = self._recv_frame(timeout=0.5)
                if not cf:
                    break

                cf_type = cf[0] & 0xF0
                if cf_type != 0x20:
                    # Not a consecutive frame - might be a negative response
                    if cf_type == 0x00 and cf[0] == 0x03 and len(cf) > 1 and cf[1] == 0x7F:
                        # Negative response
                        return cf[1:cf[0]+1]
                    break

                seq = cf[0] & 0x0F
                if seq != expected_seq:
                    # Sequence error - abort
                    break

                data.extend(cf[1:8])
                expected_seq = (expected_seq + 1) & 0x0F

            return data[:length]

        # Negative response (0x7F) in single frame
        elif frame[0] == 0x03 and len(frame) > 1 and frame[1] == 0x7F:
            return frame[1:4]

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
            elif self.operation == "read_live_data":
                results = self._read_live_data(bus, self.params.get("ecu_name", "DME"))
            elif self.operation == "read_ecu_info":
                results = self._read_ecu_info(bus, self.params.get("ecu_name"))
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

    def _security_access(self, bus, tx_id, rx_id, level=SECURITY_LEVEL_01):
        """
        Perform UDS Security Access (0x27) authentication.

        BMW E-series uses a simple seed-key algorithm for most security levels.
        This implements the standard diagnostic security access procedure.

        Args:
            bus: CAN bus instance
            tx_id: Transmit CAN ID
            rx_id: Receive CAN ID
            level: Security level (0x01, 0x03, or 0x11)

        Returns:
            True if security access granted, False otherwise
        """
        isotp = IsoTpHandler(bus, tx_id, rx_id)

        # Step 1: Request seed (level = odd number)
        response = isotp.send_receive([UDS_SECURITY_ACCESS, level], timeout=1.0)

        if not response or len(response) < 3:
            return False

        # Check for positive response
        if response[0] != UDS_SECURITY_ACCESS + 0x40:
            return False

        # Extract seed bytes (typically 2-4 bytes after service ID and sub-function)
        seed = response[2:]

        # If seed is all zeros, security is already unlocked
        if all(b == 0 for b in seed):
            return True

        # Calculate key using BMW E-series algorithm
        # This is the standard diagnostic access algorithm, not security-sensitive
        key = self._calculate_security_key(seed, level)

        # Step 2: Send key (level + 1 = even number)
        key_request = [UDS_SECURITY_ACCESS, level + 1] + key
        response = isotp.send_receive(key_request, timeout=1.0)

        if response and len(response) >= 2 and response[0] == UDS_SECURITY_ACCESS + 0x40:
            return True

        return False

    def _calculate_security_key(self, seed, level):
        """
        Calculate security key from seed using BMW E-series algorithm.

        This is the standard diagnostic algorithm used for service access.
        Different security levels may use different XOR masks.
        """
        # BMW E-series standard algorithm
        # XOR mask varies by security level
        if level == SECURITY_LEVEL_01:
            xor_mask = [0xA5, 0x96, 0xC3, 0x5A]
        elif level == SECURITY_LEVEL_03:
            xor_mask = [0x3E, 0xC1, 0x87, 0x2D]
        else:
            xor_mask = [0x5A, 0xA5, 0x69, 0x96]

        key = []
        for i, byte in enumerate(seed):
            # Apply XOR with rotating mask
            key.append(byte ^ xor_mask[i % len(xor_mask)])

        return key

    def _scan_ecus(self, bus):
        """Scan for ECUs using TesterPresent."""
        found = {}
        responding = 0
        total = len(BMW_ECUS)

        for i, (name, (tx_id, rx_id, desc, ecu_timeout)) in enumerate(BMW_ECUS.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Scanning {name}...", percent)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            response = isotp.send_receive([UDS_TESTER_PRESENT, 0x00], timeout=min(0.5, ecu_timeout))

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

            tx_id, rx_id, _, ecu_timeout = BMW_ECUS[ecu_name]
            self.progress.emit(f"Reading VIN from {ecu_name}...", 50)

            # Enter extended session first
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ReadDataByIdentifier - VIN is 0xF190
            response = isotp.send_receive([UDS_READ_DATA_BY_ID, 0xF1, 0x90], timeout=ecu_timeout)

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

        for i, (name, (tx_id, rx_id, desc, ecu_timeout)) in enumerate(ecus_to_scan.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Reading DTCs from {name}...", percent)

            # Enter extended session
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ReadDTCInformation - reportDTCByStatusMask (0x02), all DTCs (0xFF)
            response = isotp.send_receive([UDS_READ_DTC, 0x02, 0xFF], timeout=ecu_timeout)

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

        for i, (name, (tx_id, rx_id, _, ecu_timeout)) in enumerate(ecus_to_clear.items()):
            percent = int((i / total) * 100)
            self.progress.emit(f"Clearing DTCs from {name}...", percent)

            # Enter extended session
            self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

            isotp = IsoTpHandler(bus, tx_id, rx_id)
            # ClearDiagnosticInformation - all groups (0xFF 0xFF 0xFF)
            response = isotp.send_receive([UDS_CLEAR_DTC, 0xFF, 0xFF, 0xFF], timeout=ecu_timeout)

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

        tx_id, rx_id, desc, ecu_timeout = BMW_ECUS[ecu_name]
        self.progress.emit(f"Resetting {ecu_name}...", 50)

        # Enter extended session first
        if not self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED):
            return {"success": False, "ecu": ecu_name, "error": "Could not enter diagnostic session"}

        isotp = IsoTpHandler(bus, tx_id, rx_id)
        # Use longer timeout for reset operations
        reset_timeout = max(ecu_timeout, 2.0)
        response = isotp.send_receive([UDS_ECU_RESET, reset_type], timeout=reset_timeout)

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

        tx_id, rx_id, _, ecu_timeout = BMW_ECUS["DME"]
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

        tx_id, rx_id, _, ecu_timeout = BMW_ECUS["KOMBI"]
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

    def _read_live_data(self, bus, ecu_name="DME"):
        """Read live data from ECU."""
        if ecu_name not in BMW_ECUS:
            return {"error": f"Unknown ECU: {ecu_name}"}

        tx_id, rx_id, desc, ecu_timeout = BMW_ECUS[ecu_name]
        self.progress.emit(f"Reading live data from {ecu_name}...", 10)

        # Enter extended session
        self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

        data = {}
        isotp = IsoTpHandler(bus, tx_id, rx_id)
        total = len(LIVE_DATA_PIDS)

        for i, (pid, (name, unit, scale_func)) in enumerate(LIVE_DATA_PIDS.items()):
            percent = int(((i + 1) / total) * 100)
            self.progress.emit(f"Reading {name}...", percent)

            # ReadDataByIdentifier (0x22)
            response = isotp.send_receive([
                UDS_READ_DATA_BY_ID,
                (pid >> 8) & 0xFF,
                pid & 0xFF
            ], timeout=0.5)

            if response and len(response) >= 4 and response[0] == UDS_READ_DATA_BY_ID + 0x40:
                # Response: 62 [PID_HI] [PID_LO] [DATA...]
                try:
                    raw_data = response[3:]
                    if raw_data:
                        value = scale_func(raw_data)
                        data[name] = {"value": value, "unit": unit, "raw": raw_data}
                except Exception:
                    pass

        self.progress.emit("Complete", 100)
        return {"data": data, "ecu": ecu_name}

    def _read_ecu_info(self, bus, ecu_name):
        """Read ECU identification information."""
        if ecu_name not in BMW_ECUS:
            return {"error": f"Unknown ECU: {ecu_name}"}

        tx_id, rx_id, desc, ecu_timeout = BMW_ECUS[ecu_name]
        self.progress.emit(f"Reading {ecu_name} info...", 10)

        # Enter extended session
        self._enter_session(bus, tx_id, rx_id, SESSION_EXTENDED)

        info = {"ecu": ecu_name, "description": desc}
        isotp = IsoTpHandler(bus, tx_id, rx_id)
        total = len(ECU_INFO_DIDS)

        for i, (did, did_name) in enumerate(ECU_INFO_DIDS.items()):
            percent = int(((i + 1) / total) * 100)
            self.progress.emit(f"Reading {did_name}...", percent)

            # ReadDataByIdentifier (0x22)
            response = isotp.send_receive([
                UDS_READ_DATA_BY_ID,
                (did >> 8) & 0xFF,
                did & 0xFF
            ], timeout=ecu_timeout)

            if response and len(response) >= 4 and response[0] == UDS_READ_DATA_BY_ID + 0x40:
                # Response: 62 [DID_HI] [DID_LO] [DATA...]
                raw_data = response[3:]
                # Try to decode as ASCII string
                try:
                    value = ''.join(chr(b) for b in raw_data if 32 <= b <= 126).strip()
                    if value:
                        info[did_name] = value
                except Exception:
                    # If not a string, show as hex
                    info[did_name] = ' '.join(f'{b:02X}' for b in raw_data)

        self.progress.emit("Complete", 100)
        return info


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

        # Initialize session logger
        self.session_logger = SessionLogger()

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
        tabs.addTab(self._create_live_data_tab(), "Live Data")
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
        for name, (tx, rx, desc, _) in BMW_ECUS.items():
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

    def _create_live_data_tab(self):
        """Create Live Data tab with ECU info and real-time sensor data."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ECU Info section
        info_group = QGroupBox("ECU Information")
        info_layout = QVBoxLayout(info_group)

        ecu_row = QHBoxLayout()
        ecu_row.addWidget(QLabel("ECU:"))
        self.info_ecu_combo = QComboBox()
        for name, (tx, rx, desc, _) in BMW_ECUS.items():
            self.info_ecu_combo.addItem(f"{name} - {desc}", name)
        self.info_ecu_combo.setMinimumWidth(300)
        ecu_row.addWidget(self.info_ecu_combo)

        self.read_info_btn = QPushButton("Read ECU Info")
        self.read_info_btn.clicked.connect(self.read_ecu_info)
        self.read_info_btn.setEnabled(False)
        ecu_row.addWidget(self.read_info_btn)

        ecu_row.addStretch()
        info_layout.addLayout(ecu_row)

        self.ecu_info_table = QTableWidget()
        self.ecu_info_table.setColumnCount(2)
        self.ecu_info_table.setHorizontalHeaderLabels(["Property", "Value"])
        self.ecu_info_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ecu_info_table.setColumnWidth(0, 180)
        self.ecu_info_table.setMaximumHeight(200)
        info_layout.addWidget(self.ecu_info_table)

        layout.addWidget(info_group)

        # Live Data section
        live_group = QGroupBox("Live Sensor Data")
        live_layout = QVBoxLayout(live_group)

        live_btn_row = QHBoxLayout()
        self.read_live_btn = QPushButton("Read Live Data")
        self.read_live_btn.clicked.connect(self.read_live_data)
        self.read_live_btn.setEnabled(False)
        live_btn_row.addWidget(self.read_live_btn)

        live_btn_row.addStretch()
        live_layout.addLayout(live_btn_row)

        self.live_progress = QProgressBar()
        self.live_progress.setMinimumHeight(20)
        self.live_progress.setRange(0, 100)
        self.live_progress.hide()
        live_layout.addWidget(self.live_progress)

        self.live_data_table = QTableWidget()
        self.live_data_table.setColumnCount(3)
        self.live_data_table.setHorizontalHeaderLabels(["Parameter", "Value", "Unit"])
        self.live_data_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.live_data_table.setColumnWidth(1, 120)
        self.live_data_table.setColumnWidth(2, 80)
        live_layout.addWidget(self.live_data_table)

        layout.addWidget(live_group)

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
        for name, (tx, rx, desc, _) in BMW_ECUS.items():
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

        # Log info label
        if self.session_logger:
            log_info = QLabel(f"Session log: {self.session_logger.get_log_path()}")
            log_info.setStyleSheet("color: #888; font-size: 10px;")
            log_info.setWordWrap(True)
            layout.addWidget(log_info)

        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear Display")
        clear_btn.clicked.connect(lambda: self.log_output.clear())
        btn_layout.addWidget(clear_btn)

        save_btn = QPushButton("Save Log As...")
        save_btn.clicked.connect(self.save_log)
        btn_layout.addWidget(save_btn)

        open_folder_btn = QPushButton("Open Log Folder")
        open_folder_btn.clicked.connect(self.open_log_folder)
        btn_layout.addWidget(open_folder_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return tab

    def save_log(self):
        """Save the current log to a file."""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Log", f"e92pulse_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.log_output.toPlainText())
                self.log(f"Log saved to: {filename}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not save log: {e}")

    def open_log_folder(self):
        """Open the log folder in file manager."""
        if self.session_logger:
            log_dir = str(self.session_logger.log_dir)
            try:
                subprocess.Popen(['xdg-open', log_dir])
            except Exception:
                QMessageBox.information(self, "Log Folder", f"Log folder: {log_dir}")

    def log(self, msg):
        """Log message to both UI and session file."""
        self.log_output.append(msg)
        if self.session_logger:
            self.session_logger.log(msg)

    def closeEvent(self, event):
        """Handle window close - cleanup session logger."""
        if self.session_logger:
            self.session_logger.close()
        event.accept()

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
        self.read_info_btn.setEnabled(enabled)
        self.read_live_btn.setEnabled(enabled)

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

    def read_ecu_info(self):
        """Read ECU identification information."""
        ecu_name = self.info_ecu_combo.currentData()
        self.read_info_btn.setEnabled(False)
        self.ecu_info_table.setRowCount(0)
        self.live_progress.show()
        self.log(f"Reading {ecu_name} information...")

        self.worker = CANWorker("read_ecu_info", self.interface, {"ecu_name": ecu_name})
        self.worker.progress.connect(self._on_live_progress)
        self.worker.finished.connect(self._on_ecu_info_complete)
        self.worker.start()

    def _on_ecu_info_complete(self, results):
        """Handle ECU info read completion."""
        self.live_progress.hide()
        self.read_info_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        self.ecu_info_table.setRowCount(0)
        for key, value in results.items():
            if key not in ("ecu", "description"):
                row = self.ecu_info_table.rowCount()
                self.ecu_info_table.insertRow(row)
                self.ecu_info_table.setItem(row, 0, QTableWidgetItem(key))
                self.ecu_info_table.setItem(row, 1, QTableWidgetItem(str(value)))

        self.log(f"ECU info read complete: {results.get('ecu')}")

    def read_live_data(self):
        """Read live sensor data from DME."""
        self.read_live_btn.setEnabled(False)
        self.live_data_table.setRowCount(0)
        self.live_progress.show()
        self.log("Reading live data from DME...")

        self.worker = CANWorker("read_live_data", self.interface, {"ecu_name": "DME"})
        self.worker.progress.connect(self._on_live_progress)
        self.worker.finished.connect(self._on_live_data_complete)
        self.worker.start()

    def _on_live_progress(self, msg, percent):
        """Handle live data progress updates."""
        self.log(f"  {msg}")
        self.live_progress.setValue(percent)

    def _on_live_data_complete(self, results):
        """Handle live data read completion."""
        self.live_progress.hide()
        self.read_live_btn.setEnabled(True)

        if "error" in results:
            self.log(f"Error: {results['error']}")
            return

        data = results.get("data", {})
        self.live_data_table.setRowCount(0)

        for name, info in data.items():
            row = self.live_data_table.rowCount()
            self.live_data_table.insertRow(row)
            self.live_data_table.setItem(row, 0, QTableWidgetItem(name))
            value = info.get("value", "N/A")
            if isinstance(value, float):
                value = f"{value:.1f}"
            self.live_data_table.setItem(row, 1, QTableWidgetItem(str(value)))
            self.live_data_table.setItem(row, 2, QTableWidgetItem(info.get("unit", "")))

        self.log(f"Live data read complete: {len(data)} parameters")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("E92 Pulse")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
