from datetime import datetime, timedelta, timezone

import pytest

from shelftwin_core import (
    EvidenceEngine,
    EvidenceStatus,
    PackageIdentity,
    SensorReading,
    StorageProfile,
)


def package():
    return PackageIdentity(
        package_id="PKG-001",
        product_name="Example Medicine",
        strength="80 mg",
        dosage_form="tablet",
        batch_number="B26",
        serial_number="SER-1",
        expiry_date="2028-12-31",
    )


def profile(**kwargs):
    base = dict(
        min_temp_c=15.0,
        max_temp_c=25.0,
        expected_sample_interval_min=15,
        max_data_gap_min=30,
        max_single_excursion_min=0,
    )
    base.update(kwargs)
    return StorageProfile(**base)


def readings(values, minutes=15, tamper_at=None):
    start = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    result = []
    for i, value in enumerate(values):
        result.append(
            SensorReading(
                timestamp=start + timedelta(minutes=minutes * i),
                temperature_c=value,
                humidity_pct=50.0,
                tamper_open=(tamper_at == i),
            )
        )
    return result


def test_clean_history_is_ready_for_human_qa_review():
    engine = EvidenceEngine(package(), profile())
    engine.add_readings(readings([20.0, 21.0, 22.0, 23.0]))
    report = engine.evaluate()
    assert report.status == EvidenceStatus.READY_FOR_QA_REVIEW
    assert report.data_gap_count == 0
    assert report.tamper_detected is False
    assert report.excursions == ()


def test_high_temperature_excursion_causes_hold():
    engine = EvidenceEngine(package(), profile())
    engine.add_readings(readings([21.0, 26.5, 27.0, 23.0]))
    report = engine.evaluate()
    assert report.status == EvidenceStatus.HOLD_FOR_QA_REVIEW
    assert len(report.excursions) == 1
    assert report.excursions[0].kind == "TEMP_HIGH"
    assert report.excursions[0].duration_min == 30.0


def test_low_temperature_excursion_causes_hold():
    engine = EvidenceEngine(package(), profile())
    engine.add_readings(readings([20.0, 14.0, 13.5, 20.0]))
    report = engine.evaluate()
    assert report.status == EvidenceStatus.HOLD_FOR_QA_REVIEW
    assert report.excursions[0].kind == "TEMP_LOW"


def test_tamper_event_causes_hold():
    engine = EvidenceEngine(package(), profile())
    engine.add_readings(readings([20.0, 21.0, 22.0], tamper_at=1))
    report = engine.evaluate()
    assert report.status == EvidenceStatus.HOLD_FOR_QA_REVIEW
    assert report.tamper_detected is True


def test_large_data_gap_is_insufficient_evidence():
    engine = EvidenceEngine(package(), profile(max_data_gap_min=30))
    start = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    engine.add_reading(SensorReading(start, 20.0))
    engine.add_reading(SensorReading(start + timedelta(minutes=75), 20.0))
    report = engine.evaluate()
    assert report.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert report.data_gap_count == 1
    assert report.largest_gap_min == 75.0


def test_no_readings_is_insufficient_evidence():
    report = EvidenceEngine(package(), profile()).evaluate()
    assert report.status == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert report.reading_count == 0


def test_non_chronological_reading_rejected():
    engine = EvidenceEngine(package(), profile())
    start = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    engine.add_reading(SensorReading(start, 20.0))
    with pytest.raises(ValueError, match="strictly chronological"):
        engine.add_reading(SensorReading(start, 21.0))


def test_evidence_hash_is_deterministic_for_same_input():
    data = readings([20.0, 21.0, 22.0])
    a = EvidenceEngine(package(), profile())
    b = EvidenceEngine(package(), profile())
    a.add_readings(data)
    b.add_readings(data)
    assert a.evaluate().evidence_sha256 == b.evaluate().evidence_sha256
