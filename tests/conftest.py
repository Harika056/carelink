import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    return TestClient(create_app(":memory:"))


def patient(family="Rao", given="Asha", gender="female", birth="1980-04-12"):
    return {"resourceType": "Patient", "name": [{"family": family, "given": [given]}],
            "gender": gender, "birthDate": birth}


def obs(pid, code, value, unit, dt="2024-05-01T09:00:00Z", status="final"):
    return {"resourceType": "Observation", "status": status,
            "code": {"coding": [{"system": "http://loinc.org", "code": code}]},
            "subject": {"reference": f"Patient/{pid}"}, "effectiveDateTime": dt,
            "valueQuantity": {"value": value, "unit": unit}}


def med(pid, name, code="x", status="active"):
    return {"resourceType": "MedicationRequest", "status": status, "intent": "order",
            "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                                      "code": code, "display": name}]},
            "subject": {"reference": f"Patient/{pid}"}}


def cond(pid, code="38341003", display="Hypertension", status="active"):
    return {"resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": status}]},
            "code": {"coding": [{"system": "http://snomed.info/sct", "code": code, "display": display}]},
            "subject": {"reference": f"Patient/{pid}"}}


def make(client, res):
    r = client.post(f"/{res['resourceType']}", json=res)
    assert r.status_code == 201, r.text
    return r.json()
