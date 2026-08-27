#!/usr/bin/env python3
"""Validate an insight JSON against an evidence ledger (standard library only)."""
import argparse, json, re
from pathlib import Path
TURN = re.compile(r"^INT-[A-Z0-9]+(?:-[A-Z0-9]+)*-T\d{3}$", re.IGNORECASE); INS = re.compile(r"^INS-\d{3}$"); HYP = re.compile(r"^HYP-\d{3}$")
def as_list(value): return value if isinstance(value, list) else ([] if value is None else [value])
def errors_for(ledger, analysis):
    errors = []; records = ledger.get("records", ledger if isinstance(ledger, list) else []); by_id = {r.get("turn_id"): r for r in records if isinstance(r, dict)}
    if len(by_id) != len(records): errors.append("ledger has duplicate or missing turn_id")
    for key in by_id:
        if not isinstance(key, str) or not TURN.fullmatch(key or ""): errors.append("ledger invalid Turn ID: %r" % key)
    for item in as_list(analysis.get("evidence")):
        if not isinstance(item, dict): continue
        ident = item.get("evidence_id", item.get("turn_id")); text = item.get("text", item.get("quote", item.get("respondent_quote")))
        if not isinstance(ident, str) or not TURN.fullmatch(ident): errors.append("evidence requires exact full Turn ID: %r" % ident); continue
        rec = by_id.get(ident)
        if not rec: errors.append("evidence does not exist: " + ident); continue
        if rec.get("speaker_role") != "respondent": errors.append("formal evidence is not respondent speech: " + ident)
        if text is not None and (not isinstance(text, str) or text not in str(rec.get("text", ""))): errors.append("evidence text does not match ledger: " + ident)
    for insight in as_list(analysis.get("insights")):
        if not isinstance(insight, dict): errors.append("insight must be an object"); continue
        iid = insight.get("insight_id", "")
        if not INS.fullmatch(str(iid)): errors.append("insight ID must be INS-xxx (not BINS): %r" % iid)
        evidence_ids = as_list(insight.get("supporting_evidence_ids")); supporters = set(as_list(insight.get("supporting_interview_ids")))
        if not evidence_ids: errors.append("%s has no supporting evidence" % iid)
        if not supporters: errors.append("%s has no supporting interview IDs" % iid)
        for eid in evidence_ids:
            if not isinstance(eid, str) or not TURN.fullmatch(eid): errors.append("%s uses invalid evidence ID %r" % (iid, eid)); continue
            rec = by_id.get(eid)
            if not rec: errors.append("%s references missing evidence %s" % (iid, eid)); continue
            if rec.get("speaker_role") != "respondent": errors.append("%s uses non-respondent evidence %s" % (iid, eid))
            if supporters and rec.get("interview_id") not in supporters: errors.append("%s evidence/interview alignment fails: %s" % (iid, eid))
        declared = insight.get("sample_coverage")
        respondent_interviews = {r.get("interview_id") for r in records if r.get("speaker_role") == "respondent"}
        partial = set(as_list(insight.get("conditional_support_interview_ids")))
        counter = set(as_list(insight.get("counter_interview_ids")))
        mixed = set(as_list(insight.get("mixed_interview_ids")))
        status_sets = {"S": supporters, "P": partial, "C": counter, "M": mixed}
        labels = list(status_sets)
        for left in range(len(labels)):
            for right in range(left + 1, len(labels)):
                overlap = status_sets[labels[left]] & status_sets[labels[right]]
                if overlap: errors.append("%s assigns an interview to multiple coverage states: %s" % (iid, sorted(overlap)))
        uncovered = insight.get("uncovered_interview_count")
        if uncovered is not None:
            if not isinstance(uncovered, int) or uncovered < 0: errors.append("%s uncovered_interview_count must be a nonnegative integer" % iid)
            elif len(supporters | partial | counter | mixed) + uncovered != len(respondent_interviews): errors.append("%s S/P/C/M/U count does not equal ledger respondent total" % iid)
        if isinstance(declared, str) and re.fullmatch(r"\d+/\d+", declared):
            n, total = map(int, declared.split("/")); valid = respondent_interviews
            if n != len(supporters): errors.append("%s sample_coverage numerator differs from unique supporters" % iid)
            if total != len(valid): errors.append("%s sample_coverage denominator differs from ledger" % iid)
        for field in ("conditional_support_interview_ids", "counter_interview_ids", "mixed_interview_ids"):
            if set(as_list(insight.get(field))) & supporters: errors.append("%s has overlapping supporters and %s" % (iid, field))
    for hyp in as_list(analysis.get("hypotheses")):
        if isinstance(hyp, dict) and not HYP.fullmatch(str(hyp.get("hypothesis_id", ""))): errors.append("hypothesis ID must be HYP-xxx: %r" % hyp.get("hypothesis_id"))
    return errors
