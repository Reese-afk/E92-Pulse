"""
Port Discovery System

Automatically detects K+DCAN USB diagnostic cables on Linux.
Implements intelligent ranking and selection of diagnostic interfaces.
"""

import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class ChipType(IntEnum):
    """USB-serial chip types, ranked by preference for BMW diagnostics."""

    FTDI = 100  # Most reliable for BMW K+DCAN
    FT232 = 95  # FTDI FT232 variant
    CH340 = 70  # Common in cheaper cables
    CP210X = 60  # Silicon Labs
    PL2303 = 50  # Prolific (older)
    OTHER = 20  # Unknown chip
    UNKNOWN = 10


@dataclass
class PortInfo:
    """Information about a detected serial port."""

    device: str  # e.g., /dev/ttyUSB0
    name: str  # Human-readable name
    description: str  # Detailed description
    hwid: str  # Hardware ID string
    vid: int | None  # USB Vendor ID
    pid: int | None  # USB Product ID
    serial_number: str | None  # USB serial number
    manufacturer: str | None  # Manufacturer string
    product: str | None  # Product string
    chip_type: ChipType  # Detected chip type
    by_id_path: str | None  # Stable /dev/serial/by-id path
    score: int  # Ranking score (higher = more preferred)

    def __str__(self) -> str:
        return f"{self.device} ({self.name}) - Score: {self.score}"


class PortDiscovery:
    """
    Discovers and ranks serial ports for BMW K+DCAN diagnostics.

    Prioritizes:
    1. Stable device paths (/dev/serial/by-id)
    2. FTDI chips (most reliable for BMW)
    3. Ports with BMW-related identifiers
    """

    # Known USB VID:PID pairs for K+DCAN cables
    KNOWN_KDCAN_DEVICES = {
        (0x0403, 0x6001): ("FTDI FT232R", ChipType.FTDI, 100),
        (0x0403, 0x6010): ("FTDI FT2232", ChipType.FTDI, 95),
        (0x0403, 0x6011): ("FTDI FT4232", ChipType.FTDI, 95),
        (0x0403, 0x6014): ("FTDI FT232H", ChipType.FT232, 90),
        (0x0403, 0x6015): ("FTDI FT-X", ChipType.FT232, 90),
        (0x1A86, 0x7523): ("CH340", ChipType.CH340, 70),
        (0x1A86, 0x5523): ("CH341", ChipType.CH340, 65),
        (0x10C4, 0xEA60): ("CP210x", ChipType.CP210X, 60),
        (0x067B, 0x2303): ("PL2303", ChipType.PL2303, 50),
    }

    # Keywords that suggest BMW diagnostic use
    BMW_KEYWORDS = ("dcan", "k+dcan", "kdcan", "ediabas", "inpa", "ista", "bmw", "obd")

    def __init__(self, last_known_port: str | None = None):
        """
        Initialize port discovery.

        Args:
            last_known_port: Previously successful port for bonus scoring
        """
        self.last_known_port = last_known_port
        self._cached_ports: list[PortInfo] | None = None

    def discover_ports(self, force_rescan: bool = False) -> list[PortInfo]:
        """
        Discover available serial ports.

        Args:
            force_rescan: Force re-enumeration of ports

        Returns:
            List of PortInfo sorted by preference (best first)
        """
        if self._cached_ports is not None and not force_rescan:
            return self._cached_ports

        try:
            from serial.tools import list_ports
        except ImportError:
            logger.error("pyserial not installed")
            return []

        ports: list[PortInfo] = []

        for port in list_ports.comports():
            try:
                port_info = self._create_port_info(port)
                if port_info:
                    ports.append(port_info)
            except Exception as e:
                logger.warning(f"Error processing port {port.device}: {e}")

        # Sort by score (descending)
        ports.sort(key=lambda p: p.score, reverse=True)

        self._cached_ports = ports
        logger.info(f"Discovered {len(ports)} serial port(s)")

        for port in ports:
            logger.debug(f"  {port}")

        return ports

    def _create_port_info(self, port) -> PortInfo | None:
        """Create PortInfo from pyserial port info."""
        device = port.device

        # Skip non-USB serial ports
        if not any(
            x in device for x in ("ttyUSB", "ttyACM", "serial")
        ):
            return None

        # Extract VID:PID
        vid = port.vid
        pid = port.pid

        # Determine chip type
        chip_type = ChipType.UNKNOWN
        chip_name = "Unknown"
        base_score = 10

        if vid and pid:
            key = (vid, pid)
            if key in self.KNOWN_KDCAN_DEVICES:
                chip_name, chip_type, base_score = self.KNOWN_KDCAN_DEVICES[key]
            else:
                # Try to identify by VID alone
                if vid == 0x0403:  # FTDI
                    chip_type = ChipType.FTDI
                    chip_name = "FTDI (unknown PID)"
                    base_score = 80
                elif vid == 0x1A86:  # CH340/CH341
                    chip_type = ChipType.CH340
                    chip_name = "CH34x"
                    base_score = 65

        # Find stable by-id path
        by_id_path = self._find_by_id_path(device)
        if by_id_path:
            base_score += 15  # Bonus for stable path

        # Bonus for BMW-related keywords
        combined_text = " ".join(
            filter(
                None,
                [
                    port.description or "",
                    port.product or "",
                    port.manufacturer or "",
                    by_id_path or "",
                ],
            )
        ).lower()

        for keyword in self.BMW_KEYWORDS:
            if keyword in combined_text:
                base_score += 10
                break

        # Bonus for last known good port
        if self.last_known_port and (
            device == self.last_known_port or by_id_path == self.last_known_port
        ):
            base_score += 50

        return PortInfo(
            device=device,
            name=chip_name,
            description=port.description or "",
            hwid=port.hwid or "",
            vid=vid,
            pid=pid,
            serial_number=port.serial_number,
            manufacturer=port.manufacturer,
            product=port.product,
            chip_type=chip_type,
            by_id_path=by_id_path,
            score=base_score,
        )

    def _find_by_id_path(self, device: str) -> str | None:
        """Find the stable /dev/serial/by-id path for a device."""
        by_id_dir = Path("/dev/serial/by-id")
        if not by_id_dir.exists():
            return None

        try:
            device_path = Path(device).resolve()
            for symlink in by_id_dir.iterdir():
                if symlink.is_symlink():
                    target = symlink.resolve()
                    if target == device_path:
                        return str(symlink)
        except Exception as e:
            logger.debug(f"Error finding by-id path: {e}")

        return None

    def get_best_port(self) -> PortInfo | None:
        """Get the highest-ranked port."""
        ports = self.discover_ports()
        return ports[0] if ports else None

    def get_port_by_device(self, device: str) -> PortInfo | None:
        """Find a specific port by device path."""
        ports = self.discover_ports()
        for port in ports:
            if port.device == device or port.by_id_path == device:
                return port
        return None

    def refresh(self) -> list[PortInfo]:
        """Force refresh of port list."""
        return self.discover_ports(force_rescan=True)


def rank_ports_for_kdcan(ports: list[PortInfo]) -> list[PortInfo]:
    """
    Additional ranking logic for K+DCAN specifically.

    This function applies BMW-specific heuristics on top of
    the general port discovery scoring.
    """
    # Already sorted by score from discover_ports()
    # Apply additional BMW-specific logic if needed
    return sorted(ports, key=lambda p: p.score, reverse=True)
