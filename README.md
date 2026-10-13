# CareLink: FHIR-style Patient Data API

A small healthcare backend that stores and serves **FHIR R4-style** clinical records
(Patient, Condition, Observation, MedicationRequest) with strict validation, search,
atomic bundle uploads, a medication-interaction check and explainable screening flags.

> **Data and safety:** all data is synthetic (`scripts/seed.py`). The interaction table and
> screening rules are small teaching samples, **not clinical decision support** and not
> medical advice. This is not a certified FHIR server and is not HIPAA-compliant.

## What it does
- **REST resources:** create / read / update / delete / search for 4 FHIR resource types, JSON served as `application/fhir+json`, `ETag` versioning, `If-Match` conflict detection (412), soft delete (410).
- **Validation:** required fields, code sets, real-date checks, patient-reference integrity, LOINC unit and plausible-range checks (e.g. systolic BP 900 is rejected). Errors come back as FHIR `OperationOutcome`, all problems at once.
- **Search:** name, birthdate, patient, code, status, `date=ge..&date=le..`, paging with `_count`/`_offset`.
- **Transaction bundles:** `POST /Bundle` resolves `urn:uuid:` references between entries and is all-or-nothing (a bad entry saves nothing).
- **`$everything`:** a patient's full record in one call.
- **`$interactions`:** pairwise check of a patient's *active* medications against an illustrative rule table, worst first.
- **`$screening`:** rule-based cardiometabolic flags (BP, HbA1c, BMI, cholesterol, heart rate) from the latest observations. Each flag names its rule, source observation and threshold. No ML, so nothing is a black box.
- **`/metadata`:** a CapabilityStatement.

## Run it (Windows PowerShell)
```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest --cov=app
$env:CARELINK_DB="carelink.db"
uvicorn app.main:app --port 8000
```
Open http://127.0.0.1:8000/docs for the interactive API.
Load demo data: `python scripts/seed.py --patients 200`. Measure it: `python scripts/benchmark.py`.

Docker: `docker compose up --build`.

## Design notes
- SQLite stores each resource as JSON plus indexed search columns. One shared connection is serialised with a lock. A load test caught a crash from unsynchronised concurrent reads; it is now covered by a regression test.
- Validation lives in one module and is shared by single-resource and bundle paths.
- Limits: single process, SQLite, no auth, no FHIR `_include`/chained search, only `valueQuantity` observations.

## Tests
`python -m pytest --cov=app` runs 51 tests: CRUD and versioning, validation, search and paging, bundles and atomicity, interactions, screening boundaries, and a concurrency regression test. CI runs them on every push.
## Results (measured on my laptop)
Windows laptop (Intel i5-10300H, 8 GB RAM), Python 3.11, single uvicorn process, SQLite file database, synthetic patients loaded with `scripts/seed.py`. Command: `python scripts/benchmark.py --requests 2000 --threads 8`. The request mix is one third each: read a patient, search observations, and run `$screening` (several queries per call). Three runs in a row:

| Metric | Result |
|---|---|
| Throughput | 145 req/s (all 3 runs) |
| Latency p50 | about 43 ms |
| Latency p95 | about 133-140 ms |
| Latency p99 | about 183-185 ms |
| Automated tests | 51 passing |

These are local, single-process numbers on synthetic data, not production figures.
'@