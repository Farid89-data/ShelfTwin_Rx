from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Iterable, Optional


class EvidenceStatus(str, Enum):
    READY_FOR_QA_REVIEW = "READY_FOR_QA_REVIEW"
    HOLD_FOR_QA_REVIEW = "HOLD_FOR_QA_REVIEW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class StorageProfile:
    """Product-specific review profile. Values are examples and must be configured from approved product data/SOPs."""
    min_temp_c: float
    max_temp_c: float
    expected_sample_interval_min: int = 15
    max_data_gap_min: int = 30
    max_single_excursion_min: int = 0
    humidity_min_pct: Optional[float] = None
    humidity_max_pct: Optional[float] = None


@dataclass(frozen=True)
class PackageIdentity:
    package_id: str
    product_name: str
    strength: str
    dosage_form: str
    batch_number: str
    serial_number: str
    expiry_date: str


@dataclass(frozen=True)
class SensorReading:
    timestamp: datetime
    temperature_c: float
    humidity_pct: Optional[float] = None
    light_lux: Optional[float] = None
    tamper_open: bool = False
    battery_mv: Optional[int] = None

    def normalized(self) -> dict:
        ts = self.timestamp.astimezone(timezone.utc).isoformat()
        return {
            "timestamp": ts,
            "temperature_c": round(self.temperature_c, 3),
            "humidity_pct": None if self.humidity_pct is None else round(self.humidity_pct, 3),
            "light_lux": None if self.light_lux is None else round(self.light_lux, 3),
            "tamper_open": self.tamper_open,
            "battery_mv": self.battery_mv,
        }


@dataclass(frozen=True)
class Excursion:
    kind: str
    start: datetime
    end: datetime
    duration_min: float
    extreme_value: float


