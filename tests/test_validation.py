import pytest

from .conftest import cond, make, med, obs, patient


def issues(r):
    return [i["diagnostics"] for i in r.json()["issue"]]


def test_patient_needs_name(client):
    r = client.post("/Patient", json={"resourceType": "Patient", "gender": "male"})
    assert r.status_code == 422 and any("name" in d for d in issues(r))


def test_patient_bad_gender(client):
    assert client.post("/Patient", json=patient(gender="robot")).status_code == 422


def test_patient_future_birthdate(client):
    r = client.post("/Patient", json=patient(birth="2999-01-01"))
    assert r.status_code == 422 and any("future" in d for d in issues(r))


def test_patient_impossible_date(client):
    assert client.post("/Patient", json=patient(birth="2020-02-31")).status_code == 422


def test_observation_requires_existing_patient(client):
    r = client.post("/Observation", json=obs("ghost", "8480-6", 120, "mm[Hg]"))
    assert r.status_code == 422 and any("does not exist" in d for d in issues(r))


def test_observation_implausible_value(client):
    p = make(client, patient())
    r = client.post("/Observation", json=obs(p["id"], "8480-6", 900, "mm[Hg]"))
    assert r.status_code == 422 and any("plausible" in d for d in issues(r))


def test_observation_wrong_unit(client):
    p = make(client, patient())
    r = client.post("/Observation", json=obs(p["id"], "4548-4", 6.0, "mg/dL"))
    assert r.status_code == 422 and any("unit" in d for d in issues(r))


def test_observation_non_numeric_value(client):
    p = make(client, patient())
    bad = obs(p["id"], "8480-6", "high", "mm[Hg]")
    assert client.post("/Observation", json=bad).status_code == 422


def test_observation_bool_value_rejected(client):
    p = make(client, patient())
    assert client.post("/Observation", json=obs(p["id"], "8480-6", True, "mm[Hg]")).status_code == 422


def test_observation_future_date(client):
    p = make(client, patient())
    bad = obs(p["id"], "8480-6", 120, "mm[Hg]", dt="2999-01-01T00:00:00Z")
    assert client.post("/Observation", json=bad).status_code == 422


def test_observation_bad_status(client):
    p = make(client, patient())
    assert client.post("/Observation", json=obs(p["id"], "8480-6", 120, "mm[Hg]", status="maybe")).status_code == 422


def test_unknown_loinc_code_accepted_without_range_check(client):
    p = make(client, patient())
    assert client.post("/Observation", json=obs(p["id"], "99999-9", 123456, "u")).status_code == 201


def test_condition_bad_status(client):
    p = make(client, patient())
    assert client.post("/Condition", json=cond(p["id"], status="maybe")).status_code == 422


def test_medreq_needs_display_and_intent(client):
    p = make(client, patient())
    m = med(p["id"], "X")
    m["medicationCodeableConcept"]["coding"][0].pop("display")
    m["intent"] = "wish"
    r = client.post("/MedicationRequest", json=m)
    assert r.status_code == 422 and len(issues(r)) >= 2


def test_multiple_errors_reported_together(client):
    r = client.post("/Observation", json={"resourceType": "Observation"})
    assert r.status_code == 422 and len(issues(r)) >= 4