def self_test():
    ledger = {"records": [{"turn_id":"INT-001-T001","interview_id":"INT-001","speaker_role":"interviewer","text":"Q"},{"turn_id":"INT-001-T002","interview_id":"INT-001","speaker_role":"respondent","text":"我很困扰"}]}
    valid = {"evidence":[{"evidence_id":"INT-001-T002","text":"我很困扰"}],"insights":[{"insight_id":"INS-001","supporting_evidence_ids":["INT-001-T002"],"supporting_interview_ids":["INT-001"],"conditional_support_interview_ids":[],"counter_interview_ids":[],"mixed_interview_ids":[],"uncovered_interview_count":0,"sample_coverage":"1/1"}],"hypotheses":[{"hypothesis_id":"HYP-001"}]}; assert not errors_for(ledger, valid)
    stable_ledger = {"records": [{"turn_id":"INT-SIM-006-T035","interview_id":"INT-SIM-006","speaker_role":"respondent","text":"稳定ID可校验"}]}
    stable = {"evidence":[{"evidence_id":"INT-SIM-006-T035","text":"稳定ID可校验"}],"insights":[{"insight_id":"INS-001","supporting_evidence_ids":["INT-SIM-006-T035"],"supporting_interview_ids":["INT-SIM-006"],"conditional_support_interview_ids":[],"counter_interview_ids":[],"mixed_interview_ids":[],"uncovered_interview_count":0,"sample_coverage":"1/1"}],"hypotheses":[]}; assert not errors_for(stable_ledger, stable)
    bad = {"evidence":[{"evidence_id":"INT-001-T001","text":"Q"}],"insights":[{"insight_id":"WRONG-1","supporting_evidence_ids":["INT-001-T001"],"supporting_interview_ids":["INT-999"],"sample_coverage":"2/1"}],"hypotheses":[{"hypothesis_id":"HYP-1"}]}; assert len(errors_for(ledger, bad)) >= 5
    print("validate_analysis_evidence self-test: OK")
def main():
    p = argparse.ArgumentParser(description="Validate formal respondent evidence, IDs, alignment, and clear counts in analysis JSON."); p.add_argument("ledger", nargs="?", help="Evidence ledger JSON"); p.add_argument("analysis", nargs="?", help="Analysis JSON"); p.add_argument("--self-test", action="store_true", help="Run built-in validator checks and exit"); a = p.parse_args()
    if a.self_test: self_test(); return
    if not a.ledger or not a.analysis: p.error("provide LEDGER ANALYSIS, or use --self-test")
    try: errs = errors_for(json.loads(Path(a.ledger).read_text(encoding="utf-8-sig")), json.loads(Path(a.analysis).read_text(encoding="utf-8-sig")))
    except (OSError, json.JSONDecodeError) as exc: p.error(str(exc))
    if errs:
        for err in errs: print("ERROR: " + err)
        raise SystemExit(1)
    print("OK: analysis evidence is valid")
if __name__ == "__main__": main()