@dataclass(frozen=True)
class EvidenceReport:
    package: PackageIdentity
    status: EvidenceStatus
    reasons: tuple[str, ...]
    reading_count: int
    first_reading: Optional[datetime]
    last_reading: Optional[datetime]
    min_temp_c: Optional[float]
    max_temp_c: Optional[float]
    min_humidity_pct: Optional[float]
    max_humidity_pct: Optional[float]
    data_gap_count: int
    largest_gap_min: float
    tamper_detected: bool
    excursions: tuple[Excursion, ...]
    evidence_sha256: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        for key in ("first_reading", "last_reading"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        for excursion in data["excursions"]:
            excursion["start"] = excursion["start"].isoformat()
            excursion["end"] = excursion["end"].isoformat()
        return data


class EvidenceEngine:
    """Deterministic package-level evidence evaluator.
    It never authorizes reuse or release. It only identifies evidence quality and
    flags that support a human pharmacist/QA disposition decision.
    """

    def __init__(self, package: PackageIdentity, profile: StorageProfile):
        self.package = package
        self.profile = profile
        self._readings: list[SensorReading] = []

    def add_reading(self, reading: SensorReading) -> None:
        if reading.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self._readings and reading.timestamp <= self._readings[-1].timestamp:
            raise ValueError("readings must be strictly chronological")
        if not (-100.0 <= reading.temperature_c <= 150.0):
            raise ValueError("temperature outside plausible sensor range")
        if reading.humidity_pct is not None and not (0.0 <= reading.humidity_pct <= 100.0):
            raise ValueError("humidity must be between 0 and 100 percent")
        self._readings.append(reading)

    def add_readings(self, readings: Iterable[SensorReading]) -> None:
        for reading in readings:
            self.add_reading(reading)

    def evaluate(self) -> EvidenceReport:
        readings = self._readings
        if not readings:
            return self._empty_report()

        gaps: list[float] = []
        for previous, current in zip(readings, readings[1:]):
            gap = (current.timestamp - previous.timestamp).total_seconds() / 60.0
            if gap > self.profile.max_data_gap_min:
                gaps.append(gap)

        temp_excursions = self._detect_temperature_excursions(readings)
        humidity_excursions = self._detect_humidity_excursions(readings)
        all_excursions = tuple(temp_excursions + humidity_excursions)

        tamper = any(r.tamper_open for r in readings)

        reasons: list[str] = []
        status = EvidenceStatus.READY_FOR_QA_REVIEW

        if len(readings) < 2:
            status = EvidenceStatus.INSUFFICIENT_EVIDENCE
            reasons.append("Fewer than two sensor readings are available.")

        if gaps:
            status = EvidenceStatus.INSUFFICIENT_EVIDENCE
            reasons.append(
                f"{len(gaps)} data gap(s) exceeded the configured maximum of "
                f"{self.profile.max_data_gap_min} minutes."
            )

        if tamper:
            if status is not EvidenceStatus.INSUFFICIENT_EVIDENCE:
                status = EvidenceStatus.HOLD_FOR_QA_REVIEW
            reasons.append("Tamper-open event detected.")

        critical_excursions = [
            e for e in all_excursions if e.duration_min > self.profile.max_single_excursion_min
        ]
        if critical_excursions:
            if status is not EvidenceStatus.INSUFFICIENT_EVIDENCE:
                status = EvidenceStatus.HOLD_FOR_QA_REVIEW
            reasons.append(
                f"{len(critical_excursions)} excursion(s) exceeded the configured allowable duration "
                f"of {self.profile.max_single_excursion_min} minutes."
            )

        if not reasons:
            reasons.append(
                "No configured critical excursion, tamper event, or unacceptable data gap was detected. "
                "Human QA review is still required."
            )

        humidities = [r.humidity_pct for r in readings if r.humidity_pct is not None]

        return EvidenceReport(
            package=self.package,
            status=status,
            reasons=tuple(reasons),
            reading_count=len(readings),
            first_reading=readings[0].timestamp,
            last_reading=readings[-1].timestamp,
            min_temp_c=min(r.temperature_c for r in readings),
            max_temp_c=max(r.temperature_c for r in readings),
            min_humidity_pct=min(humidities) if humidities else None,
            max_humidity_pct=max(humidities) if humidities else None,
            data_gap_count=len(gaps),
            largest_gap_min=max(gaps) if gaps else 0.0,
            tamper_detected=tamper,
            excursions=all_excursions,
            evidence_sha256=self._evidence_hash(readings),
        )

    def _empty_report(self) -> EvidenceReport:
        return EvidenceReport(
            package=self.package,
            status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
            reasons=("No sensor readings are available.",),
            reading_count=0,
            first_reading=None,
            last_reading=None,
            min_temp_c=None,
            max_temp_c=None,
            min_humidity_pct=None,
            max_humidity_pct=None,
            data_gap_count=0,
            largest_gap_min=0.0,
            tamper_detected=False,
            excursions=(),
            evidence_sha256=self._evidence_hash([]),
        )

    def _detect_temperature_excursions(self, readings: list[SensorReading]) -> list[Excursion]:
        def classify(value: float) -> Optional[str]:
            if value < self.profile.min_temp_c:
                return "TEMP_LOW"
            if value > self.profile.max_temp_c:
                return "TEMP_HIGH"
            return None

        return self._segment_excursions(
            readings=readings,
            classifier=lambda r: classify(r.temperature_c),
            value_getter=lambda r: r.temperature_c,
        )

    def _detect_humidity_excursions(self, readings: list[SensorReading]) -> list[Excursion]:
        if self.profile.humidity_min_pct is None and self.profile.humidity_max_pct is None:
            return []

        def classify(reading: SensorReading) -> Optional[str]:
            value = reading.humidity_pct
            if value is None:
                return None
            if self.profile.humidity_min_pct is not None and value < self.profile.humidity_min_pct:
                return "RH_LOW"
            if self.profile.humidity_max_pct is not None and value > self.profile.humidity_max_pct:
                return "RH_HIGH"
            return None

        return self._segment_excursions(
            readings=readings,
            classifier=classify,
            value_getter=lambda r: r.humidity_pct if r.humidity_pct is not None else 0.0,
        )

    @staticmethod
    def _segment_excursions(readings, classifier, value_getter) -> list[Excursion]:
        excursions: list[Excursion] = []
        start_idx: Optional[int] = None
        active_kind: Optional[str] = None
        values: list[float] = []

        for idx, reading in enumerate(readings):
            kind = classifier(reading)
            if kind != active_kind:
                if active_kind is not None and start_idx is not None:
                    end_idx = idx
                    excursions.append(
                        EvidenceEngine._build_excursion(
                            active_kind, readings, start_idx, end_idx, values
                        )
                    )
                active_kind = kind
                start_idx = idx if kind is not None else None
                values = [value_getter(reading)] if kind is not None else []
            elif kind is not None:
                values.append(value_getter(reading))

        if active_kind is not None and start_idx is not None:
            # Conservative end estimate: one configured sample period is not known here;
            # therefore the excursion ends at the final observed timestamp.
            end_idx = len(readings) - 1
            excursions.append(
                EvidenceEngine._build_excursion(active_kind, readings, start_idx, end_idx, values)
            )

        return excursions

    @staticmethod
    def _build_excursion(kind, readings, start_idx, end_idx, values) -> Excursion:
        start = readings[start_idx].timestamp
        end = readings[end_idx].timestamp
        duration = max(0.0, (end - start).total_seconds() / 60.0)
        extreme = min(values) if kind.endswith("LOW") else max(values)
        return Excursion(kind=kind, start=start, end=end, duration_min=duration, extreme_value=extreme)

    def _evidence_hash(self, readings: Iterable[SensorReading]) -> str:
        payload = {
            "package": asdict(self.package),
            "profile": asdict(self.profile),
            "readings": [r.normalized() for r in readings],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
