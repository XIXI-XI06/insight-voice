#!/usr/bin/env python3
"""Build a deterministic, traceable ledger from interview transcripts.

Only the Python standard library is required. DOCX files are read directly
from their Office Open XML package, so python-docx is intentionally optional.
"""
import argparse
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

TURN = re.compile(r"^INT-[A-Z0-9]+(?:-[A-Z0-9]+)*-T\d{3}$", re.IGNORECASE)
INTERVIEW_ID = re.compile(r"\bINT-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
LABEL = re.compile(r"^(?:(?P<time>\[?\d{1,2}:\d{2}(?::\d{2})?\]?)\s*)?(?P<speaker>[\w\u4e00-\u9fff .·-]{1,40})\s*(?:[：:]|\((?P<ptime>\d{1,2}:\d{2}(?::\d{2})?)\)\s*[:：])\s*(?P<text>.*)$")

def read_docx(path):
    """Return visible paragraph text without third-party dependencies."""
    with zipfile.ZipFile(path) as zf: root = ET.fromstring(zf.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    for p in root.iter(ns + "p"):
        chunks = []
        for node in p.iter():
            if node.tag == ns + "t": chunks.append(node.text or "")
            elif node.tag == ns + "tab": chunks.append("\t")
            elif node.tag == ns + "br": chunks.append("\n")
        value = "".join(chunks).strip()
        if value: out.extend(value.splitlines())
    return out

def read_lines(path):
    suffix = path.suffix.lower()
    if suffix == ".docx": return read_docx(path)
    if suffix not in (".md", ".txt"): raise ValueError("unsupported file type: " + suffix)
    return path.read_text(encoding="utf-8-sig").splitlines()

def role_for(label):
    key = re.sub(r"\s+", "", label).lower()
    if key in {"受访者", "用户", "被访者", "respondent", "participant", "interviewee", "answer", "a"}: return "respondent"
    if key in {"访谈者", "采访者", "研究员", "主持人", "interviewer", "moderator", "question", "q"}: return "interviewer"
    if any(x in key for x in ("研究员笔记", "笔记", "note")): return "researcher_note"
    if any(x in key for x in ("系统", "转写", "system", "transcript")): return "system_note"
    if key.startswith(("interviewer", "moderator", "访谈者", "采访者")): return "interviewer"
    if key.startswith(("respondent", "participant", "interviewee", "受访者", "用户", "被访者")): return "respondent"
    return "unknown"

def parse_lines(lines, interview_id, source_file):
    turns, current = [], None
    for number, raw in enumerate(lines, 1):
        text = raw.strip()
        if not text: continue
        match = LABEL.match(text)
        if match:
            label, body = match.group("speaker").strip(), match.group("text").strip()
            role = role_for(label)
            if role in ("researcher_note", "system_note"):
                current = None; continue
            current = {"speaker": label, "speaker_role": role, "text": body, "source_line_start": number, "source_line_end": number, "timestamp": match.group("time") or match.group("ptime")}
            turns.append(current)
        elif current is not None:
            current["text"] = (current["text"] + "\n" + text).strip(); current["source_line_end"] = number
    records = []
    for index, turn in enumerate(turns, 1):
        locator = turn["timestamp"] or "lines %d-%d" % (turn["source_line_start"], turn["source_line_end"])
        role = turn["speaker_role"]
        records.append({"turn_id": "%s-T%03d" % (interview_id, index), "interview_id": interview_id, "source_file": source_file, "source_locator": locator, "speaker_alias": role if role in ("interviewer", "respondent") else "unknown", "speaker": turn["speaker"], "speaker_role": role, "text": turn["text"], "timestamp": turn["timestamp"], "source_line_start": turn["source_line_start"], "source_line_end": turn["source_line_end"], "transcription_flags": [], "evidence_eligibility": "formal" if role == "respondent" else "context_only", "confidence": "high" if role in ("respondent", "interviewer") else "unknown"})
    return records

def interview_id_for(lines, fallback):
    """Keep a stable interview ID already supplied in the transcript."""
    for line in lines[:50]:
        found = INTERVIEW_ID.search(line)
        if found: return found.group(0).upper()
    return fallback

def build(paths):
    records, interviews, used_ids = [], [], set()
    for n, path in enumerate(sorted((Path(p) for p in paths), key=lambda x: str(x).lower()), 1):
        lines = read_lines(path); iid = interview_id_for(lines, "INT-%03d" % n)
        if iid in used_ids: raise ValueError("duplicate interview ID: " + iid)
        used_ids.add(iid); items = parse_lines(lines, iid, str(path)); records.extend(items)
        interviews.append({"interview_id": iid, "source_file": str(path), "turn_count": len(items)})
    return {"schema_version": "1.0", "interviews": interviews, "records": records}

def self_test():
    got = parse_lines(["访谈者：最近用过吗？", "受访者：是", "  昨天用的。", "[00:03] Speaker 2: okay", "Alice(00:04): Hello", "00:05 Interviewer: Why?"], "INT-001", "x.txt")
    assert [x["turn_id"] for x in got] == ["INT-001-T001", "INT-001-T002", "INT-001-T003", "INT-001-T004", "INT-001-T005"]
    assert got[1]["text"] == "是\n昨天用的。" and got[1]["speaker_role"] == "respondent"
    assert got[2]["speaker_role"] == "unknown" and got[3]["timestamp"] == "00:04" and got[4]["speaker_role"] == "interviewer" and all(TURN.match(x["turn_id"]) for x in got)
    assert all({"source_locator", "speaker_alias", "speaker_role", "transcription_flags"} <= set(x) for x in got)
    assert interview_id_for(["# INT-SIM-006"], "INT-001") == "INT-SIM-006"
    # Exercise the dependency-free DOCX reader with a minimal OOXML package.
    xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>受访者：DOCX可读</w:t></w:r></w:p></w:body></w:document>'
    with tempfile.TemporaryDirectory() as folder:
        docx = Path(folder) / "sample.docx"
        with zipfile.ZipFile(docx, "w") as zf: zf.writestr("word/document.xml", xml)
        assert read_lines(docx) == ["受访者：DOCX可读"]
    print("build_evidence_ledger self-test: OK")

def main():
    parser = argparse.ArgumentParser(description="Create deterministic INT-xxx-Txxx evidence ledgers from .md, .txt, or .docx transcripts.")
    parser.add_argument("inputs", nargs="*", help="Transcript files (.md, .txt, .docx)"); parser.add_argument("-o", "--output", help="Ledger JSON output path (default: stdout)"); parser.add_argument("--self-test", action="store_true", help="Run built-in parser checks and exit")
    args = parser.parse_args()
    if args.self_test: self_test(); return
    if not args.inputs: parser.error("provide at least one transcript, or use --self-test")
    try: payload = build(args.inputs)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc: parser.error(str(exc))
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output: Path(args.output).write_text(rendered, encoding="utf-8")
    else: sys.stdout.write(rendered)
if __name__ == "__main__": main()
