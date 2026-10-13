"""Structural + clinical-plausibility validation. Returns FHIR OperationOutcome issues."""
import re
from datetime import date, datetime

SUPPORTED = ("Patient", "Condition", "Observation", "MedicationRequest")
GENDERS = {"male", "female", "other", "unknown"}
OBS_STATUS = {"registered", "preliminary", "final", "amended", "corrected", "cancelled",
              "entered-in-error", "unknown"}
MED_STATUS = {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped",
              "draft", "unknown"}
MED_INTENT = {"proposal", "plan", "order", "original-order", "reflex-order", "filler-order",
              "instance-order", "option"}
CLINICAL_STATUS = {"active", "recurrence", "relapse", "inactive", "remission", "resolved"}

LOINC = "http://loinc.org"
# LOINC code -> (label, unit, plausible min, plausible max)
PLAUSIBLE = {
    "8480-6": ("Systolic blood pressure", "mm[Hg]", 40, 300),
    "8462-4": ("Diastolic blood pressure", "mm[Hg]", 20, 200),
    "4548-4": ("Hemoglobin A1c", "%", 3, 20),
    "39156-5": ("Body mass index", "kg/m2", 8, 100),
    "2339-0": ("Glucose", "mg/dL", 20, 800),
    "8867-4": ("Heart rate", "/min", 20, 250),
    "2093-3": ("Total cholesterol", "mg/dL", 50, 700),
}
_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def issue(code, diagnostics, expression=None, severity="error"):
    out = {"severity": severity, "code": code, "diagnostics": diagnostics}
    if expression:
        out["expression"] = [expression]
    return out


def outcome(issues):
    return {"resourceType": "OperationOutcome", "issue": issues}


def _parse_dt(v):
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _check_coding(cc, path, issues, required=True):
    codings = (cc or {}).get("coding") or []
    if not codings or not codings[0].get("code"):
        if required:
            issues.append(issue("required", f"{path}.coding[0].code is required", path))
        return None
    if not codings[0].get("system"):
        issues.append(issue("required", f"{path}.coding[0].system is required", path))
    return codings[0]


def _check_subject(res, store, issues, known_ids=()):
    ref = (res.get("subject") or {}).get("reference")
    if not ref or not ref.startswith("Patient/"):
        issues.append(issue("required", "subject.reference must be 'Patient/<id>'", "subject"))
        return
    pid = ref.split("/", 1)[1]
    if pid not in known_ids and not store.exists("Patient", pid):
        issues.append(issue("not-found", f"Referenced Patient/{pid} does not exist", "subject"))


def validate(res, store, known_ids=()):
    issues = []
    if not isinstance(res, dict):
        return [issue("structure", "Body must be a JSON object")]
    rtype = res.get("resourceType")
    if rtype not in SUPPORTED:
        return [issue("not-supported", f"resourceType '{rtype}' is not supported; use one of {SUPPORTED}")]
    {"Patient": _patient, "Condition": _condition, "Observation": _observation,
     "MedicationRequest": _medreq}[rtype](res, store, issues, known_ids)
    return issues


def _patient(res, store, issues, known_ids):
    names = res.get("name") or []
    if not names or not (names[0].get("family") or names[0].get("given")):
        issues.append(issue("required", "Patient.name needs a family or given name", "name"))
    if res.get("gender") not in GENDERS:
        issues.append(issue("code-invalid", f"gender must be one of {sorted(GENDERS)}", "gender"))
    bd = res.get("birthDate")
    if bd:
        if not _DATE.match(bd):
            issues.append(issue("value", "birthDate must be YYYY[-MM[-DD]]", "birthDate"))
        else:
            try:
                d = date.fromisoformat(bd) if len(bd) == 10 else date(int(bd[:4]), int(bd[5:7] or 1), 1)
                if d > date.today():
                    issues.append(issue("value", "birthDate cannot be in the future", "birthDate"))
            except ValueError:
                issues.append(issue("value", "birthDate is not a real date", "birthDate"))


def _condition(res, store, issues, known_ids):
    _check_coding(res.get("code"), "code", issues)
    status = (((res.get("clinicalStatus") or {}).get("coding")) or [{}])[0].get("code")
    if status not in CLINICAL_STATUS:
        issues.append(issue("code-invalid", f"clinicalStatus must be one of {sorted(CLINICAL_STATUS)}",
                            "clinicalStatus"))
    _check_subject(res, store, issues, known_ids)


def _observation(res, store, issues, known_ids):
    if res.get("status") not in OBS_STATUS:
        issues.append(issue("code-invalid", f"status must be one of {sorted(OBS_STATUS)}", "status"))
    coding = _check_coding(res.get("code"), "code", issues)
    _check_subject(res, store, issues, known_ids)
    eff = res.get("effectiveDateTime")
    if not eff or _parse_dt(eff) is None:
        issues.append(issue("required", "effectiveDateTime must be an ISO-8601 datetime", "effectiveDateTime"))
    elif _parse_dt(eff).replace(tzinfo=None) > datetime.now():
        issues.append(issue("value", "effectiveDateTime cannot be in the future", "effectiveDateTime"))
    vq = res.get("valueQuantity")
    if not isinstance(vq, dict) or not isinstance(vq.get("value"), (int, float)) \
            or isinstance(vq.get("value"), bool):
        issues.append(issue("required", "valueQuantity.value must be a number", "valueQuantity"))
        return
    if coding and coding.get("system") == LOINC and coding.get("code") in PLAUSIBLE:
        label, unit, lo, hi = PLAUSIBLE[coding["code"]]
        if vq.get("unit") != unit and vq.get("code") != unit:
            issues.append(issue("code-invalid", f"{label} must use unit '{unit}'", "valueQuantity.unit"))
        if not lo <= vq["value"] <= hi:
            issues.append(issue("value", f"{label} {vq['value']} is outside plausible range {lo}-{hi}",
                                "valueQuantity.value"))


def _medreq(res, store, issues, known_ids):
    if res.get("status") not in MED_STATUS:
        issues.append(issue("code-invalid", f"status must be one of {sorted(MED_STATUS)}", "status"))
    if res.get("intent") not in MED_INTENT:
        issues.append(issue("code-invalid", f"intent must be one of {sorted(MED_INTENT)}", "intent"))
    c = _check_coding(res.get("medicationCodeableConcept"), "medicationCodeableConcept", issues)
    if c and not c.get("display"):
        issues.append(issue("required", "medicationCodeableConcept.coding[0].display is required",
                            "medicationCodeableConcept"))
    _check_subject(res, store, issues, known_ids)
