from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from shelftwin_core import EvidenceEngine, PackageIdentity, SensorReading, StorageProfile

app = FastAPI(
    title="ShelfTwin Rx Python MVP",
    version="0.1.0",
    description=(
        "Reference API for package-level storage-integrity evidence. "
        "This prototype supports QA review; it does not authorize medicinal-product reuse."
    ),
)

_lock = RLock()
_engines: dict[str, EvidenceEngine] = {}


class StorageProfileIn(BaseModel):
    min_temp_c: float
    max_temp_c: float
    expected_sample_interval_min: int = 15
    max_data_gap_min: int = 30
    max_single_excursion_min: int = 0
    humidity_min_pct: Optional[float] = None
    humidity_max_pct: Optional[float] = None


class PackageIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    package_id: str = Field(min_length=3, max_length=80)
    product_name: str = Field(min_length=1, max_length=120)
    strength: str = Field(min_length=1, max_length=80)
    dosage_form: str = Field(min_length=1, max_length=80)
    batch_number: str = Field(min_length=1, max_length=80)
    serial_number: str = Field(min_length=1, max_length=120)
    expiry_date: str = Field(min_length=7, max_length=20)
    storage_profile: StorageProfileIn


class ReadingIn(BaseModel):
    timestamp: datetime
    temperature_c: float
    humidity_pct: Optional[float] = None
    light_lux: Optional[float] = None
    tamper_open: bool = False
    battery_mv: Optional[int] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ShelfTwin Rx Python MVP"}


@app.post("/packages", status_code=201)
def register_package(payload: PackageIn) -> dict:
    with _lock:
        if payload.package_id in _engines:
            raise HTTPException(status_code=409, detail="package_id already exists")
        identity = PackageIdentity(
            package_id=payload.package_id,
            product_name=payload.product_name,
            strength=payload.strength,
            dosage_form=payload.dosage_form,
            batch_number=payload.batch_number,
            serial_number=payload.serial_number,
            expiry_date=payload.expiry_date,
        )
        profile = StorageProfile(**payload.storage_profile.model_dump())
        _engines[payload.package_id] = EvidenceEngine(identity, profile)
    return {"package_id": payload.package_id, "registered": True}


@app.post("/packages/{package_id}/readings", status_code=202)
def add_readings(package_id: str, readings: list[ReadingIn]) -> dict:
    with _lock:
        engine = _engines.get(package_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="package not found")
        try:
            engine.add_readings(
                SensorReading(**reading.model_dump()) for reading in readings
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"package_id": package_id, "accepted_readings": len(readings)}


@app.get("/packages/{package_id}/evidence")
def get_evidence(package_id: str) -> dict:
    with _lock:
        engine = _engines.get(package_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="package not found")
        report = engine.evaluate()
    return report.to_dict()


@app.delete("/_test/reset")
def reset_for_tests() -> dict:
    """Test-only helper. Remove in any non-test deployment."""
    with _lock:
        _engines.clear()
    return {"reset": True}
