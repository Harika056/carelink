"""SQLite-backed FHIR resource store (JSON documents + indexed search columns)."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    type TEXT NOT NULL,
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    patient TEXT,
    code TEXT,
    name TEXT,
    birthdate TEXT,
    effective TEXT,
    status TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (type, id)
);
CREATE INDEX IF NOT EXISTS idx_patient ON resources(type, patient);
CREATE INDEX IF NOT EXISTS idx_code ON resources(type, code);
CREATE INDEX IF NOT EXISTS idx_name ON resources(type, name);
"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _first_code(res):
    for key in ("code", "medicationCodeableConcept"):
        cc = res.get(key)
        if cc and cc.get("coding"):
            return cc["coding"][0].get("code")
    return None


def _patient_ref(res):
    ref = (res.get("subject") or {}).get("reference", "")
    return ref.split("/", 1)[1] if ref.startswith("Patient/") else None


def _name(res):
    parts = []
    for n in res.get("name", []) or []:
        parts.append(n.get("family", ""))
        parts.extend(n.get("given", []) or [])
    return " ".join(p for p in parts if p).lower() or None


class Store:
    def __init__(self, path=":memory:"):
        self._lock = threading.RLock()  # one shared connection: serialise ALL access, reads included
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def _index_values(self, rtype, res):
        return dict(
            patient=res.get("id") if rtype == "Patient" else _patient_ref(res),
            code=_first_code(res),
            name=_name(res) if rtype == "Patient" else None,
            birthdate=res.get("birthDate"),
            effective=res.get("effectiveDateTime") or res.get("authoredOn") or res.get("recordedDate"),
            status=res.get("status") or (((res.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code")),
        )

    def create(self, rtype, res, rid=None):
        rid = rid or str(uuid.uuid4())
        res = dict(res, resourceType=rtype, id=rid)
        res["meta"] = {"versionId": "1", "lastUpdated": now_iso()}
        iv = self._index_values(rtype, res)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO resources(type,id,version,body,patient,code,name,birthdate,effective,status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (rtype, rid, 1, json.dumps(res), iv["patient"], iv["code"], iv["name"],
                 iv["birthdate"], iv["effective"], iv["status"]),
            )
        return res

    def read(self, rtype, rid):
        """Returns resource, None if never existed, or 'gone' if deleted."""
        with self._lock:
            row = self._db.execute(
                "SELECT body, deleted FROM resources WHERE type=? AND id=?", (rtype, rid)).fetchone()
        if row is None:
            return None
        if row["deleted"]:
            return "gone"
        return json.loads(row["body"])

    def exists(self, rtype, rid):
        r = self.read(rtype, rid)
        return isinstance(r, dict)

    def update(self, rtype, rid, res):
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT version, deleted FROM resources WHERE type=? AND id=?", (rtype, rid)).fetchone()
            if row is None:
                return None
            version = row["version"] + 1
            res = dict(res, resourceType=rtype, id=rid)
            res["meta"] = {"versionId": str(version), "lastUpdated": now_iso()}
            iv = self._index_values(rtype, res)
            self._db.execute(
                "UPDATE resources SET version=?, body=?, patient=?, code=?, name=?, birthdate=?,"
                " effective=?, status=?, deleted=0 WHERE type=? AND id=?",
                (version, json.dumps(res), iv["patient"], iv["code"], iv["name"], iv["birthdate"],
                 iv["effective"], iv["status"], rtype, rid),
            )
        return res

    def delete(self, rtype, rid):
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE resources SET deleted=1 WHERE type=? AND id=? AND deleted=0", (rtype, rid))
        return cur.rowcount == 1

    def search(self, rtype, patient=None, code=None, name=None, birthdate=None,
               status=None, date_from=None, date_to=None, count=20, offset=0):
        where, args = ["type=?", "deleted=0"], [rtype]
        if patient:
            where.append("patient=?"); args.append(patient)
        if code:
            where.append("code=?"); args.append(code)
        if name:
            where.append("name LIKE ?"); args.append(f"%{name.lower()}%")
        if birthdate:
            where.append("birthdate=?"); args.append(birthdate)
        if status:
            where.append("status=?"); args.append(status)
        if date_from:
            where.append("effective>=?"); args.append(date_from)
        if date_to:
            where.append("effective<=?"); args.append(date_to)
        clause = " AND ".join(where)
        with self._lock:
            total = self._db.execute(f"SELECT COUNT(*) FROM resources WHERE {clause}", args).fetchone()[0]
            rows = self._db.execute(
                f"SELECT body FROM resources WHERE {clause} ORDER BY effective DESC, id LIMIT ? OFFSET ?",
                args + [count, offset]).fetchall()
        return total, [json.loads(r["body"]) for r in rows]

    def all_for_patient(self, rtype, pid):
        total, res = self.search(rtype, patient=pid, count=10_000)
        return res

    def create_many(self, items):
        """Insert several resources atomically: all succeed or none do."""
        out = []
        with self._lock, self._db:
            for rtype, res, rid in items:
                rid = rid or str(uuid.uuid4())
                res = dict(res, resourceType=rtype, id=rid)
                res["meta"] = {"versionId": "1", "lastUpdated": now_iso()}
                iv = self._index_values(rtype, res)
                self._db.execute(
                    "INSERT INTO resources(type,id,version,body,patient,code,name,birthdate,effective,status)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (rtype, rid, 1, json.dumps(res), iv["patient"], iv["code"], iv["name"],
                     iv["birthdate"], iv["effective"], iv["status"]))
                out.append(res)
        return out
