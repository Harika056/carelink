"""Illustrative drug-interaction check.

NOT clinical decision support. The rule table is a tiny, hand-written teaching sample
of well-known interaction pairs; a real system would use a licensed drug database.
"""
from itertools import combinations

# (drug keyword A, drug keyword B, severity, effect)
RULES = [
    ("warfarin", "aspirin", "major", "Increased bleeding risk"),
    ("warfarin", "ibuprofen", "major", "Increased bleeding risk"),
    ("lisinopril", "spironolactone", "major", "Risk of high potassium (hyperkalemia)"),
    ("simvastatin", "clarithromycin", "major", "Raised statin levels; muscle injury risk"),
    ("sildenafil", "nitroglycerin", "contraindicated", "Severe drop in blood pressure"),
    ("metformin", "contrast", "moderate", "Lactic acidosis risk around contrast imaging"),
    ("lisinopril", "ibuprofen", "moderate", "Reduced blood-pressure effect; kidney strain"),
    ("sertraline", "tramadol", "major", "Serotonin syndrome risk"),
]
RANK = {"moderate": 1, "major": 2, "contraindicated": 3}
DISCLAIMER = ("Illustrative rule table for a portfolio project. Not medical advice and not "
              "a substitute for a licensed drug-interaction database or clinician review.")


def _name(medreq):
    cc = medreq.get("medicationCodeableConcept") or {}
    coding = (cc.get("coding") or [{}])[0]
    return (coding.get("display") or cc.get("text") or "").lower()


def check(medication_requests):
    """Pairwise-check ACTIVE medication requests. Returns findings sorted worst-first."""
    active = [m for m in medication_requests if m.get("status") == "active"]
    findings = []
    for a, b in combinations(active, 2):
        na, nb = _name(a), _name(b)
        for ka, kb, sev, effect in RULES:
            if (ka in na and kb in nb) or (ka in nb and kb in na):
                findings.append({
                    "severity": sev,
                    "drugs": sorted([na, nb]),
                    "effect": effect,
                    "medicationRequests": sorted([a["id"], b["id"]]),
                })
    findings.sort(key=lambda f: (-RANK[f["severity"]], f["drugs"]))
    return {"count": len(findings), "findings": findings, "disclaimer": DISCLAIMER}
