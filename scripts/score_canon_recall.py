#!/usr/bin/env python3
"""Automated recall scorer -- the missing judge half of canon_recall_gate.py /
canon_recall_live.py. Reads a case dump either of those two produce and judges
each case with a headless `claude -p` call against a haiku-class model, one
YES / PARTIAL / NO verdict per case, then emits per-category recall rates plus
a scorecard file. Makes the 259-case bed re-runnable end-to-end again (it was
previously graded by hand / one-off harness scripts, not a repeatable tool).

Dump shape accepted (a JSON list of case dicts), matching either producer:
  - canon_recall_gate.py:  {id, source, category, input, expect, retrieved: [str, ...]}
  - canon_recall_live.py:  {id, source, category, input, expect, output: str, ...}
Either "retrieved" or "output" is used, whichever the case carries.

Judge pattern mirrors hooks/prose_observer.py's philosophy (fail-open, never
raise past a single case, structured/constrained output over free-form parsing)
but the project has settled on the headless Claude Code CLI rather than the
anthropic SDK directly for this scorer (owner-approved, see Task 6 of
docs/superpowers/specs/2026-07-04-rag-hardening-sprint.md) -- `--tools ""`
disables all tool use so the judge can only answer in text, and
`--output-format json` gives a stable `result` field to parse instead of
scraping stdout.

If the `claude` CLI is not on PATH at all, this exits 2 immediately (no point
burning N subprocess-not-found failures). A single case's judge call failing
(timeout, bad JSON, unparseable verdict, non-zero exit) is recorded as "ERROR"
and does not abort the run.

Usage:
  .venv/Scripts/python.exe scripts/score_canon_recall.py DUMP.json [--limit N] \\
      [--model claude-haiku-4-5-20251001] [--out SCORECARD.md]

Cost note: the full bed is 259 cases, each one a separate `claude -p` process.
Use --limit while developing/smoke-testing; only run the full bed deliberately.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
JUDGE_TIMEOUT_SECONDS = 90
MAX_RETRIEVED_CHARS = 6000  # keep the judge prompt bounded; snippets/outputs are already short

JUDGE_INSTRUCTIONS = (
    "You are grading a memory-retrieval system for a tabletop RPG campaign engine. "
    "Given an EXPECTED FACT and the TEXT actually retrieved/output for a query, decide "
    "whether the retrieved text surfaces the expected fact.\n\n"
    "Answer with EXACTLY one word: YES, PARTIAL, or NO. No punctuation, no explanation.\n"
    "YES = the fact is clearly present or directly derivable from the retrieved text.\n"
    "PARTIAL = related/adjacent information is present but the specific fact is not confirmed.\n"
    "NO = the fact is absent from the retrieved text, or the text contradicts it."
)


def _case_text(case: dict) -> str:
    """Normalize a case's retrieved content across the two dump shapes."""
    output = case.get("output")
    if output:
        return str(output)
    retrieved = case.get("retrieved")
    if retrieved:
        return "\n---\n".join(str(t) for t in retrieved)
    return ""


def judge_case(case: dict, model: str, claude_bin: str) -> str:
    """Return one of YES / PARTIAL / NO / ERROR. Never raises."""
    retrieved_text = _case_text(case)
    prompt = (
        f"{JUDGE_INSTRUCTIONS}\n\n"
        f"EXPECTED FACT:\n{case.get('expect', '')}\n\n"
        f"RETRIEVED/OUTPUT TEXT:\n{retrieved_text[:MAX_RETRIEVED_CHARS]}"
    )
    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt, "--model", model,
             "--output-format", "json", "--tools", ""],
            capture_output=True, text=True, timeout=JUDGE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "ERROR"
    except Exception:
        return "ERROR"
    if proc.returncode != 0:
        return "ERROR"
    try:
        payload = json.loads(proc.stdout)
        result = str(payload.get("result", "")).strip().upper()
    except Exception:
        return "ERROR"
    for tag in ("YES", "PARTIAL", "NO"):
        if tag in result:
            return tag
    return "ERROR"


