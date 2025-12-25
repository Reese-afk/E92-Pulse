"""
Tests for port discovery and selection heuristics.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from e92_pulse.core.discovery import PortDiscovery, PortInfo, ChipType, rank_ports_for_kdcan


class TestPortInfo:
    """Tests for PortInfo dataclass."""

    def test_port_info_creation(self):
        """Test creating PortInfo with all fields."""
        port = PortInfo(
            device="/dev/ttyUSB0",
            name="FTDI FT232R",
            description="USB Serial",
            hwid="USB VID:PID=0403:6001",
            vid=0x0403,
            pid=0x6001,
            serial_number="A12345",
            manufacturer="FTDI",
            product="FT232R USB UART",
            chip_type=ChipType.FTDI,
            by_id_path="/dev/serial/by-id/usb-FTDI_FT232R_A12345-if00-port0",
            score=100,
        )

        assert port.device == "/dev/ttyUSB0"
        assert port.chip_type == ChipType.FTDI
        assert port.score == 100

    def test_port_info_str(self):
        """Test PortInfo string representation."""
        port = PortInfo(
            device="/dev/ttyUSB0",
            name="FTDI",
            description="",
            hwid="",
            vid=None,
            pid=None,
            serial_number=None,
            manufacturer=None,
            product=None,
            chip_type=ChipType.FTDI,
            by_id_path=None,
            score=95,
        )

        assert "/dev/ttyUSB0" in str(port)
        assert "95" in str(port)


class TestChipType:
    """Tests for ChipType enumeration."""

    def test_chip_type_ranking(self):
        """Test chip types are ranked correctly."""
        assert ChipType.FTDI > ChipType.CH340
        assert ChipType.CH340 > ChipType.CP210X
        assert ChipType.CP210X > ChipType.PL2303
        assert ChipType.PL2303 > ChipType.OTHER
        assert ChipType.OTHER > ChipType.UNKNOWN


class TestPortDiscovery:
    """Tests for PortDiscovery class."""

    def test_known_kdcan_devices(self):
        """Test known K+DCAN device list."""
        discovery = PortDiscovery()

        # FTDI FT232R
        assert (0x0403, 0x6001) in discovery.KNOWN_KDCAN_DEVICES
        # CH340
        assert (0x1A86, 0x7523) in discovery.KNOWN_KDCAN_DEVICES

    def test_bmw_keywords(self):
        """Test BMW-related keyword detection."""
        discovery = PortDiscovery()

        assert "dcan" in discovery.BMW_KEYWORDS
        assert "kdcan" in discovery.BMW_KEYWORDS
        assert "ista" in discovery.BMW_KEYWORDS
        assert "bmw" in discovery.BMW_KEYWORDS

    def test_last_known_port_bonus(self):
        """Test last known port gets bonus score."""
        discovery = PortDiscovery(last_known_port="/dev/ttyUSB0")
        assert discovery.last_known_port == "/dev/ttyUSB0"

    @patch("e92_pulse.core.discovery.list_ports")
    def test_discover_empty(self, mock_list_ports):
        """Test discovery with no ports."""
        mock_list_ports.comports.return_value = []

        discovery = PortDiscovery()
        ports = discovery.discover_ports()

        assert ports == []

    @patch("e92_pulse.core.discovery.list_ports")
    def test_discover_ftdi_port(self, mock_list_ports):
        """Test discovery of FTDI port."""
        mock_port = Mock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.vid = 0x0403
        mock_port.pid = 0x6001
        mock_port.description = "FT232R USB UART"
        mock_port.hwid = "USB VID:PID=0403:6001"
        mock_port.serial_number = "A12345"
        mock_port.manufacturer = "FTDI"
        mock_port.product = "FT232R USB UART"

        mock_list_ports.comports.return_value = [mock_port]

        discovery = PortDiscovery()
        ports = discovery.discover_ports()

        assert len(ports) == 1
        assert ports[0].chip_type == ChipType.FTDI
        assert ports[0].score >= 80  # FTDI should have high score

    @patch("e92_pulse.core.discovery.list_ports")
    def test_ftdi_ranked_above_ch340(self, mock_list_ports):
        """Test FTDI ports are ranked above CH340."""
        ftdi_port = Mock()
        ftdi_port.device = "/dev/ttyUSB0"
        ftdi_port.vid = 0x0403
        ftdi_port.pid = 0x6001
        ftdi_port.description = "FTDI"
        ftdi_port.hwid = ""
        ftdi_port.serial_number = None
        ftdi_port.manufacturer = "FTDI"
        ftdi_port.product = None

        ch340_port = Mock()
        ch340_port.device = "/dev/ttyUSB1"
        ch340_port.vid = 0x1A86
        ch340_port.pid = 0x7523
        ch340_port.description = "CH340"
        ch340_port.hwid = ""
        ch340_port.serial_number = None
        ch340_port.manufacturer = None
        ch340_port.product = None

        mock_list_ports.comports.return_value = [ch340_port, ftdi_port]

        discovery = PortDiscovery()
        ports = discovery.discover_ports()

        assert len(ports) == 2
        # FTDI should be first (higher score)
        assert ports[0].chip_type == ChipType.FTDI
        assert ports[1].chip_type == ChipType.CH340

    @patch("e92_pulse.core.discovery.list_ports")
    def test_by_id_path_bonus(self, mock_list_ports):
        """Test ports with by-id path get bonus."""
        mock_port = Mock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.vid = 0x1A86
        mock_port.pid = 0x7523
        mock_port.description = ""
        mock_port.hwid = ""
        mock_port.serial_number = None
        mock_port.manufacturer = None
        mock_port.product = None

        mock_list_ports.comports.return_value = [mock_port]

        # Mock the _find_by_id_path to return a path
        with patch.object(
            PortDiscovery,
            "_find_by_id_path",
            return_value="/dev/serial/by-id/usb-test",
        ):
            discovery = PortDiscovery()
            ports = discovery.discover_ports()

            assert len(ports) == 1
            assert ports[0].by_id_path is not None
            # Score should be higher than base
            assert ports[0].score > ChipType.CH340

    def test_get_best_port_empty(self):
        """Test get_best_port with no ports."""
        with patch.object(PortDiscovery, "discover_ports", return_value=[]):
            discovery = PortDiscovery()
            assert discovery.get_best_port() is None


class TestRankPortsForKdcan:
    """Tests for port ranking function."""

    def test_rank_empty_list(self):
        """Test ranking empty list."""
        result = rank_ports_for_kdcan([])
        assert result == []

    def test_rank_single_port(self):
        """Test ranking single port."""
        port = PortInfo(
            device="/dev/ttyUSB0",
            name="Test",
            description="",
            hwid="",
            vid=None,
            pid=None,
            serial_number=None,
            manufacturer=None,
            product=None,
            chip_type=ChipType.OTHER,
            by_id_path=None,
            score=50,
        )

        result = rank_ports_for_kdcan([port])
        assert len(result) == 1
        assert result[0] == port

    def test_rank_maintains_order(self):
        """Test ranking maintains score order."""
        high_score = PortInfo(
            device="/dev/ttyUSB0",
            name="High",
            description="",
            hwid="",
            vid=None,
            pid=None,
            serial_number=None,
            manufacturer=None,
            product=None,
            chip_type=ChipType.FTDI,
            by_id_path=None,
            score=100,
        )

        low_score = PortInfo(
            device="/dev/ttyUSB1",
            name="Low",
            description="",
            hwid="",
            vid=None,
            pid=None,
            serial_number=None,
            manufacturer=None,
            product=None,
            chip_type=ChipType.OTHER,
            by_id_path=None,
            score=20,
        )

        result = rank_ports_for_kdcan([low_score, high_score])
        assert result[0].score >= result[1].score
