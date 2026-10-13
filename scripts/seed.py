"""Load SYNTHETIC patients (no real people) into a running CareLink server.

    python scripts/seed.py --base-url http://127.0.0.1:8000 --patients 200
"""
import argparse
import json
import random
import urllib.request

LOINC = "http://loinc.org"
MEDS = ["Lisinopril 10mg", "Metformin 500mg", "Atorvastatin 20mg", "Aspirin 81mg", "Warfarin 5mg",
        "Ibuprofen 400mg", "Spironolactone 25mg", "Sertraline 50mg", "Tramadol 50mg"]
FAMILY = ["Rao", "Khan", "Iyer", "Singh", "Das", "Reddy", "Patel", "Nair", "Shah", "Menon"]
GIVEN = ["Asha", "Imran", "Priya", "Arjun", "Meera", "Kiran", "Neha", "Ravi", "Sana", "Vikram"]


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/fhir+json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def obs(ref, code, value, unit, day):
    return {"fullUrl": f"urn:uuid:{random.getrandbits(64):x}", "resource": {
        "resourceType": "Observation", "status": "final",
        "code": {"coding": [{"system": LOINC, "code": code}]},
        "subject": {"reference": ref}, "effectiveDateTime": f"2024-{day}T09:00:00Z",
        "valueQuantity": {"value": value, "unit": unit}}}


def patient_bundle(rng, i):
    ref = f"urn:uuid:patient-{i}"
    entries = [{"fullUrl": ref, "resource": {
        "resourceType": "Patient",
        "name": [{"family": rng.choice(FAMILY), "given": [rng.choice(GIVEN)]}],
        "gender": rng.choice(["male", "female"]),
        "birthDate": f"{rng.randint(1945, 2004)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"}}]
    for month in ("02-10", "06-10"):
        entries += [
            obs(ref, "8480-6", rng.randint(100, 175), "mm[Hg]", month),
            obs(ref, "8462-4", rng.randint(60, 105), "mm[Hg]", month),
            obs(ref, "4548-4", round(rng.uniform(4.8, 8.5), 1), "%", month),
            obs(ref, "39156-5", round(rng.uniform(19, 38), 1), "kg/m2", month)]
    for m in rng.sample(MEDS, rng.randint(1, 3)):
        entries.append({"fullUrl": f"urn:uuid:m{rng.getrandbits(64):x}", "resource": {
            "resourceType": "MedicationRequest", "status": "active", "intent": "order",
            "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                                      "code": "0", "display": m}]},
            "subject": {"reference": ref}}})
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [dict(e, request={"method": "POST"}) for e in entries]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--patients", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    for i in range(a.patients):
        post(a.base_url, "/Bundle", patient_bundle(rng, i))
    print(f"Loaded {a.patients} synthetic patients (seed={a.seed}).")


if __name__ == "__main__":
    main()
