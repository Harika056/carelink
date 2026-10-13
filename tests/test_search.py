from .conftest import make, obs, patient


def test_search_patient_by_name_case_insensitive(client):
    make(client, patient("Rao", "Asha"))
    make(client, patient("Khan", "Imran"))
    r = client.get("/Patient", params={"name": "RAO"}).json()
    assert r["total"] == 1 and r["entry"][0]["resource"]["name"][0]["family"] == "Rao"


def test_search_patient_by_birthdate(client):
    make(client, patient(birth="1990-01-01"))
    make(client, patient(birth="1991-01-01"))
    assert client.get("/Patient", params={"birthdate": "1990-01-01"}).json()["total"] == 1


def test_observation_filters(client):
    p = make(client, patient())
    q = make(client, patient("Khan"))
    make(client, obs(p["id"], "8480-6", 120, "mm[Hg]"))
    make(client, obs(p["id"], "4548-4", 6.0, "%"))
    make(client, obs(q["id"], "8480-6", 110, "mm[Hg]"))
    assert client.get("/Observation", params={"patient": p["id"]}).json()["total"] == 2
    assert client.get("/Observation", params={"patient": p["id"], "code": "8480-6"}).json()["total"] == 1
    assert client.get("/Observation", params={"code": "8480-6"}).json()["total"] == 2


def test_date_range(client):
    p = make(client, patient())
    for d in ("2023-01-10T08:00:00Z", "2024-03-10T08:00:00Z", "2024-12-31T23:00:00Z"):
        make(client, obs(p["id"], "8480-6", 120, "mm[Hg]", dt=d))
    r = client.get("/Observation", params=[("date", "ge2024-01-01"), ("date", "le2024-12-31")]).json()
    assert r["total"] == 2


def test_bad_date_prefix_400(client):
    assert client.get("/Observation", params={"date": "2024-01-01"}).status_code == 400


def test_paging(client):
    p = make(client, patient())
    for i in range(5):
        make(client, obs(p["id"], "8480-6", 100 + i, "mm[Hg]", dt=f"2024-01-0{i+1}T08:00:00Z"))
    page1 = client.get("/Observation", params={"_count": 2, "_offset": 0}).json()
    page2 = client.get("/Observation", params={"_count": 2, "_offset": 2}).json()
    assert page1["total"] == 5 and len(page1["entry"]) == 2 and len(page2["entry"]) == 2
    ids1 = {e["resource"]["id"] for e in page1["entry"]}
    assert ids1.isdisjoint({e["resource"]["id"] for e in page2["entry"]})


def test_count_limit_enforced(client):
    assert client.get("/Patient", params={"_count": 1000}).status_code == 422


def test_sql_injection_in_name_is_inert(client):
    make(client, patient())
    r = client.get("/Patient", params={"name": "x' OR '1'='1"})
    assert r.status_code == 200 and r.json()["total"] == 0
