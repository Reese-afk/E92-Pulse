"""
Tests for logging and audit functionality.
"""

import pytest
import json
from pathlib import Path

from e92_pulse.core.app_logging import (
    setup_logging,
    get_logger,
    get_session_id,
    get_log_dir,
    log_audit_event,
    log_diagnostic_action,
)


class TestLogging:
    """Tests for logging system."""

    def test_setup_logging(self, temp_dir: Path):
        """Test logging setup."""
        log_dir = temp_dir / "logs"
        setup_logging(log_dir=log_dir, debug=True)

        assert log_dir.exists()

    def test_get_logger(self, temp_dir: Path):
        """Test getting a logger."""
        setup_logging(log_dir=temp_dir, debug=False)

        logger = get_logger("test")
        assert logger is not None
        assert "e92_pulse" in logger.name

    def test_get_session_id(self, temp_dir: Path):
        """Test session ID generation."""
        setup_logging(log_dir=temp_dir, debug=False)

        session_id = get_session_id()
        assert session_id is not None
        assert len(session_id) > 0
        # Should be in YYYYMMDD_HHMMSS format
        assert "_" in session_id

    def test_log_audit_event(self, temp_dir: Path):
        """Test audit event logging."""
        setup_logging(log_dir=temp_dir, debug=True)

        log_audit_event(
            "test_event",
            "Test description",
            {"key": "value"},
        )

        # Check log file was created
        log_files = list(temp_dir.glob("*.jsonl"))
        assert len(log_files) > 0

    def test_log_diagnostic_action(self, temp_dir: Path):
        """Test diagnostic action logging."""
        setup_logging(log_dir=temp_dir, debug=True)

        log_diagnostic_action(
            "test_action",
            module_id="DME",
            success=True,
            details={"param": "value"},
        )

        # Verify log was written
        log_files = list(temp_dir.glob("*.jsonl"))
        assert len(log_files) > 0

    def test_log_format_jsonl(self, temp_dir: Path):
        """Test log entries are valid JSONL."""
        setup_logging(log_dir=temp_dir, debug=True)

        logger = get_logger("test_jsonl")
        logger.info("Test message")

        log_files = list(temp_dir.glob("*.jsonl"))
        assert len(log_files) > 0

        with open(log_files[0], "r") as f:
            for line in f:
                if line.strip():
                    # Each line should be valid JSON
                    data = json.loads(line)
                    assert "timestamp" in data
                    assert "level" in data
                    assert "message" in data

    def test_failed_action_logged(self, temp_dir: Path):
        """Test failed diagnostic actions are logged."""
        setup_logging(log_dir=temp_dir, debug=True)

        log_diagnostic_action(
            "failed_action",
            module_id="TEST",
            success=False,
            error="Test error message",
        )

        log_files = list(temp_dir.glob("*.jsonl"))
        assert len(log_files) > 0

        # Check error was logged
        with open(log_files[0], "r") as f:
            content = f.read()
            assert "failed_action" in content


class TestLogDir:
    """Tests for log directory management."""

    def test_get_log_dir_default(self):
        """Test default log directory."""
        log_dir = get_log_dir()
        # Should return Path object
        assert isinstance(log_dir, Path)

    def test_get_log_dir_after_setup(self, temp_dir: Path):
        """Test log directory after setup."""
        log_dir = temp_dir / "custom_logs"
        setup_logging(log_dir=log_dir, debug=False)

        result = get_log_dir()
        assert result == log_dir
