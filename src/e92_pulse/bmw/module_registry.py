"""
Module Registry

Manages ECU module definitions for BMW E92 M3.
Supports built-in starter definitions and user datapacks.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModuleDefinition:
    """Definition of a BMW ECU module."""

    module_id: str  # Unique identifier (e.g., "DME", "DSC")
    name: str  # Human-readable name
    description: str  # Description of function
    address: int  # Diagnostic address
    can_id_tx: int | None = None  # CAN TX ID (if applicable)
    can_id_rx: int | None = None  # CAN RX ID (if applicable)
    category: str = "general"  # Category (powertrain, chassis, body, etc.)
    dtc_prefix: str = ""  # DTC code prefix (e.g., "P" for powertrain)
    supports_extended_session: bool = True
    priority: int = 0  # Scan priority (higher = scan first)
    variants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "description": self.description,
            "address": self.address,
            "can_id_tx": self.can_id_tx,
            "can_id_rx": self.can_id_rx,
            "category": self.category,
            "dtc_prefix": self.dtc_prefix,
            "supports_extended_session": self.supports_extended_session,
            "priority": self.priority,
            "variants": self.variants,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleDefinition":
        """Create from dictionary."""
        return cls(
            module_id=data["module_id"],
            name=data["name"],
            description=data.get("description", ""),
            address=data["address"],
            can_id_tx=data.get("can_id_tx"),
            can_id_rx=data.get("can_id_rx"),
            category=data.get("category", "general"),
            dtc_prefix=data.get("dtc_prefix", ""),
            supports_extended_session=data.get("supports_extended_session", True),
            priority=data.get("priority", 0),
            variants=data.get("variants", []),
        )


class ModuleRegistry:
    """
    Registry of BMW ECU modules.

    Provides built-in starter definitions for E92 M3 and supports
    loading additional definitions from user datapacks.
    """

    def __init__(self, datapacks_dir: str | Path | None = None) -> None:
        """
        Initialize module registry.

        Args:
            datapacks_dir: Directory for user datapacks
        """
        self._modules: dict[str, ModuleDefinition] = {}
        self._datapacks_dir = Path(datapacks_dir) if datapacks_dir else None

        # Load built-in definitions
        self._load_builtin_definitions()

        # Load user datapacks
        if self._datapacks_dir:
            self._load_datapacks()

    def _load_builtin_definitions(self) -> None:
        """Load built-in module definitions for E92 M3."""
        # These are starter definitions based on public information
        # Real addresses may vary by variant
        builtin = [
            ModuleDefinition(
                module_id="DME",
                name="Digital Motor Electronics",
                description="Engine control unit (S65 V8)",
                address=0x12,
                category="powertrain",
                dtc_prefix="P",
                priority=100,
                variants=["S65B40", "MSS60"],
            ),
            ModuleDefinition(
                module_id="EGS",
                name="Electronic Transmission Control",
                description="Automatic transmission control",
                address=0x18,
                category="powertrain",
                dtc_prefix="P",
                priority=90,
            ),
            ModuleDefinition(
                module_id="DSC",
                name="Dynamic Stability Control",
                description="ABS, traction control, stability",
                address=0x56,
                category="chassis",
                dtc_prefix="C",
                priority=85,
            ),
            ModuleDefinition(
                module_id="EPS",
                name="Electric Power Steering",
                description="Power steering control",
                address=0x32,
                category="chassis",
                dtc_prefix="C",
                priority=70,
            ),
            ModuleDefinition(
                module_id="KOMBI",
                name="Instrument Cluster",
                description="Dashboard and gauges",
                address=0x60,
                category="body",
                dtc_prefix="B",
                priority=60,
            ),
            ModuleDefinition(
                module_id="CAS",
                name="Car Access System",
                description="Central locking, immobilizer",
                address=0x40,
                category="body",
                dtc_prefix="B",
                priority=75,
            ),
            ModuleDefinition(
                module_id="FRM",
                name="Footwell Module",
                description="Light control, central body electronics",
                address=0x16,
                category="body",
                dtc_prefix="B",
                priority=50,
            ),
            ModuleDefinition(
                module_id="CCC",
                name="Car Communication Computer",
                description="iDrive, navigation, multimedia",
                address=0x63,
                category="body",
                dtc_prefix="B",
                priority=40,
            ),
            ModuleDefinition(
                module_id="IHKA",
                name="Climate Control",
                description="HVAC control",
                address=0x3B,
                category="body",
                dtc_prefix="B",
                priority=30,
            ),
            ModuleDefinition(
                module_id="PDC",
                name="Park Distance Control",
                description="Parking sensors",
                address=0x62,
                category="body",
                dtc_prefix="B",
                priority=20,
            ),
            ModuleDefinition(
                module_id="SZL",
                name="Steering Column Switch Cluster",
                description="Turn signals, wipers, cruise control",
                address=0x61,
                category="body",
                dtc_prefix="B",
                priority=25,
            ),
            ModuleDefinition(
                module_id="ACSM",
                name="Advanced Crash Safety Module",
                description="Airbag control",
                address=0x64,
                category="chassis",
                dtc_prefix="B",
                priority=80,
            ),
            ModuleDefinition(
                module_id="EDC",
                name="Electronic Damper Control",
                description="Adaptive suspension (M)",
                address=0x59,
                category="chassis",
                dtc_prefix="C",
                priority=65,
            ),
            ModuleDefinition(
                module_id="SINE",
                name="Siren and Tilt Alarm Module",
                description="Security system",
                address=0x73,
                category="body",
                dtc_prefix="B",
                priority=10,
            ),
        ]

        for module in builtin:
            self._modules[module.module_id] = module

        logger.info(f"Loaded {len(builtin)} built-in module definitions")

    def _load_datapacks(self) -> None:
        """Load module definitions from user datapacks."""
        if not self._datapacks_dir or not self._datapacks_dir.exists():
            return

        for file in self._datapacks_dir.glob("*.yaml"):
            self._load_datapack_file(file)

        for file in self._datapacks_dir.glob("*.json"):
            self._load_datapack_file(file)

    def _load_datapack_file(self, file: Path) -> None:
        """Load a single datapack file."""
        try:
            with open(file, "r", encoding="utf-8") as f:
                if file.suffix == ".yaml":
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)

            if not data or "modules" not in data:
                return

            count = 0
            for module_data in data["modules"]:
                try:
                    module = ModuleDefinition.from_dict(module_data)
                    self._modules[module.module_id] = module
                    count += 1
                except Exception as e:
                    logger.warning(f"Invalid module in {file}: {e}")

            logger.info(f"Loaded {count} modules from datapack: {file.name}")

        except Exception as e:
            logger.error(f"Failed to load datapack {file}: {e}")

    def get_module(self, module_id: str) -> ModuleDefinition | None:
        """Get a module definition by ID."""
        return self._modules.get(module_id)

    def get_module_by_address(self, address: int) -> ModuleDefinition | None:
        """Get a module definition by address."""
        for module in self._modules.values():
            if module.address == address:
                return module
        return None

    def get_all_modules(self) -> list[ModuleDefinition]:
        """Get all module definitions sorted by priority."""
        return sorted(
            self._modules.values(), key=lambda m: m.priority, reverse=True
        )

    def get_modules_by_category(self, category: str) -> list[ModuleDefinition]:
        """Get modules in a specific category."""
        return [
            m
            for m in self._modules.values()
            if m.category.lower() == category.lower()
        ]

    def get_categories(self) -> list[str]:
        """Get list of all categories."""
        return sorted(set(m.category for m in self._modules.values()))

    def add_module(self, module: ModuleDefinition) -> None:
        """Add or update a module definition."""
        self._modules[module.module_id] = module

    def remove_module(self, module_id: str) -> bool:
        """Remove a module definition."""
        if module_id in self._modules:
            del self._modules[module_id]
            return True
        return False

    def export_to_file(self, file: Path) -> bool:
        """Export all definitions to a file."""
        try:
            data = {
                "version": "1.0",
                "modules": [m.to_dict() for m in self._modules.values()],
            }

            with open(file, "w", encoding="utf-8") as f:
                if file.suffix == ".yaml":
                    yaml.dump(data, f, default_flow_style=False)
                else:
                    json.dump(data, f, indent=2)

            return True

        except Exception as e:
            logger.error(f"Failed to export modules: {e}")
            return False
