"""Explainable pair decisions. Never pick a winner or infer truth from repetition."""
from decimal import Decimal


def compare(left: dict, right: dict) -> dict | None:
    if left["subject_key"] != right["subject_key"] or left["predicate"] != right["predicate"]:
        return None
    a, b = left["normalized"], right["normalized"]
    ca, cb = left["context"], right["context"]
    steps = [f"Same conservative entity key: {left['subject_key']}.",
             f"Same normalized predicate: {left['predicate']}.", a["normalization"], b["normalization"]]

    def result(kind, reason, confidence):
        return {"kind": kind, "reason": reason, "steps": steps + [reason], "confidence": confidence,
                "caveat": "A relationship between documented claims; not an independent verification of truth."}

    if ca.get("unit_unresolved") or cb.get("unit_unresolved"):
        return result("uncertain", "Table-wide units have not been resolved from the row; numerical comparability needs review.", 0.4)
    if ca.get("qualifier_unresolved") or cb.get("qualifier_unresolved"):
        return result("uncertain", "A table footnote qualifies at least one metric; its definition needs review before scope alignment.", 0.4)
    if a["kind"] != b["kind"] or "ambiguous" in (a["kind"], b["kind"]):
        return result("uncertain", "Value types are incompatible or ambiguous; review the source.", 0.35)
    if a["unit"] != b["unit"]:
        return result("uncertain", "Units or currencies differ. No exchange rate or missing unit is assumed.", 0.45)
    if a["unit"] in ("$", "tons"):
        return result("uncertain", "Currency symbol or ton definition is ambiguous without an explicit convention.", 0.4)
    for field in ("period", "scope"):
        steps.append(f"{field.title()}: {ca[field] or 'unspecified'} ↔ {cb[field] or 'unspecified'}.")
    if ca.get("ambiguous") or cb.get("ambiguous") or ca.get("approximate") or cb.get("approximate"):
        return result("uncertain", "Ambiguous context or approximation requires human review.", 0.4)
    different = [k for k in ("period", "scope") if ca[k] and cb[k] and ca[k] != cb[k]]
    # Calendar year versus FY is not automatically a distinct, nonoverlapping period.
    if "period" in different:
        pa, pb = ca["period"], cb["period"]
        import re
        ya, yb = re.findall(r"\d{4}", pa), re.findall(r"\d{4}", pb)
        if ya == yb and (pa[:2] != pb[:2] or "/" in pa or "-" in pa or "/" in pb or "-" in pb):
            return result("uncertain", "Period labels may overlap (for example fiscal versus calendar year); boundaries are unknown.", 0.45)
    equal = Decimal(a["value"]) == Decimal(b["value"]) if a["kind"] == "number" else a["value"] == b["value"]
    if different:
        return result("reconciled", "Claims refer to different explicit " + " and ".join(different) +
                      "; they can coexist. This explains comparability, not the cause of the change.", 0.85)
    missing = [k for k in ("period", "scope") if bool(ca[k]) != bool(cb[k])]
    if missing:
        return result("uncertain", "One source omits " + " and ".join(missing) + "; alignment cannot be established.", 0.45)
    if equal:
        return result("corroborates", "Normalized values agree under the stated context. Unspecified context and shared upstream sources remain possible.", 0.88)
    if a["kind"] == "number" and (a.get("scaled") or b.get("scaled")) and abs(Decimal(a["value"])-Decimal(b["value"])) < (Decimal(a.get("resolution", "0"))+Decimal(b.get("resolution", "0")))/2:
        return result("reconciled", "Values differ but their displayed-precision intervals overlap after unit conversion. Rounding can explain the difference; inspect the source conventions.", 0.7)
    if a["kind"] == "text" and left["predicate"] != "address":
        return result("uncertain", "Different text values may be compatible descriptions or multiple valid values; no exclusivity is assumed.", 0.45)
    if not ca["period"]:
        return result("uncertain", "Values differ but neither source provides an explicit period; a time change could explain them.", 0.5)
    return result("contradicts", "Likely contradiction: different values for the same entity, metric, explicit period and stated scope. Check omitted qualifiers and source errors.", 0.82)
