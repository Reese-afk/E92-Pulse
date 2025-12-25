"""
Structured Logging System

Provides JSONL structured logging for audit trails and debugging.
All diagnostic operations are logged with timestamps and context.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}
_log_dir: Path | None = None
_session_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")


class JSONLFormatter(logging.Formatter):
    """Formatter that outputs logs as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session": _session_id,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra"):
            log_data["extra"] = record.extra

        # Add standard extra fields if present
        for key in ["category", "operation", "details", "module_id", "dtc_code"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Colored console formatter for human-readable output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        return f"{color}[{timestamp}] {record.levelname:8}{self.RESET} {record.name}: {record.getMessage()}"


def setup_logging(log_dir: Path | None = None, debug: bool = False) -> None:
    """
    Initialize the logging system.

    Args:
        log_dir: Directory for log files (default: ./logs)
        debug: Enable debug-level logging
    """
    global _log_dir, _session_id

    _log_dir = log_dir or Path("./logs")
    _log_dir.mkdir(parents=True, exist_ok=True)

    # Generate session ID
    _session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Configure root logger
    root_logger = logging.getLogger("e92_pulse")
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler (JSONL structured)
    log_file = _log_dir / f"session_{_session_id}.jsonl"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONLFormatter())
    root_logger.addHandler(file_handler)

    # Log startup
    root_logger.info(
        f"Logging initialized: session={_session_id}, log_file={log_file}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    if name not in _loggers:
        # Ensure name is under e92_pulse namespace
        if not name.startswith("e92_pulse"):
            name = f"e92_pulse.{name}"

        logger = logging.getLogger(name)
        _loggers[name] = logger

    return _loggers[name]


def get_session_id() -> str:
    """Get the current session ID."""
    return _session_id


def get_log_dir() -> Path:
    """Get the log directory."""
    return _log_dir or Path("./logs")


def log_audit_event(
    event_type: str,
    description: str,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Log an audit event for tracking diagnostic operations.

    Args:
        event_type: Type of event (e.g., "dtc_clear", "service_execute")
        description: Human-readable description
        details: Additional details
    """
    logger = get_logger("audit")
    logger.info(
        f"AUDIT: {event_type} - {description}",
        extra={
            "audit_event": event_type,
            "audit_description": description,
            "audit_details": details or {},
        },
    )


def log_diagnostic_action(
    action: str,
    module_id: str | None = None,
    success: bool = True,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Log a diagnostic action with structured data.

    Args:
        action: Action performed (e.g., "read_dtc", "clear_dtc")
        module_id: Target module identifier
        success: Whether the action succeeded
        error: Error message if failed
        details: Additional details
    """
    logger = get_logger("diagnostic")
    log_data = {
        "action": action,
        "module_id": module_id,
        "success": success,
        "error": error,
        "details": details or {},
    }

    if success:
        logger.info(f"Diagnostic action: {action}", extra=log_data)
    else:
        logger.error(f"Diagnostic action failed: {action} - {error}", extra=log_data)
