"""
Vehicle Profile

Manages vehicle identification and profile information.
Stores session data including detected modules, DTCs, and service history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

from e92_pulse.core.app_logging import get_logger

logger = get_logger(__name__)


class VehicleSeries(Enum):
    """BMW vehicle series identifiers."""

    E90 = "E90"  # 3-Series Sedan
    E91 = "E91"  # 3-Series Touring
    E92 = "E92"  # 3-Series Coupe
    E93 = "E93"  # 3-Series Convertible
    UNKNOWN = "Unknown"


class EngineType(Enum):
    """Engine type identifiers."""

    S65 = "S65"  # V8 (M3)
    N52 = "N52"  # Inline-6
    N54 = "N54"  # Twin-turbo I6
    N55 = "N55"  # Single-turbo I6
    UNKNOWN = "Unknown"


@dataclass
class ModuleStatus:
    """Status information for a vehicle module."""

    module_id: str
    name: str
    address: int
    responding: bool
    has_faults: bool
    fault_count: int
    last_scan: datetime | None = None
    variant: str | None = None
    software_version: str | None = None


@dataclass
class DTCInfo:
    """Diagnostic Trouble Code information."""

    code: str  # e.g., "P0171"
    description: str
    module_id: str
    module_name: str
    status: str  # "Active", "Stored", "Pending"
    freeze_frame: dict[str, Any] | None = None
    occurrence_count: int = 1
    first_seen: datetime | None = None
    last_seen: datetime | None = None


@dataclass
class ServiceRecord:
    """Record of a service function execution."""

    service_name: str
    module_id: str
    timestamp: datetime
    success: bool
    details: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class VehicleProfile:
    """
    Complete profile of the connected vehicle.

    Contains identification, module status, fault history,
    and service records for the current session.
    """

    # Identification (read from vehicle)
    vin: str | None = None
    series: VehicleSeries = VehicleSeries.UNKNOWN
    engine: EngineType = EngineType.UNKNOWN
    model_year: int | None = None
    production_date: str | None = None

    # Session data
    session_start: datetime = field(default_factory=datetime.now)
    modules: dict[str, ModuleStatus] = field(default_factory=dict)
    dtcs: list[DTCInfo] = field(default_factory=list)
    service_history: list[ServiceRecord] = field(default_factory=list)

    # Metadata
    scan_complete: bool = False
    last_scan_time: datetime | None = None

    def add_module(self, module: ModuleStatus) -> None:
        """Add or update a module in the profile."""
        self.modules[module.module_id] = module
        logger.debug(f"Module added/updated: {module.module_id} ({module.name})")

    def get_module(self, module_id: str) -> ModuleStatus | None:
        """Get a module by ID."""
        return self.modules.get(module_id)

    def add_dtc(self, dtc: DTCInfo) -> None:
        """Add a DTC to the profile."""
        # Check for existing DTC
        for existing in self.dtcs:
            if existing.code == dtc.code and existing.module_id == dtc.module_id:
                # Update existing
                existing.occurrence_count += 1
                existing.last_seen = datetime.now()
                return

        dtc.first_seen = datetime.now()
        dtc.last_seen = datetime.now()
        self.dtcs.append(dtc)
        logger.debug(f"DTC added: {dtc.code} from {dtc.module_id}")

    def clear_dtcs(self, module_id: str | None = None) -> int:
        """
        Clear DTCs from the profile.

        Args:
            module_id: Clear only DTCs from this module (None = all)

        Returns:
            Number of DTCs cleared
        """
        if module_id is None:
            count = len(self.dtcs)
            self.dtcs.clear()
        else:
            original_count = len(self.dtcs)
            self.dtcs = [d for d in self.dtcs if d.module_id != module_id]
            count = original_count - len(self.dtcs)

        logger.info(f"Cleared {count} DTC(s)")
        return count

    def add_service_record(self, record: ServiceRecord) -> None:
        """Add a service execution record."""
        self.service_history.append(record)
        logger.info(
            f"Service recorded: {record.service_name} on {record.module_id} "
            f"({'success' if record.success else 'failed'})"
        )

    def get_fault_summary(self) -> dict[str, Any]:
        """Get a summary of all faults."""
        modules_with_faults = sum(
            1 for m in self.modules.values() if m.has_faults
        )
        active_dtcs = sum(1 for d in self.dtcs if d.status == "Active")
        stored_dtcs = sum(1 for d in self.dtcs if d.status == "Stored")

        return {
            "total_modules": len(self.modules),
            "modules_responding": sum(
                1 for m in self.modules.values() if m.responding
            ),
            "modules_with_faults": modules_with_faults,
            "total_dtcs": len(self.dtcs),
            "active_dtcs": active_dtcs,
            "stored_dtcs": stored_dtcs,
        }

    def to_export_dict(self) -> dict[str, Any]:
        """
        Export profile to dictionary for serialization.

        Note: VIN is sanitized/masked for privacy.
        """
        masked_vin = None
        if self.vin:
            # Mask middle characters of VIN
            masked_vin = self.vin[:3] + "*" * 11 + self.vin[-3:]

        return {
            "vehicle": {
                "vin_masked": masked_vin,
                "series": self.series.value,
                "engine": self.engine.value,
                "model_year": self.model_year,
            },
            "session": {
                "start": self.session_start.isoformat(),
                "scan_complete": self.scan_complete,
                "last_scan": (
                    self.last_scan_time.isoformat() if self.last_scan_time else None
                ),
            },
            "modules": [
                {
                    "id": m.module_id,
                    "name": m.name,
                    "responding": m.responding,
                    "fault_count": m.fault_count,
                }
                for m in self.modules.values()
            ],
            "dtcs": [
                {
                    "code": d.code,
                    "description": d.description,
                    "module": d.module_id,
                    "status": d.status,
                    "occurrences": d.occurrence_count,
                }
                for d in self.dtcs
            ],
            "service_history": [
                {
                    "service": s.service_name,
                    "module": s.module_id,
                    "timestamp": s.timestamp.isoformat(),
                    "success": s.success,
                }
                for s in self.service_history
            ],
        }

    @classmethod
    def detect_series_from_vin(cls, vin: str) -> VehicleSeries:
        """Attempt to detect vehicle series from VIN."""
        if not vin or len(vin) < 11:
            return VehicleSeries.UNKNOWN

        # Position 4-5 in VIN typically indicates model
        model_code = vin[3:5]

        # E9x series detection
        # This is simplified - real detection would use full VIN decoding
        series_map = {
            "3C": VehicleSeries.E90,
            "3D": VehicleSeries.E91,
            "3E": VehicleSeries.E92,
            "3F": VehicleSeries.E93,
        }

        return series_map.get(model_code, VehicleSeries.UNKNOWN)

    @classmethod
    def detect_engine_from_module(cls, variant: str | None) -> EngineType:
        """Detect engine type from DME variant string."""
        if not variant:
            return EngineType.UNKNOWN

        variant_upper = variant.upper()

        if "S65" in variant_upper or "M3" in variant_upper:
            return EngineType.S65
        elif "N54" in variant_upper:
            return EngineType.N54
        elif "N55" in variant_upper:
            return EngineType.N55
        elif "N52" in variant_upper:
            return EngineType.N52

        return EngineType.UNKNOWN
