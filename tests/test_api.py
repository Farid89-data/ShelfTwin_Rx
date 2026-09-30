from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def setup_function():
    client.delete("/_test/reset")


def package_payload():
    return {
        "package_id": "API-PKG-1",
        "product_name": "Example High-Value Medicine",
        "strength": "80 mg",
        "dosage_form": "tablet",
        "batch_number": "B26-A",
        "serial_number": "SER-API-1",
        "expiry_date": "2028-12-31",
        "storage_profile": {
            "min_temp_c": 15.0,
            "max_temp_c": 25.0,
            "expected_sample_interval_min": 15,
            "max_data_gap_min": 30,
            "max_single_excursion_min": 0,
        },
    }


def test_api_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_register_ingest_and_evidence_round_trip():
    response = client.post("/packages", json=package_payload())
    assert response.status_code == 201
    readings = [
        {"timestamp": "2026-07-27T08:00:00Z", "temperature_c": 21.0},
        {"timestamp": "2026-07-27T08:15:00Z", "temperature_c": 26.0},
        {"timestamp": "2026-07-27T08:30:00Z", "temperature_c": 27.0},
        {"timestamp": "2026-07-27T08:45:00Z", "temperature_c": 22.0},
    ]
    response = client.post("/packages/API-PKG-1/readings", json=readings)
    assert response.status_code == 202
    response = client.get("/packages/API-PKG-1/evidence")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HOLD_FOR_QA_REVIEW"
    assert body["reading_count"] == 4
    assert body["tamper_detected"] is False
    assert len(body["excursions"]) == 1


def test_duplicate_package_is_rejected():
    assert client.post("/packages", json=package_payload()).status_code == 201
    response = client.post("/packages", json=package_payload())
    assert response.status_code == 409
