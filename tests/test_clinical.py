from app import interactions, screening

from .conftest import cond, make, med, obs, patient


def test_interaction_detected_both_orders(client):
    p = make(client, patient())
    make(client, med(p["id"], "Warfarin 5mg"))
    make(client, med(p["id"], "Aspirin 81mg"))
    r = client.get(f"/Patient/{p['id']}/$interactions").json()
    assert r["count"] == 1 and r["findings"][0]["severity"] == "major"
    assert "disclaimer" in r


def test_inactive_medication_ignored(client):
    p = make(client, patient())
    make(client, med(p["id"], "Warfarin"))
    make(client, med(p["id"], "Aspirin", status="stopped"))
    assert client.get(f"/Patient/{p['id']}/$interactions").json()["count"] == 0


def test_worst_first_ordering():
    meds = [dict(med("p", n), id=str(i)) for i, n in
            enumerate(["lisinopril", "ibuprofen", "sildenafil", "nitroglycerin"])]
    out = interactions.check(meds)
    assert out["findings"][0]["severity"] == "contraindicated"
    assert [f["severity"] for f in out["findings"]][-1] == "moderate"


def test_no_self_interaction():
    m = [dict(med("p", "warfarin"), id="1")]
    assert interactions.check(m)["count"] == 0


def test_screening_no_data_is_none(client):
    p = make(client, patient())
    r = client.get(f"/Patient/{p['id']}/$screening").json()
    assert r["attentionLevel"] == "none" and r["flagCount"] == 0


def test_screening_flags_with_evidence(client):
    p = make(client, patient())
    pid = p["id"]
    o1 = make(client, obs(pid, "8480-6", 152, "mm[Hg]"))
    make(client, obs(pid, "4548-4", 7.1, "%"))
    make(client, obs(pid, "39156-5", 32.0, "kg/m2"))
    r = client.get(f"/Patient/{pid}/$screening").json()
    assert r["attentionLevel"] == "high" and r["flagCount"] == 3
    bp = next(f for f in r["flags"] if f["rule"] == "BP-1")
    assert bp["observation"] == o1["id"] and bp["value"] == 152


def test_screening_uses_latest_observation_only(client):
    p = make(client, patient())
    make(client, obs(p["id"], "8480-6", 170, "mm[Hg]", dt="2023-01-01T00:00:00Z"))
    make(client, obs(p["id"], "8480-6", 118, "mm[Hg]", dt="2024-06-01T00:00:00Z"))
    assert client.get(f"/Patient/{p['id']}/$screening").json()["flagCount"] == 0


def test_screening_ignores_entered_in_error(client):
    p = make(client, patient())
    make(client, obs(p["id"], "8480-6", 170, "mm[Hg]", status="entered-in-error"))
    assert client.get(f"/Patient/{p['id']}/$screening").json()["flagCount"] == 0


def test_screening_boundaries():
    mk = lambda code, v: {code: {"id": "o", "valueQuantity": {"value": v}}}
    assert screening.evaluate(mk("8480-6", 139.9))["flagCount"] == 0
    assert screening.evaluate(mk("8480-6", 140))["flagCount"] == 1
    assert screening.evaluate(mk("4548-4", 5.6))["flagCount"] == 0
    assert screening.evaluate(mk("4548-4", 5.7))["flags"][0]["rule"] == "GLU-2"
    assert screening.evaluate(mk("4548-4", 6.5))["flags"][0]["rule"] == "GLU-1"
    assert screening.evaluate(mk("8867-4", 49))["flagCount"] == 1
    assert screening.evaluate(mk("8867-4", 100))["flagCount"] == 0


def test_everything_and_metadata(client):
    p = make(client, patient())
    make(client, cond(p["id"]))
    assert client.get(f"/Patient/{p['id']}/$everything").json()["total"] == 2
    md = client.get("/metadata").json()
    assert md["resourceType"] == "CapabilityStatement" and len(md["rest"][0]["resource"]) == 4


def test_everything_404_for_unknown_patient(client):
    assert client.get("/Patient/zzz/$everything").status_code == 404
