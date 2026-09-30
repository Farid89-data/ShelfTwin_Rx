# ShelfTwin Rx - Python Reference MVP

Package-level storage-integrity evidence generator for authorised pharmaceutical QA review.

## Status

Reference implementation for technical evaluation and prototyping. Not production-validated, not a medical device claim, and not an autonomous medicinal-product release or redispensing system. Human pharmacist/QA disposition remains mandatory.

Version 0.1 | Tested 27 July 2026 | Python 3.13.5

## What it does

Receives package identity and product-specific storage rules, ingests timestamped sensor readings, detects temperature/humidity excursions, identifies unacceptable data gaps, latches tamper evidence, and generates a deterministic evidence report with a SHA-256 fingerprint for authorised QA review.

It never outputs "approved for reuse." Its highest positive status is `READY_FOR_QA_REVIEW`. Any temperature excursion, tamper event, or insufficient evidence is surfaced as a review flag.

| Prototype does | Prototype does not |
|---|---|
| Bind readings to package identity | Confirm drug potency |
| Apply configurable storage thresholds | Authorize reuse/redispensing |
| Detect temperature/RH excursion periods | Replace stability data or SmPC |
| Detect data gaps | Make clinical decisions |
| Latch tamper-open observations | Replace QA/SOP review |
| Generate evidence SHA-256 fingerprint | Claim regulatory validation |

## Architecture

| Layer | Component | Responsibility |
|---|---|---|
| Edge | NFC / sensor logger | Collect timestamped environment and tamper observations |
| API | FastAPI service (`app.py`) | Validate package registration and incoming reading payloads |
| Domain engine | `EvidenceEngine` (`shelftwin_core.py`) | Excursion segmentation, data-gap analysis, tamper flagging, deterministic status |
| Integrity | SHA-256 canonical evidence hash | Detect changes to the exact evidence payload |
| QA interface | Evidence JSON / future dashboard | Present evidence for authorised human disposition |

## Files

- `shelftwin_core.py` — core evidence engine (`EvidenceEngine`, `StorageProfile`, `PackageIdentity`, `SensorReading`, `Excursion`, `EvidenceReport`)
- `app.py` — FastAPI service exposing package/reading/evidence endpoints
- `demo.py` — runnable demo reproducing the temperature-excursion scenario
- `tests/test_core.py` — domain-engine unit tests
- `tests/test_api.py` — API integration tests
- `pytest.ini` — pytest config (`pythonpath = .`)
- `requirements.txt` — pinned dependencies

## REST API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service health check |
| POST | `/packages` | Register package identity and storage profile |
| POST | `/packages/{package_id}/readings` | Ingest one or more sensor readings |
| GET | `/packages/{package_id}/evidence` | Generate current package evidence report |
| DELETE | `/_test/reset` | Test-only endpoint; remove outside test environments |

## Evidence decision logic

| Condition | System status |
|---|---|
| No readings | `INSUFFICIENT_EVIDENCE` |
| Unacceptable data gap | `INSUFFICIENT_EVIDENCE` |
| Tamper-open event | `HOLD_FOR_QA_REVIEW` unless already insufficient |
| Excursion above configured allowable duration | `HOLD_FOR_QA_REVIEW` unless already insufficient |
| No configured critical flags | `READY_FOR_QA_REVIEW` — human QA review still required |

Deterministic: identical package identity, storage profile, and readings always produce the same SHA-256 evidence fingerprint and status.

## Run it

```bash
pip install -r requirements.txt
python demo.py
pytest -q
coverage run -m pytest -q
coverage report -m
```

Last verified run: 11/11 tests passed, 94% line coverage, 0.25s.

## Production hardening required before pilot

| Area | Current prototype | Required production direction |
|---|---|---|
| Persistence | In-memory engine dictionary | PostgreSQL + immutable event store/object storage |
| Authentication | None | OIDC/OAuth2, MFA, RBAC, service identities |
| Audit trail | Evidence hash only | Append-only signed audit events, reviewer actions, reason codes |
| Device trust | Payload assumed trusted | Per-device keys, signed logger payloads, anti-replay counters |
| Time integrity | Client/device timestamp | Secure clock strategy and clock-drift detection |
| Rules | Single configurable profile | Versioned product/SOP rules with approval workflow |
| Calibration | Not represented | Calibration certificate linkage and sensor uncertainty metadata |
| Electronic signature | Not implemented | QA e-signature aligned to validated QMS requirements |
| Validation | Unit/integration testing | URS, risk assessment, traceability matrix, IQ/OQ/PQ as applicable |
| Availability | Single-process prototype | Containerized deployment, backup, monitoring, recovery objectives |

Source: `ShelfTwin_Rx_Python_MVP_Verification_Report.pdf` (Input/ShelfTwin_Rx/).
