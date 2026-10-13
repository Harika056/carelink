from .conftest import cond, make, med, obs, patient


def test_create_read_roundtrip(client):
    p = make(client, patient())
    r = client.get(f"/Patient/{p['id']}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/fhir+json")
    assert r.json()["name"][0]["family"] == "Rao"
    assert r.headers["etag"] == 'W/"1"'


def test_create_sets_location_and_meta(client):
    r = client.post("/Patient", json=patient())
    assert r.headers["location"] == f"/Patient/{r.json()['id']}"
    assert r.json()["meta"]["versionId"] == "1"


def test_unknown_resource_type_404(client):
    r = client.get("/Spaceship/1")
    assert r.status_code == 404
    assert r.json()["resourceType"] == "OperationOutcome"


def test_missing_resource_404(client):
    assert client.get("/Patient/nope").status_code == 404


def test_update_bumps_version(client):
    p = make(client, patient())
    body = patient(family="Rao-Iyer")
    r = client.put(f"/Patient/{p['id']}", json=body)
    assert r.status_code == 200
    assert r.json()["meta"]["versionId"] == "2"
    assert client.get(f"/Patient/{p['id']}").json()["name"][0]["family"] == "Rao-Iyer"


def test_if_match_conflict_412(client):
    p = make(client, patient())
    client.put(f"/Patient/{p['id']}", json=patient(family="B"))
    r = client.put(f"/Patient/{p['id']}", json=patient(family="C"), headers={"If-Match": 'W/"1"'})
    assert r.status_code == 412


def test_if_match_ok(client):
    p = make(client, patient())
    r = client.put(f"/Patient/{p['id']}", json=patient(family="B"), headers={"If-Match": 'W/"1"'})
    assert r.status_code == 200


def test_put_id_mismatch_400(client):
    p = make(client, patient())
    body = dict(patient(), id="other")
    assert client.put(f"/Patient/{p['id']}", json=body).status_code == 400


def test_delete_then_410_and_hidden_from_search(client):
    p = make(client, patient())
    assert client.delete(f"/Patient/{p['id']}").status_code == 204
    assert client.get(f"/Patient/{p['id']}").status_code == 410
    assert client.get("/Patient").json()["total"] == 0


def test_invalid_json_400(client):
    r = client.post("/Patient", content=b"{oops", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["issue"][0]["code"] == "structure"


def test_wrong_resource_type_in_body_400(client):
    r = client.post("/Patient", json=cond("x"))
    assert r.status_code == 400


def test_all_resource_types_create(client):
    p = make(client, patient())
    make(client, cond(p["id"]))
    make(client, obs(p["id"], "8480-6", 120, "mm[Hg]"))
    make(client, med(p["id"], "Lisinopril"))


def test_concurrent_reads_and_writes_do_not_error(tmp_path):
    """Regression: a shared SQLite connection used from many threads raised InterfaceError."""
    from concurrent.futures import ThreadPoolExecutor

    from app.main import create_app
    from fastapi.testclient import TestClient
    c = TestClient(create_app(str(tmp_path / "t.db")))
    pid = make(c, patient())["id"]

    def work(i):
        if i % 4 == 0:
            return c.post("/Patient", json=patient(family=f"F{i}")).status_code
        return c.get(f"/Patient/{pid}" if i % 2 else f"/Patient?_count=5").status_code

    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(work, range(300)))
    assert set(codes) <= {200, 201}
