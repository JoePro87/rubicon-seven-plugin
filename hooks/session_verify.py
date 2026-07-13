"""Deterministic session-end verification — pure functions, no MCP/LLM dependency.

Each check returns a list of {"target": str, "ok": bool, "detail": str} dicts.
The verify_session_save() MCP tool aggregates and formats these.
"""
import datetime
import json
import re
from pathlib import Path


def _load_facts(facts_path):
    return json.loads(Path(facts_path).read_text(encoding="utf-8"))


def _expected_writes(facts):
    """Derive which writes should have landed, per facts-record-schema.md."""
    always = ["MEMORY.md", "dm_narrative_synthesis.md", "VAARN_DM_SCREEN.md",
              "WORLD_PROGRESS.md", "character_sync"]
    conditional = []
    if facts.get("locations_touched"):
        conditional.append("prep PROGRESS LOGs")
    cultivation = facts.get("escalations") or facts.get("scratchpad_routed", {}).get("cultivation_seeds")
    if cultivation:
        conditional.append("ANTAGONIST_CULTIVATION.md")
    if facts.get("escalations"):
        conditional.append("narrative_threads.json")
    if facts.get("beats"):
        conditional.append("RESONANCE_INDEX.md")
    return always, conditional


# Files whose freshness we can check directly by path (campaign-dir relative),
# excluding bookkeeping-only targets the verifier can't resolve to one file.
_CAMPAIGN_FILE = {
    "dm_narrative_synthesis.md": "dm_narrative_synthesis.md",
    "VAARN_DM_SCREEN.md": "VAARN_DM_SCREEN.md",
    "WORLD_PROGRESS.md": "WORLD_PROGRESS.md",
    "ANTAGONIST_CULTIVATION.md": "ANTAGONIST_CULTIVATION.md",
    "narrative_threads.json": "narrative_threads.json",
    "RESONANCE_INDEX.md": "RESONANCE_INDEX.md",
}


def check_writes_landed(facts_path, campaign_dir, memory_path):
    facts = _load_facts(facts_path)
    ref_mtime = Path(facts_path).stat().st_mtime
    always, conditional = _expected_writes(facts)
    results = []

    def _fresh(p, target):
        if not Path(p).exists():
            return {"target": target, "ok": False, "detail": "file missing"}
        ok = Path(p).stat().st_mtime >= ref_mtime
        return {"target": target, "ok": ok,
                "detail": "fresh" if ok else "stale (not written this session)"}

    for target in always + conditional:
        if target == "MEMORY.md":
            results.append(_fresh(memory_path, target))
        elif target == "dm_narrative_synthesis.md":
            # Lives in the memory dir alongside MEMORY.md, NOT the campaign dir.
            results.append(_fresh(Path(memory_path).parent / target, target))
        elif target in _CAMPAIGN_FILE:
            results.append(_fresh(Path(campaign_dir) / _CAMPAIGN_FILE[target], target))
        else:
            # character_sync, prep PROGRESS LOGs — surfaced for the agent, not path-checkable here
            results.append({"target": target, "ok": True,
                            "detail": "agent-attested (not a single-file check)"})
    return results


# Budget limits (bytes unless noted). From spec §9; W2 additions 2026-06-12.
BUDGET_BYTES = {"WORLD_PROGRESS.md": 20000, "RESONANCE_INDEX.md": 30000}
BUDGET_LINES = {"VAARN_DM_SCREEN.md": 120}
MASTER_CONTINUITY_WARN_BYTES = 150000
# Margin BEFORE the memory loader's 200-line truncation cliff - content past the
# cut vanishes silently, so the alarm must fire while there is still room to act.
MEMORY_LINE_BUDGET = 190
# The DM-screen Tensions block rides into context EVERY turn via the CLAUDE.md
# import; it accreted to 4,557 chars before the 2026-06-12 diet (1,860 after).
TENSIONS_CHAR_BUDGET = 2500
# Campaign CLAUDE.md is also an every-turn import. Warn-only: protocol edits are
# deliberate, not save-time accretion (6,492 bytes at calibration).
CLAUDE_MD_WARN_BYTES = 8000


