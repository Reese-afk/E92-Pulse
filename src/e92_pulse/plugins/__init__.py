"""
E92 Pulse Plugin System

Provides interfaces and loading for optional datapacks and plugins.
"""

from e92_pulse.plugins.base import (
    PluginInterface,
    DatapackInterface,
    PluginMetadata,
)
from e92_pulse.plugins.loader import PluginLoader

__all__ = [
    "PluginInterface",
    "DatapackInterface",
    "PluginMetadata",
    "PluginLoader",
]
