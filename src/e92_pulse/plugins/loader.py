"""
Plugin Loader

Discovers and loads plugins and datapacks from the user's configuration directory.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

from e92_pulse.core.app_logging import get_logger
from e92_pulse.plugins.base import PluginInterface, DatapackInterface, PluginMetadata

logger = get_logger(__name__)


class PluginLoader:
    """
    Loads plugins and datapacks from the filesystem.

    Datapacks are loaded from:
    - ~/.config/e92_pulse/datapacks/

    Plugins are loaded from:
    - ~/.config/e92_pulse/plugins/
    """

    def __init__(self, base_dir: str | Path) -> None:
        """
        Initialize plugin loader.

        Args:
            base_dir: Base configuration directory
        """
        self._base_dir = Path(base_dir)
        self._datapacks_dir = self._base_dir / "datapacks"
        self._plugins_dir = self._base_dir / "plugins"

        self._loaded_datapacks: list[dict[str, Any]] = []
        self._loaded_plugins: list[PluginInterface] = []

    @property
    def datapacks_dir(self) -> Path:
        """Get datapacks directory."""
        return self._datapacks_dir

    @property
    def plugins_dir(self) -> Path:
        """Get plugins directory."""
        return self._plugins_dir

    def discover_datapacks(self) -> list[PluginMetadata]:
        """
        Discover available datapacks.

        Returns:
            List of datapack metadata
        """
        if not self._datapacks_dir.exists():
            return []

        datapacks = []

        # Look for YAML/JSON datapack files
        for file in self._datapacks_dir.glob("*.yaml"):
            meta = self._read_datapack_metadata(file)
            if meta:
                datapacks.append(meta)

        for file in self._datapacks_dir.glob("*.json"):
            meta = self._read_datapack_metadata(file)
            if meta:
                datapacks.append(meta)

        return datapacks

    def _read_datapack_metadata(self, file: Path) -> PluginMetadata | None:
        """Read metadata from a datapack file."""
        try:
            with open(file, "r", encoding="utf-8") as f:
                if file.suffix == ".yaml":
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)

            if not data:
                return None

            # Extract or create metadata
            meta_data = data.get("metadata", {})
            meta_data.setdefault("id", file.stem)
            meta_data.setdefault("name", file.stem)
            meta_data.setdefault("version", "1.0.0")
            meta_data.setdefault("description", f"Datapack from {file.name}")

            return PluginMetadata.from_dict(meta_data)

        except Exception as e:
            logger.warning(f"Failed to read datapack {file}: {e}")
            return None

    def load_datapack(self, file: Path) -> dict[str, Any] | None:
        """
        Load a datapack file.

        Args:
            file: Path to datapack file

        Returns:
            Datapack data dictionary or None
        """
        try:
            with open(file, "r", encoding="utf-8") as f:
                if file.suffix == ".yaml":
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)

            if data:
                self._loaded_datapacks.append(data)
                logger.info(f"Loaded datapack: {file.name}")
                return data

        except Exception as e:
            logger.error(f"Failed to load datapack {file}: {e}")

        return None

    def load_all_datapacks(self) -> list[dict[str, Any]]:
        """
        Load all discovered datapacks.

        Returns:
            List of loaded datapack data
        """
        if not self._datapacks_dir.exists():
            return []

        for file in self._datapacks_dir.glob("*.yaml"):
            self.load_datapack(file)

        for file in self._datapacks_dir.glob("*.json"):
            self.load_datapack(file)

        return self._loaded_datapacks

    def discover_plugins(self) -> list[PluginMetadata]:
        """
        Discover available plugins.

        Returns:
            List of plugin metadata
        """
        if not self._plugins_dir.exists():
            return []

        plugins = []

        # Look for Python plugin directories with manifest.yaml
        for plugin_dir in self._plugins_dir.iterdir():
            if plugin_dir.is_dir():
                manifest = plugin_dir / "manifest.yaml"
                if manifest.exists():
                    meta = self._read_plugin_manifest(manifest)
                    if meta:
                        plugins.append(meta)

        return plugins

    def _read_plugin_manifest(self, manifest: Path) -> PluginMetadata | None:
        """Read metadata from a plugin manifest."""
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data:
                return PluginMetadata.from_dict(data)

        except Exception as e:
            logger.warning(f"Failed to read plugin manifest {manifest}: {e}")

        return None

    def load_plugin(self, plugin_dir: Path, app_context: Any) -> PluginInterface | None:
        """
        Load a plugin from directory.

        Args:
            plugin_dir: Plugin directory
            app_context: Application context to pass to plugin

        Returns:
            Loaded plugin instance or None
        """
        try:
            # Find the main module
            main_file = plugin_dir / "plugin.py"
            if not main_file.exists():
                main_file = plugin_dir / "__init__.py"

            if not main_file.exists():
                logger.warning(f"No plugin entry point in {plugin_dir}")
                return None

            # Load the module
            spec = importlib.util.spec_from_file_location(
                plugin_dir.name, main_file
            )
            if not spec or not spec.loader:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find and instantiate the plugin class
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, PluginInterface)
                    and attr is not PluginInterface
                ):
                    plugin = attr()
                    if plugin.initialize(app_context):
                        self._loaded_plugins.append(plugin)
                        logger.info(f"Loaded plugin: {plugin.metadata.name}")
                        return plugin
                    else:
                        logger.warning(
                            f"Plugin {attr_name} failed to initialize"
                        )

        except Exception as e:
            logger.error(f"Failed to load plugin from {plugin_dir}: {e}")

        return None

    def get_loaded_datapacks(self) -> list[dict[str, Any]]:
        """Get all loaded datapacks."""
        return self._loaded_datapacks.copy()

    def get_loaded_plugins(self) -> list[PluginInterface]:
        """Get all loaded plugins."""
        return self._loaded_plugins.copy()

    def unload_all_plugins(self) -> None:
        """Unload all plugins."""
        for plugin in self._loaded_plugins:
            try:
                plugin.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down plugin: {e}")

        self._loaded_plugins.clear()

    def ensure_directories(self) -> None:
        """Create plugin directories if they don't exist."""
        self._datapacks_dir.mkdir(parents=True, exist_ok=True)
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