def check_budgets(campaign_dir, memory_path):
    results = []
    campaign_dir = Path(campaign_dir)

    for name, limit in BUDGET_BYTES.items():
        p = campaign_dir / name
        size = p.stat().st_size if p.exists() else 0
        results.append({"target": name, "ok": size <= limit, "warn": False,
                        "detail": f"{size} bytes (limit {limit})"})

    for name, limit in BUDGET_LINES.items():
        p = campaign_dir / name
        lines = len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0
        results.append({"target": name, "ok": lines <= limit, "warn": False,
                        "detail": f"{lines} lines (limit {limit})"})

    mem = Path(memory_path)
    if mem.exists():
        mlines = len(mem.read_text(encoding="utf-8").splitlines())
        results.append({"target": "MEMORY.md", "ok": mlines <= MEMORY_LINE_BUDGET, "warn": False,
                        "detail": f"{mlines} lines (limit {MEMORY_LINE_BUDGET})"})
    else:
        # A missing file means this check measured nothing - loud, never a 0-line pass.
        results.append({"target": "MEMORY.md", "ok": False, "warn": False,
                        "detail": f"memory file not found at {mem}"})

    screen = campaign_dir / "VAARN_DM_SCREEN.md"
    if screen.exists():
        block = re.search(r"^Tensions.*?(?=^## |\Z)",
                          screen.read_text(encoding="utf-8"), re.M | re.S)
        if block:
            tchars = len(block.group(0))
            results.append({"target": "VAARN_DM_SCREEN.md Tensions",
                            "ok": tchars <= TENSIONS_CHAR_BUDGET, "warn": False,
                            "detail": f"{tchars} chars (limit {TENSIONS_CHAR_BUDGET}) - every-turn context cost"})

    claude_md = campaign_dir / "CLAUDE.md"
    c_size = claude_md.stat().st_size if claude_md.exists() else 0
    c_over = c_size > CLAUDE_MD_WARN_BYTES
    results.append({"target": "CLAUDE.md", "ok": True, "warn": c_over,
                    "detail": f"{c_size} bytes (warn at {CLAUDE_MD_WARN_BYTES})"
                              + (" - every-turn import has grown; diet or re-baseline" if c_over else "")})

    mc = campaign_dir / "MASTER_CONTINUITY_CURRENT.md"
    mc_size = mc.stat().st_size if mc.exists() else 0
    over = mc_size > MASTER_CONTINUITY_WARN_BYTES
    results.append({"target": "MASTER_CONTINUITY_CURRENT.md", "ok": True, "warn": over,
                    "detail": f"{mc_size} bytes (warn at {MASTER_CONTINUITY_WARN_BYTES})"
                              + (" — flag for arc archival" if over else "")})
    return results


def check_staleness(campaign_dir, memory_path, current_day, today=None):
    """W2: 'PENDING X' notes decay silently - enforce a check-by convention.

    Scans the campaign MEMORY.md and VAARN_DM_SCREEN.md for ALL-CAPS PENDING
    markers (prose 'pending' is ignored). Each must carry '(check-by YYYY-MM-DD)'
    (wall-clock) or '(check-by Dnnn)' (campaign day). Missing or past-due
    check-bys WARN - loud in the report, never blocks a save on prose semantics.
    """
    today = today or datetime.date.today()
    flagged = []

    sources = [("MEMORY.md", Path(memory_path)),
               ("VAARN_DM_SCREEN.md", Path(campaign_dir) / "VAARN_DM_SCREEN.md")]
    for name, path in sources:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"\bPENDING\b", line):
                continue
            m = re.search(r"check-by\s+(\d{4}-\d{2}-\d{2}|D\d+)", line)
            if not m:
                flagged.append(f"{name}:{lineno} PENDING with no check-by")
                continue
            stamp = m.group(1)
            if stamp.startswith("D"):
                past = int(stamp[1:]) < int(current_day)
            else:
                past = datetime.date.fromisoformat(stamp) < today
            if past:
                flagged.append(f"{name}:{lineno} PENDING past its check-by ({stamp})")

    if flagged:
        detail = ("stale PENDING notes - verify and clear or re-date "
                  "(convention: 'PENDING ... (check-by YYYY-MM-DD)' or '(check-by Dnnn)'): "
                  + "; ".join(flagged))
    else:
        detail = "no stale PENDING notes"
    return [{"target": "staleness", "ok": True, "warn": bool(flagged), "detail": detail}]


def check_day_agreement(facts_day, current_status_day):
    ok = int(facts_day) == int(current_status_day)
    return {"target": "day_agreement", "ok": ok,
            "detail": f"facts day={facts_day}, CURRENT_STATUS day={current_status_day}"
                      + ("" if ok else " — MISMATCH (day-regression risk)")}


def _norm_ent(s):
    """Normalize an entity string for lenient comparison (lowercase, alnum-spaced)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def check_corrections_landed(facts, bans, cache):
    """Every correction in this session's facts must have a permanent ban AND a cache fact.

    Matching is intentionally lenient. Reconcile backfills bans/cache under
    near-but-not-identical entity strings, wrong_terms, and keys, so exact
    equality produced false MISSING flags. We accept normalized-entity
    containment + >=1 wrong-term overlap for the ban, and we check the recorded
    backfill cache_entry (leading token, dropping any parenthetical note) before
    falling back to the correction's topic_key.
    """
    results = []
    existing_bans = bans.all_bans()
    for corr in facts.get("corrections", []):
        entity = _norm_ent(corr.get("entity", ""))
        wrong = set(t.lower().strip() for t in corr.get("wrong_terms", []))
        topic_key = corr.get("topic_key", "")
        cache_entry = (corr.get("backfilled", {}) or {}).get("cache_entry", "") or ""
        cache_key = cache_entry.split(" (")[0].strip()

        def _ban_matches(b):
            be = _norm_ent(b.get("entity", ""))
            ent_ok = (be == entity) if (not be or not entity) else (entity in be or be in entity)
            bw = set(t.lower().strip() for t in b.get("wrong_terms", []))
            overlap = wrong & bw
            # wrong_terms are the operative banned strings; the entity is only a
            # label. Strong wrong-term overlap alone confirms the protection is in
            # place even when reconcile filed the ban under a different label.
            strong_overlap = bool(wrong) and len(overlap) >= max(1, len(wrong) // 2)
            wrong_ok = (not wrong) or bool(overlap)
            return strong_overlap or (ent_ok and wrong_ok)

        has_ban = any(_ban_matches(b) for b in existing_bans)
        has_cache = (
            (bool(cache_key) and cache.get(cache_key) is not None)
            or (bool(topic_key) and cache.get(topic_key) is not None)
        )

        ok = has_ban and has_cache
        missing = []
        if not has_ban:
            missing.append("ban")
        if not has_cache:
            missing.append("cache fact")
        results.append({"target": f"correction:{corr.get('entity', '').lower()}", "ok": ok,
                        "detail": "landed" if ok else f"MISSING {', '.join(missing)}"})
    if not results:
        results.append({"target": "corrections", "ok": True, "detail": "none this session"})
    return results


def check_cache_loop(cache):
    """Pass #2 only: ingest must have left zero un-posted distillation entries."""
    unposted = cache.get_unposted()
    n = len(unposted)
    return {"target": "cache_loop", "ok": n == 0,
            "detail": f"{n} un-posted distillation(s) remain"
                      + ("" if n == 0 else " — corrections will NOT reach check_canon")}


