"""
Application Configuration

Manages configuration loading, validation, and persistence.
Supports configuration files and runtime overrides.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConnectionConfig:
    """Connection-related configuration."""

    preferred_port: str | None = None  # CAN interface name (can0, etc.)
    timeout: float = 1.0
    retry_count: int = 3
    auto_reconnect: bool = True


@dataclass
class UIConfig:
    """UI-related configuration."""

    theme: str = "dark"
    show_raw_data: bool = False
    confirm_dtc_clear: bool = True
    confirm_service_execute: bool = True
    window_geometry: dict[str, int] = field(
        default_factory=lambda: {"x": 100, "y": 100, "width": 1200, "height": 800}
    )


@dataclass
class LoggingConfig:
    """Logging-related configuration."""

    log_level: str = "INFO"
    log_dir: str = "./logs"
    max_log_files: int = 50
    log_raw_protocol: bool = False


@dataclass
class AppConfig:
    """Main application configuration."""

    datapacks_dir: str = ""
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Last known good interface for quick reconnection
    last_known_interface: str | None = None

    def __post_init__(self) -> None:
        """Initialize default paths."""
        if not self.datapacks_dir:
            config_dir = Path(user_config_dir("e92_pulse"))
            self.datapacks_dir = str(config_dir / "datapacks")

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "datapacks_dir": self.datapacks_dir,
            "last_known_interface": self.last_known_interface,
            "connection": {
                "preferred_interface": self.connection.preferred_port,
                "timeout": self.connection.timeout,
                "retry_count": self.connection.retry_count,
                "auto_reconnect": self.connection.auto_reconnect,
            },
            "ui": {
                "theme": self.ui.theme,
                "show_raw_data": self.ui.show_raw_data,
                "confirm_dtc_clear": self.ui.confirm_dtc_clear,
                "confirm_service_execute": self.ui.confirm_service_execute,
                "window_geometry": self.ui.window_geometry,
            },
            "logging": {
                "log_level": self.logging.log_level,
                "log_dir": self.logging.log_dir,
                "max_log_files": self.logging.max_log_files,
                "log_raw_protocol": self.logging.log_raw_protocol,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Create configuration from dictionary."""
        config = cls()

        if "datapacks_dir" in data:
            config.datapacks_dir = data["datapacks_dir"]
        if "last_known_interface" in data:
            config.last_known_interface = data["last_known_interface"]

        if "connection" in data:
            conn = data["connection"]
            config.connection = ConnectionConfig(
                preferred_port=conn.get("preferred_interface"),
                timeout=conn.get("timeout", 1.0),
                retry_count=conn.get("retry_count", 3),
                auto_reconnect=conn.get("auto_reconnect", True),
            )

        if "ui" in data:
            ui = data["ui"]
            config.ui = UIConfig(
                theme=ui.get("theme", "dark"),
                show_raw_data=ui.get("show_raw_data", False),
                confirm_dtc_clear=ui.get("confirm_dtc_clear", True),
                confirm_service_execute=ui.get("confirm_service_execute", True),
                window_geometry=ui.get(
                    "window_geometry",
                    {"x": 100, "y": 100, "width": 1200, "height": 800},
                ),
            )

        if "logging" in data:
            log = data["logging"]
            config.logging = LoggingConfig(
                log_level=log.get("log_level", "INFO"),
                log_dir=log.get("log_dir", "./logs"),
                max_log_files=log.get("max_log_files", 50),
                log_raw_protocol=log.get("log_raw_protocol", False),
            )

        return config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    config_dir = Path(user_config_dir("e92_pulse"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    """
    Load configuration from file.

    Args:
        path: Path to configuration file (default: user config dir)

    Returns:
        Loaded configuration
    """
    config_path = path or get_config_path()

    if not config_path.exists():
        logger.info(f"No configuration file found at {config_path}, using defaults")
        return AppConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        config = AppConfig.from_dict(data or {})
        logger.info(f"Configuration loaded from {config_path}")
        return config

    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> bool:
    """
    Save configuration to file.

    Args:
        config: Configuration to save
        path: Path to save to (default: user config dir)

    Returns:
        True if saved successfully
    """
    config_path = path or get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config.to_dict(), f, default_flow_style=False)

        logger.info(f"Configuration saved to {config_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save configuration: {e}")
        return False
