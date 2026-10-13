from .conftest import patient


def entry(res, url):
    return {"fullUrl": url, "resource": res, "request": {"method": "POST"}}


def test_transaction_resolves_urn_references(client):
    b = {"resourceType": "Bundle", "type": "transaction", "entry": [
        entry(patient(), "urn:uuid:p1"),
        entry({"resourceType": "Observation", "status": "final",
               "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
               "subject": {"reference": "urn:uuid:p1"}, "effectiveDateTime": "2024-01-01T00:00:00Z",
               "valueQuantity": {"value": 150, "unit": "mm[Hg]"}}, "urn:uuid:o1")]}
    r = client.post("/Bundle", json=b)
    assert r.status_code == 200
    locs = [e["response"]["location"] for e in r.json()["entry"]]
    pid = locs[0].split("/")[1]
    assert client.get(f"/Patient/{pid}/$everything").json()["total"] == 2


def test_transaction_is_atomic(client):
    b = {"resourceType": "Bundle", "type": "transaction", "entry": [
        entry(patient(), "urn:uuid:p1"),
        entry({"resourceType": "Observation", "status": "final"}, "urn:uuid:o1")]}
    r = client.post("/Bundle", json=b)
    assert r.status_code == 400
    assert "Bundle.entry[1]" in r.json()["issue"][0]["expression"][0]
    assert client.get("/Patient").json()["total"] == 0  # nothing from the bundle was saved


def test_bundle_wrong_type(client):
    assert client.post("/Bundle", json={"resourceType": "Bundle", "type": "collection"}).status_code == 400


def test_bundle_size_limit(client):
    b = {"resourceType": "Bundle", "type": "transaction",
         "entry": [entry(patient(), f"urn:uuid:{i}") for i in range(101)]}
    assert client.post("/Bundle", json=b).status_code == 400
