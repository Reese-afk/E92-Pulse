"""
Plugin Base Interfaces

Defines the interfaces for E92 Pulse plugins and datapacks.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginMetadata:
    """Metadata about a plugin or datapack."""

    id: str
    name: str
    version: str
    description: str
    author: str = ""
    license: str = ""
    requires_version: str = ">=0.1.0"
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "requires_version": self.requires_version,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginMetadata":
        """Create from dictionary."""
        return cls(
            id=data.get("id", "unknown"),
            name=data.get("name", "Unknown Plugin"),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            license=data.get("license", ""),
            requires_version=data.get("requires_version", ">=0.1.0"),
            dependencies=data.get("dependencies", []),
        )


class PluginInterface(ABC):
    """
    Base interface for E92 Pulse plugins.

    Plugins can extend functionality by providing additional
    services, protocols, or UI elements.
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Plugin metadata."""
        pass

    @abstractmethod
    def initialize(self, app_context: Any) -> bool:
        """
        Initialize the plugin.

        Args:
            app_context: Application context with references to core services

        Returns:
            True if initialization successful
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the plugin and release resources."""
        pass

    def on_connect(self) -> None:
        """Called when diagnostic connection is established."""
        pass

    def on_disconnect(self) -> None:
        """Called when diagnostic connection is closed."""
        pass


class DatapackInterface(ABC):
    """
    Interface for datapacks.

    Datapacks provide additional data definitions such as:
    - Module definitions
    - DTC descriptions
    - Live data definitions
    - Service routines
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Datapack metadata."""
        pass

    @abstractmethod
    def get_modules(self) -> list[dict[str, Any]]:
        """
        Get module definitions.

        Returns:
            List of module definition dictionaries
        """
        pass

    def get_dtc_descriptions(self) -> dict[str, str]:
        """
        Get DTC code descriptions.

        Returns:
            Dictionary mapping DTC codes to descriptions
        """
        return {}

    def get_live_data_definitions(self) -> list[dict[str, Any]]:
        """
        Get live data/PID definitions.

        Returns:
            List of live data definition dictionaries
        """
        return []

    def get_service_definitions(self) -> list[dict[str, Any]]:
        """
        Get service routine definitions.

        Returns:
            List of service definition dictionaries
        """
        return []