def build_scorecard(dump_path: Path, model: str, verdicts: dict, cases: list,
                     elapsed: float, limited_to: int | None) -> str:
    bycat = defaultdict(Counter)
    for case in cases:
        cid = case.get("id", "")
        cat = case.get("category", "uncategorized")
        if cid in verdicts:
            bycat[cat][verdicts[cid]] += 1

    overall = Counter(verdicts.values())
    n = len(verdicts)

    lines = [
        "# Canon-Recall Scorecard",
        "",
        f"Dump: `{dump_path}` | Judge: `{model}` via headless `claude -p` | cases judged: {n}"
        + (f" (limited from full dump by --limit {limited_to})" if limited_to else ""),
        f"Elapsed: {elapsed:.0f}s",
        "",
        "## Overall",
        "",
        "| Verdict | Count | % |",
        "|---|---|---|",
    ]
    for tag in ("YES", "PARTIAL", "NO", "ERROR"):
        c = overall.get(tag, 0)
        pct = f"{100 * c / n:.0f}%" if n else "-"
        lines.append(f"| {tag} | {c} | {pct} |")

    lines += ["", "## By category", "",
              "| Category | YES | PARTIAL | NO | ERROR | n |", "|---|---|---|---|---|---|"]
    for cat, counts in sorted(bycat.items()):
        cn = sum(counts.values())
        lines.append(f"| {cat} | {counts.get('YES', 0)} | {counts.get('PARTIAL', 0)} | "
                      f"{counts.get('NO', 0)} | {counts.get('ERROR', 0)} | {cn} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", type=Path,
                         help="Path to a canon-recall dump JSON (from canon_recall_gate.py or canon_recall_live.py)")
    parser.add_argument("--limit", type=int, default=None,
                         help="Judge only the first N cases (cost control; the full bed is 259 cases)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                         help=f"Judge model (default: {DEFAULT_MODEL})")
    parser.add_argument("--out", type=Path, default=None,
                         help="Scorecard markdown path (default: <dump-dir>/<dump-stem>-scorecard.md)")
    parser.add_argument("--verdicts-out", type=Path, default=None,
                         help="Optional path to also write raw per-case verdicts as JSON")
    args = parser.parse_args()

    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("ERROR: `claude` CLI not found on PATH. score_canon_recall.py judges via headless "
              "`claude -p`, which requires the Claude Code CLI installed and authenticated.",
              file=sys.stderr)
        return 2

    if not args.dump.exists():
        print(f"ERROR: dump file not found: {args.dump}", file=sys.stderr)
        return 2

    try:
        cases = json.loads(args.dump.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: could not parse dump JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(cases, list):
        print("ERROR: dump JSON must be a list of case objects", file=sys.stderr)
        return 2

    limited_to = args.limit
    if limited_to is not None:
        cases = cases[:limited_to]

    verdicts = {}
    t0 = time.time()
    for i, case in enumerate(cases):
        cid = case.get("id", f"case_{i}")
        cat = case.get("category", "uncategorized")
        v = judge_case(case, args.model, claude_bin)
        verdicts[cid] = v
        print(f"  [{i + 1}/{len(cases)}] {cid} ({cat}): {v}", file=sys.stderr)
    elapsed = time.time() - t0

    scorecard_text = build_scorecard(args.dump, args.model, verdicts, cases, elapsed, limited_to)

    out_path = args.out or args.dump.with_name(args.dump.stem + "-scorecard.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scorecard_text, encoding="utf-8")
    print(f"\nScorecard written: {out_path}")

    if args.verdicts_out:
        args.verdicts_out.parent.mkdir(parents=True, exist_ok=True)
        args.verdicts_out.write_text(json.dumps({"verdicts": verdicts}, indent=2), encoding="utf-8")
        print(f"Verdicts written: {args.verdicts_out}")

    print()
    print(scorecard_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
