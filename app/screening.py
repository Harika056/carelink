"""Explainable cardiometabolic screening flags from a patient's latest observations.

Rule-based (no ML, no training data): every flag names the rule, the observation it
came from, and the published threshold it uses. Educational only.
"""
DISCLAIMER = ("Educational screening flags from simple threshold rules. Not a diagnosis and not "
              "a clinical risk score; clinical decisions belong to a clinician.")

SYS, DIA, A1C, BMI, CHOL, HR = "8480-6", "8462-4", "4548-4", "39156-5", "2093-3", "8867-4"
CODES = [SYS, DIA, A1C, BMI, CHOL, HR]


def _flag(rule, label, obs, threshold):
    return {"rule": rule, "flag": label, "observation": obs["id"],
            "value": obs["valueQuantity"]["value"], "threshold": threshold}


def evaluate(latest):
    """`latest` maps LOINC code -> newest Observation resource for the patient."""
    flags = []
    v = lambda c: latest[c]["valueQuantity"]["value"] if c in latest else None

    if v(SYS) is not None and v(SYS) >= 140:
        flags.append(_flag("BP-1", "Blood pressure in stage 2 range (systolic)", latest[SYS],
                           "systolic >= 140 mm[Hg] (ACC/AHA 2017)"))
    elif v(DIA) is not None and v(DIA) >= 90:
        flags.append(_flag("BP-1", "Blood pressure in stage 2 range (diastolic)", latest[DIA],
                           "diastolic >= 90 mm[Hg] (ACC/AHA 2017)"))
    if v(A1C) is not None:
        if v(A1C) >= 6.5:
            flags.append(_flag("GLU-1", "HbA1c in diabetes range", latest[A1C], "HbA1c >= 6.5 % (ADA)"))
        elif v(A1C) >= 5.7:
            flags.append(_flag("GLU-2", "HbA1c in prediabetes range", latest[A1C],
                               "5.7 % <= HbA1c < 6.5 % (ADA)"))
    if v(BMI) is not None and v(BMI) >= 30:
        flags.append(_flag("BMI-1", "BMI in obesity range", latest[BMI], "BMI >= 30 kg/m2 (WHO)"))
    if v(CHOL) is not None and v(CHOL) >= 240:
        flags.append(_flag("LIP-1", "Total cholesterol high", latest[CHOL], "total cholesterol >= 240 mg/dL"))
    if v(HR) is not None and (v(HR) > 100 or v(HR) < 50):
        flags.append(_flag("HR-1", "Heart rate outside 50-100/min", latest[HR],
                           "heart rate < 50 or > 100 /min"))

    n = len(flags)
    level = "none" if n == 0 else "low" if n == 1 else "moderate" if n == 2 else "high"
    return {"attentionLevel": level, "flagCount": n, "flags": flags,
            "observationsUsed": sorted(o["id"] for o in latest.values()),
            "disclaimer": DISCLAIMER}