def check_antagonist(campaign_dir, day):
    """Counts-only integrity of the dossier system. Never returns dossier contents."""
    campaign_dir = Path(campaign_dir)
    dossiers_dir = campaign_dir / "dossiers"
    index = campaign_dir / "ANTAGONIST_DOSSIER_INDEX.md"

    if not dossiers_dir.exists():
        return {"target": "antagonist", "ok": True, "detail": "no dossiers dir (nothing to verify)"}

    day = int(day)
    problems = []

    # Index stamped today?
    index_ok = False
    if index.exists():
        m = re.search(r"[Ll]ast updated.*?Day\s+(\d+)", index.read_text(encoding="utf-8"))
        index_ok = bool(m and int(m.group(1)) == day)
    if not index_ok:
        problems.append("index not stamped for today")

    active = ripening = 0
    stale_logs = 0
    for f in sorted(dossiers_dir.glob("*_DOSSIER.md")):
        text = f.read_text(encoding="utf-8")
        status_m = re.search(r"Status:\s*(\w+)", text)
        status = (status_m.group(1).upper() if status_m else "")
        if status not in ("ACTIVE", "RIPENING"):
            continue
        if status == "ACTIVE":
            active += 1
        else:
            ripening += 1
        # Maintenance-log entry dated today?
        after_log = text.split("Maintenance Log", 1)
        if len(after_log) > 1:
            bullet_lines = [ln for ln in after_log[1].splitlines()
                            if ln.lstrip().startswith(("-", "*"))]
            log_days = [int(d) for ln in bullet_lines
                        for d in re.findall(r"Day\s+(\d+)", ln)]
        else:
            log_days = []
        if day not in log_days:
            stale_logs += 1

    if stale_logs:
        problems.append(f"{stale_logs} active/ripening dossier(s) missing today's maintenance log")

    ok = not problems
    detail = f"{active} active, {ripening} ripening"
    if problems:
        detail += " — " + "; ".join(problems)
    return {"target": "antagonist", "ok": ok, "detail": detail}


def compute_vital_signs(facts, bans, distillations_written=0):
    """DM-only engine-health readout (E). Not a gate — but a banned error in committed prose is an alarm."""
    narrative = facts.get("narrative_log", "")
    banned_hits = bans.check_draft(narrative) if narrative else []
    return {
        "corrections_captured": len(facts.get("corrections", [])),
        "banned_errors_in_prose": len(banned_hits),
        "distillations_written": distillations_written,
        "alarm": len(banned_hits) > 0,
    }


def run_verification(facts_path, campaign_dir, memory_path, bans, cache,
                     current_status_day, pass_number=1, reindex_ok=True,
                     distillations_written=0):
    """Aggregate all checks. Pass 1 = pre-save gate; pass 2 adds cache-loop, reindex, vital signs."""
    facts = _load_facts(facts_path)
    checks = []
    checks.extend(check_writes_landed(facts_path, campaign_dir, memory_path))
    checks.extend(check_budgets(campaign_dir, memory_path))
    checks.extend(check_staleness(campaign_dir, memory_path, current_status_day))
    checks.append(check_day_agreement(facts["day"], current_status_day))
    checks.extend(check_corrections_landed(facts, bans, cache))
    checks.append(check_antagonist(campaign_dir, facts["day"]))

    report = {"pass_number": pass_number, "checks": checks}

    if pass_number == 2:
        checks.append(check_cache_loop(cache))
        checks.append({"target": "reindex", "ok": bool(reindex_ok),
                       "detail": "clean" if reindex_ok else "reindex reported an error"})
        report["vital_signs"] = compute_vital_signs(facts, bans, distillations_written)

    report["overall_ok"] = all(c["ok"] for c in checks)
    report["gaps"] = [c for c in checks if not c["ok"]]
    return report
