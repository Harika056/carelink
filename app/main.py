"""CareLink: a small FHIR R4-style REST service (Patient, Condition, Observation, MedicationRequest)."""
import json
import os
import uuid

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from . import interactions, screening
from .store import Store
from .validation import SUPPORTED, issue, outcome, validate

FHIR_JSON = "application/fhir+json"
MAX_BUNDLE = 100


class FhirResponse(JSONResponse):
    media_type = FHIR_JSON


class FhirError(Exception):
    def __init__(self, status, issues):
        self.status, self.issues = status, issues


def _bundle(btype, entries, total=None):
    b = {"resourceType": "Bundle", "type": btype, "entry": entries}
    if total is not None:
        b["total"] = total
    return b


def _etag(res):
    return f'W/"{res["meta"]["versionId"]}"'


def create_app(db_path=None):
    db_path = db_path or os.environ.get("CARELINK_DB", ":memory:")
    store = Store(db_path)
    app = FastAPI(title="CareLink FHIR Service", version="1.0.0",
                  default_response_class=FhirResponse)
    app.state.store = store

    @app.exception_handler(FhirError)
    async def _fhir_error(_, exc):
        return FhirResponse(outcome(exc.issues), status_code=exc.status)

    def check_type(rtype):
        if rtype not in SUPPORTED:
            raise FhirError(404, [issue("not-supported", f"Unknown resource type '{rtype}'")])

    async def body_of(request):
        try:
            return json.loads(await request.body())
        except (ValueError, UnicodeDecodeError):
            raise FhirError(400, [issue("structure", "Body is not valid JSON")])

    def must_exist(rtype, rid):
        res = store.read(rtype, rid)
        if res is None:
            raise FhirError(404, [issue("not-found", f"{rtype}/{rid} not found")])
        if res == "gone":
            raise FhirError(410, [issue("deleted", f"{rtype}/{rid} was deleted")])
        return res

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metadata")
    def metadata():
        return {
            "resourceType": "CapabilityStatement", "status": "active", "kind": "instance",
            "fhirVersion": "4.0.1", "format": ["json"],
            "software": {"name": "CareLink", "version": "1.0.0"},
            "rest": [{"mode": "server", "resource": [
                {"type": t, "interaction": [{"code": c} for c in
                                            ("read", "create", "update", "delete", "search-type")]}
                for t in SUPPORTED]}],
        }

    @app.post("/Bundle")
    async def transaction(request: Request):
        bundle = await body_of(request)
        if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" \
                or bundle.get("type") != "transaction":
            raise FhirError(400, [issue("structure", "Expected a Bundle of type 'transaction'")])
        entries = bundle.get("entry") or []
        if not entries or len(entries) > MAX_BUNDLE:
            raise FhirError(400, [issue("structure", f"Bundle needs 1-{MAX_BUNDLE} entries")])
        planned, urls, patient_ids = [], {}, set()
        for i, e in enumerate(entries):
            res = e.get("resource") or {}
            rtype = res.get("resourceType")
            rid = str(uuid.uuid4())
            if e.get("fullUrl"):
                urls[e["fullUrl"]] = f"{rtype}/{rid}"
            if rtype == "Patient":
                patient_ids.add(rid)
            planned.append((rtype, res, rid))
        problems = []
        for i, (rtype, res, rid) in enumerate(planned):
            if isinstance(res.get("subject"), dict):
                ref = res["subject"].get("reference")
                if ref in urls:
                    res["subject"]["reference"] = urls[ref]
            for it in validate(res, store, known_ids=patient_ids):
                it = dict(it)
                it["expression"] = [f"Bundle.entry[{i}]." + x for x in it.get("expression", ["resource"])]
                problems.append(it)
        if problems:
            raise FhirError(400, problems)
        created = store.create_many(planned)
        out = [{"response": {"status": "201 Created",
                             "location": f"{r['resourceType']}/{r['id']}", "etag": _etag(r)}}
               for r in created]
        return FhirResponse(_bundle("transaction-response", out), status_code=200)

    @app.post("/{rtype}")
    async def create(rtype: str, request: Request):
        check_type(rtype)
        res = await body_of(request)
        if isinstance(res, dict) and res.get("resourceType") != rtype:
            raise FhirError(400, [issue("invalid", f"resourceType must be '{rtype}'")])
        issues = validate(res, store)
        if issues:
            raise FhirError(422, issues)
        created = store.create(rtype, res)
        return FhirResponse(created, status_code=201, headers={
            "Location": f"/{rtype}/{created['id']}", "ETag": _etag(created)})

    @app.get("/{rtype}/{rid}")
    def read(rtype: str, rid: str):
        check_type(rtype)
        res = must_exist(rtype, rid)
        return FhirResponse(res, headers={"ETag": _etag(res)})

    @app.put("/{rtype}/{rid}")
    async def update(rtype: str, rid: str, request: Request):
        check_type(rtype)
        current = must_exist(rtype, rid)
        res = await body_of(request)
        if isinstance(res, dict) and res.get("id") not in (None, rid):
            raise FhirError(400, [issue("invalid", "Body id does not match URL id")])
        if isinstance(res, dict) and res.get("resourceType") != rtype:
            raise FhirError(400, [issue("invalid", f"resourceType must be '{rtype}'")])
        match = request.headers.get("If-Match")
        if match and match != _etag(current):
            raise FhirError(412, [issue("conflict", f"If-Match {match} does not match current {_etag(current)}")])
        issues = validate(res, store)
        if issues:
            raise FhirError(422, issues)
        updated = store.update(rtype, rid, res)
        return FhirResponse(updated, headers={"ETag": _etag(updated)})

    @app.delete("/{rtype}/{rid}")
    def delete(rtype: str, rid: str):
        check_type(rtype)
        must_exist(rtype, rid)
        store.delete(rtype, rid)
        return Response(status_code=204)

    @app.get("/{rtype}")
    def search(rtype: str, name: str | None = None, birthdate: str | None = None,
               patient: str | None = None, code: str | None = None, status: str | None = None,
               date: list[str] = Query(default=[]),
               _count: int = Query(20, ge=1, le=100), _offset: int = Query(0, ge=0)):
        check_type(rtype)
        d_from = d_to = None
        for d in date:
            if d.startswith("ge"):
                d_from = d[2:]
            elif d.startswith("le"):
                d_to = d[2:] + ("T99" if len(d) == 12 else "")
            else:
                raise FhirError(400, [issue("invalid", "date must start with 'ge' or 'le'", "date")])
        total, res = store.search(rtype, patient=patient, code=code, name=name, birthdate=birthdate,
                                  status=status, date_from=d_from, date_to=d_to,
                                  count=_count, offset=_offset)
        return FhirResponse(_bundle("searchset", [{"fullUrl": f"{rtype}/{r['id']}", "resource": r}
                                                 for r in res], total))

    def patient_or_404(pid):
        return must_exist("Patient", pid)

    @app.get("/Patient/{pid}/$everything")
    def everything(pid: str):
        p = patient_or_404(pid)
        entries = [{"resource": p}]
        for t in ("Condition", "Observation", "MedicationRequest"):
            entries += [{"resource": r} for r in store.all_for_patient(t, pid)]
        return FhirResponse(_bundle("searchset", entries, len(entries)))

    @app.get("/Patient/{pid}/$interactions")
    def patient_interactions(pid: str):
        patient_or_404(pid)
        return interactions.check(store.all_for_patient("MedicationRequest", pid))

    @app.get("/Patient/{pid}/$screening")
    def patient_screening(pid: str):
        patient_or_404(pid)
        latest = {}
        for code in screening.CODES:
            _, found = store.search("Observation", patient=pid, code=code, count=1)
            if found and found[0].get("status") not in ("entered-in-error", "cancelled"):
                latest[code] = found[0]
        return screening.evaluate(latest)

    return app


app = create_app()
