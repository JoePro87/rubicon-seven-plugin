"""Session / persistence tools — Wave 8 of the tool-consolidation program.

Moved VERBATIM from server.py. These tools are tightly coupled to server.py's
helper web, so rather than the engine_core import-and-alias pattern they receive
their server-resident dependencies via register_session_tools(mcp, srv) at
registration time (after server.py is fully loaded). That dodges the circular
import: server.py imports THIS module to register the tools; this module never
imports server. Tool NAMES are unchanged, so the session-end/session-start skills
and the hooks that call them by name are unaffected.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from datetime import datetime

from pydantic import Field

# Server-resident dependencies. Bound to None at import; register_session_tools()
# replaces them with the live server objects via getattr(srv, name).
CAMPAIGN_DIR = None
_get_tool_tags = None
_pf = None
_read_current_status_day = None
_emit_player_view = None


def load_last_session() -> str:
    """Reach for this WHEN play resumes after a mid-session interruption or you suspect the save is stale and want to verify the checkpoint — at normal session start, full_session_startup already includes this recap; don't call both.

    Get most recent session checkpoint. Use when resuming after interruption or checking last save."""
    try:
        continuity_path = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"
        
        if not continuity_path.exists():
            return "Ã¢Å¡Â Ã¯Â¸Â MASTER_CONTINUITY_CURRENT.md not found"
        
        content = continuity_path.read_text(encoding='utf-8')
        
        # Find all SESSION SAVED markers
        pattern = r'## SESSION SAVED - Day \d+[^\n]*\n(.*?)(?=\n---\n|## SESSION SAVED|\Z)'
        matches = list(re.finditer(pattern, content, re.DOTALL))
        
        if not matches:
            return "Ã¢Å¡Â Ã¯Â¸Â No SESSION SAVED markers found in MASTER_CONTINUITY_CURRENT.md"
        
        # Get the last one
        last_match = matches[-1]
        
        # Extract the full section including header
        start = last_match.start() - 3  # Back up to include "## "
        section_content = content[start:last_match.end()].strip()
        
        # Find the header line for metadata
        header_match = re.search(r'## SESSION SAVED - Day (\d+) \(([^)]+)\)', section_content)
        
        if header_match:
            day = header_match.group(1)
            timestamp = header_match.group(2)
            
            return f"""
{'='*60}
LAST SESSION CHECKPOINT
{'='*60}

**Day:** {day}
**Saved:** {timestamp}

{section_content}

{'='*60}
Resume from this point. Scene context above tells you where/who/what.
{'='*60}
"""
        else:
            return f"""
{'='*60}
LAST SESSION CHECKPOINT
{'='*60}

{section_content}

{'='*60}
"""
    
    except Exception as e:
        return f"Ã¢ÂÅ’ Error loading last session: {str(e)}"


def verify_session_save(
    facts_path: str = Field(description="Path to the frozen session_end_facts.json"),
    pass_number: int = Field(default=1, description="1 = pre-save gate; 2 = post-save (adds cache-loop, reindex, vital signs)"),
    reindex_ok: bool = Field(default=True, description="Pass-2 only: whether reindex_recent() returned clean"),
    distillations_written: int = Field(default=0, description="Pass-2 only: count of distillation entries written this session"),
) -> str:
    """Reach for this WHEN a session-end verify pass is due — pass 1 gates the save (run after the Write agent's files land, BEFORE prepare_save_state); pass 2 runs after confirm_save and the Step-7 index calls to confirm the loop closed.

    Deterministic session-end verifier. Confirms every expected write landed, files are
    under budget, the day agrees everywhere, this session's corrections became permanent bans,
    and (pass 2) the distillation cache loop closed. Returns a PASS/FAIL report. DM-only.
    Antagonist results are counts only — never contents."""
    try:
        from hooks.session_verify import run_verification
    except ImportError:
        from session_verify import run_verification
    from hooks.fabrication_bans import FabricationBans
    from hooks.distillation_cache import DistillationCache
    from rubicon_paths import campaign_dir as _campaign_dir
    from rubicon_paths import campaign_memory_md_path as _campaign_memory_md_path

    # Path normalization: this server runs Windows Python (CAMPAIGN_DIR = C:\...),
    # so a WSL-style /mnt/<drive>/... facts_path flips to \mnt\c\... under Path()
    # and fails. If the given path is missing but its Windows translation exists,
    # use the translation. Cross-platform-safe (only swaps on a confirmed resolve).
    if facts_path and not Path(facts_path).exists():
        _m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", facts_path)
        if _m:
            _win = f"{_m.group(1).upper()}:\\" + _m.group(2).replace("/", "\\")
            if Path(_win).exists():
                facts_path = _win

    bans = FabricationBans(_campaign_dir() / "fabrication_bans.json")  # campaign-scoped (was an independent engine-relative re-derivation)
    cache = DistillationCache(_DISTILLATION_CACHE_PATH)  # campaign-scoped + respects monkeypatch (was an independent engine-relative re-derivation)
    memory_path = _campaign_memory_md_path()  # derived from campaign_dir() (was a hardcoded owner slug)

    try:
        current_day = int(_read_current_status_day())
    except Exception:
        current_day = json.loads(Path(facts_path).read_text(encoding="utf-8"))["day"]

    report = run_verification(
        facts_path, CAMPAIGN_DIR, memory_path, bans, cache,
        current_status_day=current_day, pass_number=pass_number,
        reindex_ok=reindex_ok, distillations_written=distillations_written,
    )

    lines = [f"SESSION-SAVE VERIFY (pass {pass_number}): "
             + ("PASS" if report["overall_ok"] else "FAIL")]
    for c in report["checks"]:
        mark = "ok" if c["ok"] else "FAIL"
        warn = " (warn)" if c.get("warn") else ""
        lines.append(f"  [{mark}{warn}] {c['target']}: {c['detail']}")
    if report.get("gaps"):
        lines.append("GAPS TO REPAIR: " + ", ".join(g["target"] for g in report["gaps"]))
    if "vital_signs" in report:
        vs = report["vital_signs"]
        lines.append(f"VITAL SIGNS (DM-only): corrections={vs['corrections_captured']}, "
                     f"banned-errors-in-prose={vs['banned_errors_in_prose']}, "
                     f"distillations={vs['distillations_written']}"
                     + ("  ALARM: a banned error reached committed prose" if vs["alarm"] else ""))
    if pass_number == 1 and report["overall_ok"]:
        # prepare_save_state REQUIRES session_summary + day; render placeholders
        # via raw() so the call is valid on copy-paste (day is the literal int).
        lines.append(_pf.next_block(
            _pf.push_call("prepare_save_state",
                          session_summary=_pf.raw('"<2-3 sentence summary>"'),
                          day=_pf.raw(str(current_day))),
            label="save"))
    return "\n".join(lines)


# C4: a faction record not touched in this many in-game days is FLAGGED at
# session start for the DM to reconcile — it may have drifted from play (e.g. an
# alliance sealed in fiction that never got a faction() ledger delta). The engine
# flags; it never edits play-state.
_FACTION_STALE_DAYS = 20

# C29: a relationship() store pair whose last status shift is within this many
# in-game days is surfaced at session start (recently-shifted briefing), so an
# engine-recorded change resurfaces even before both entities are in a scene.
_REL_RECENT_DAYS = 14


def _site_features_briefing_lines():
    """Session-start block: current place's stamped site-features.
    Place precedence: game_state active_location_name, then CURRENT_STATUS.md
    Location line. NEVER geography party_location (stale). Empty when none."""
    import site_features
    place = ""
    try:
        gs = json.loads((CAMPAIGN_DIR / "game_state.json").read_text(encoding="utf-8"))
        place = (gs.get("active_location_name") or "").strip()
    except Exception:
        pass
    if not place:
        try:
            content = (CAMPAIGN_DIR / "CURRENT_STATUS.md").read_text(encoding="utf-8")
            m = re.search(r'\*\*Location:\*\*\s*(.+)', content)
            if m:
                place = m.group(1).strip()
        except Exception:
            pass
    if not place:
        return []
    entry = site_features.place_entry(CAMPAIGN_DIR, place)
    if not entry or not entry.get("features"):
        return []
    return ["=== 📍 SITE FEATURES (current place) ==="] + \
        site_features.format_features_block(entry).split("\n")


def full_session_startup(characters_present: str = None) -> str:
    """Reach for this WHEN a new play session begins — call it before any other tool; it loads the day, last-session recap, active threads, NPC states, and prose-observer feedback (deeper per-turn context loads via check_canon, which you must still call every turn).

    MANDATORY at session start. Call before any other tool when beginning a new session.

    If characters_present is not provided, auto-detects from CURRENT_STATUS.md 'Present:' field
    to enable vector search for relevant character history.
    """
    results = []

    # Clear the rulebook dedup cooldown so a new session starts fresh (a rule
    # returned last session is searchable again). See C6 — the cooldown is now
    # self-driven per search, and this is its one session-boundary reset.
    try:
        rulebook_system.reset_session()
    except Exception:
        pass

    # === AUTO-DETECT CHARACTERS FROM CURRENT_STATUS.MD ===
    if not characters_present:
        try:
            status_content = read_file("CURRENT_STATUS.md")
            # Look for "**Present:**" or "Present:" line
            present_match = re.search(r'\*{0,2}Present\*{0,2}:\s*\*{0,2}\s*(.+?)(?:\n|$)', status_content, re.IGNORECASE)
            if present_match:
                characters_present = present_match.group(1).strip()
                # Clean up any markdown asterisks
                characters_present = re.sub(r'^\*+\s*|\s*\*+$', '', characters_present).strip()
        except Exception:
            pass  # Fall through to None, vector search will be skipped

    # Helper function to extract a section from content
    def extract_section(content: str, section_name: str) -> str:
        lines = content.split('\n')
        target = section_name.strip().lstrip('#').strip().lower()

        start_idx = None
        header_level = None

        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                header_match = re.match(r'^(#+)\s*(.+)$', line.strip())
                if header_match:
                    level = len(header_match.group(1))
                    header_text = header_match.group(2).strip().lower()

                    if target in header_text or header_text in target:
                        start_idx = i
                        header_level = level
                        break

        if start_idx is None:
            return f"Ã¢Å¡Â Ã¯Â¸Â Section '{section_name}' not found"

        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if lines[i].strip().startswith('#'):
                header_match = re.match(r'^(#+)\s*(.+)$', lines[i].strip())
                if header_match:
                    level = len(header_match.group(1))
                    if level <= header_level:
                        end_idx = i
                        break

        return '\n'.join(lines[start_idx:end_idx])

    # === 1. CURRENT DAY ===
    try:
        content = read_file("CURRENT_STATUS.md")
        match = re.search(r'DAY\s+(\d+)', content, re.IGNORECASE)
        if match:
            day_num = match.group(1)
            date_match = re.search(r'\((.*?of.*?)\)', content)
            if date_match:
                day_info = f"Day {day_num} ({date_match.group(1)})"
            else:
                day_info = f"Day {day_num}"
        else:
            day_info = "Ã¢Å¡Â Ã¯Â¸Â Could not determine current day"
    except Exception as e:
        day_info = f"Ã¢Å¡Â Ã¯Â¸Â Error getting day: {str(e)}"

    results.append("=== DAY ===")
    results.append(day_info)
    results.append("")

    # === PREP INTEGRITY (handoff PREP_INJECTION_DEAD_2026-07-24) ===
    # If CURRENT_STATUS names an active prep that resolves to no file, SCREAM.
    # Prep injection + prep: provenance both fail silently otherwise — the exact
    # failure that ran unnoticed for ~80 turns of the Thyricost dungeon.
    try:
        _prep_scream = _startup_prep_scream_lines()
        if _prep_scream:
            results.append("=== ⚠️ PREP INTEGRITY ===")
            results.extend(_prep_scream)
            results.append("")
    except Exception:
        pass  # Non-critical: never block session start on this check

    # === 1.5 PROSE OBSERVER RECENT CATCHES (last session feedback loop) ===
    observer_summary = _build_prose_observer_summary()
    if observer_summary:
        results.append(observer_summary)

    # === 2. VOICE GUIDE — DEFERRED to check_canon ===
    # check_canon loads selective voice guide per-turn. ~200 token savings.

    # === DEFERRED SECTIONS ===
    # Voice guide, scene state, emotional state, arc context, vector search,
    # knowledge boundaries, relationships, tripwires: all provided by check_canon
    # on its first per-turn call. Startup only carries unique data.
    results.append("=== DEFERRED TO check_canon ===")
    results.append("Voice guide, scene state, emotional state, arc context, relationships, vector search, knowledge boundaries: loaded by check_canon on first call.")
    results.append("")

    # === 5. SCENE STATE — DEFERRED to check_canon ===
    # check_canon extracts richer scene state (includes prep injection, secrets, progress log).
    # ~300 token savings.

    # === 5b. RECENT NPC STATES ===
    try:
        npc_path = CAMPAIGN_DIR / "npc_states.json"
        if npc_path.exists():
            with open(npc_path, 'r', encoding='utf-8') as f:
                npc_data = json.load(f)

            try:
                current_day_num = int(day_num)
            except (NameError, ValueError):
                current_day_num = 0
            recent_npcs = []
            for npc_id, npc_info in npc_data.get("npcs", {}).items():
                last_seen = npc_info.get("last_seen_day", 0)
                if current_day_num - last_seen <= 10:
                    name = npc_info.get("name", npc_id)
                    disposition = npc_info.get("disposition", "unknown")
                    location = npc_info.get("location", "unknown")
                    wants = npc_info.get("wants", "")
                    recent_npcs.append(
                        f"- **{name}** [{disposition}] at {location}"
                        + (f" — wants: {wants}" if wants else "")
                    )

            if recent_npcs:
                results.append("=== RECENT NPC STATES ===")
                results.append("\n".join(recent_npcs))
                results.append("")
    except Exception:
        pass  # Non-critical

    # === 6b. ARC CONTEXT — DEFERRED to check_canon ===
    # Included in check_canon scene state block. ~150 token savings.

    # === 6b2. EMOTIONAL STATE — DEFERRED to check_canon ===
    # Included in check_canon scene state block. ~100 token savings.

    # === 6c. ACTIVE THREADS ===
    # Read CURRENT_STATUS.md for thread extraction (was previously read by removed SCENE STATE block)
    try:
        status = read_file("CURRENT_STATUS.md")
    except Exception:
        status = ""
    try:
        active_threads = extract_section(status, "## ACTIVE THREADS")
        if not active_threads.startswith("Section"):
            results.append("=== ACTIVE THREADS ===")
            results.append(active_threads)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6d. TRACKED THREADS (from narrative_threads.json) ===
    try:
        threads_path = CAMPAIGN_DIR / "narrative_threads.json"
        if threads_path.exists():
            threads_data = _load_cached_json(threads_path, 'threads')
            active_thread_lines = []
            for tid, tdata in threads_data.get("threads", {}).items():
                if tdata.get("status") != "resolved":
                    urgency = tdata.get("urgency", "low")
                    title = tdata.get("title", tid)
                    active_thread_lines.append(f"- [{urgency.upper()}] {title}")
            if active_thread_lines:
                results.append("=== TRACKED THREADS (from narrative_threads.json) ===")
                results.append("\n".join(active_thread_lines))
                results.append("")
    except Exception:
        pass  # Non-critical

    # === 6e. WORLD FORCES (world tick, 2026-06-12) ===
    # READ-ONLY briefing of thread clocks. PILLAR: a fired clock reappears on
    # EVERY session start until its thread logs a development with
    # day >= fired_day (surfaced in fiction). Omitted entirely when empty.
    try:
        if THREADS_FILE.exists():
            _wf_data, _wf_err = _load_threads()
            if not _wf_err and isinstance(_wf_data, dict):
                _wf_day = _thread_current_day()
                _wf_fired, _wf_due, _wf_pending = [], [], []
                _wf_stale = 0
                for _wf_tid, _wf_t in _wf_data.get("threads", {}).items():
                    if not isinstance(_wf_t, dict):
                        continue
                    if _wf_t.get("status") == "resolved":
                        continue
                    _wf_clk = _wf_t.get("clock")
                    _wf_devs = [d for d in (_wf_t.get("developments") or [])
                                if isinstance(d, dict)]
                    if not isinstance(_wf_clk, dict):
                        # Clockless: stale if no activity in 14+ days.
                        _wf_last = max(
                            [_wf_t.get("introduced_day") or 0]
                            + [d.get("day") for d in _wf_devs
                               if isinstance(d.get("day"), int)])
                        if _wf_day - _wf_last > 14:
                            _wf_stale += 1
                        continue
                    _wf_pull = _pf.push_call(
                        "thread", action="get", thread_id=_wf_tid)
                    _wf_label = _wf_clk.get("label", _wf_tid)
                    if _wf_clk.get("fired"):
                        _wf_fday = _wf_clk.get("fired_day")
                        _wf_surfaced = isinstance(_wf_fday, int) and any(
                            isinstance(d.get("day"), int)
                            and d.get("day") >= _wf_fday
                            for d in _wf_devs)
                        if not _wf_surfaced:
                            _wf_fired.append(
                                f"\U0001f514 {_wf_label} - fired day "
                                f"{_wf_fday if isinstance(_wf_fday, int) else '?'}, "
                                f"NOT YET SURFACED in fiction -> {_wf_pull}")
                        continue
                    _wf_due_day = _wf_clk.get("due_day")
                    if not isinstance(_wf_due_day, int):
                        continue
                    if _wf_due_day <= _wf_day:
                        _wf_due.append((_wf_due_day,
                                        f"⏳ DUE (day {_wf_due_day}): "
                                        f"{_wf_label} -> {_wf_pull}"))
                    else:
                        _wf_pending.append((_wf_due_day,
                                            f"⏳ {_wf_label} - due day "
                                            f"{_wf_due_day} -> {_wf_pull}"))
                _wf_lines = (_wf_fired
                             + [l for _, l in sorted(_wf_due, key=lambda x: x[0])]
                             + [l for _, l in sorted(_wf_pending, key=lambda x: x[0])])
                if _wf_stale > 0:
                    _wf_lines.append(
                        f"{_wf_stale} thread(s) stale (no development in 14+ "
                        f"days) -> " + _pf.push_call("thread", action="list"))
                if _wf_lines:
                    results.append("=== ⏳ WORLD FORCES (world tick) ===")
                    if _wf_fired:
                        results.append(
                            "(\U0001f514 clears ONLY by surfacing in-fiction, "
                            "then thread(action=\"update\", thread_id=..., "
                            "development=..., development_day=<today>))")
                    results.extend(_wf_lines)
                    results.append("")
    except Exception:
        pass  # Non-critical

    # === 6e-people. WORLD FORCES — people moving on their own (heartbeat spine) ===
    # Surfaced flag flips True when _npc_continuity re-engages the person.
    try:
        _people = _world_forces_people_lines()
        if _people:
            results.append("=== ⏳ WORLD FORCES (people) ===")
            results.append("**People moving on their own:**")
            results.extend(_people)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6e-crossings. WORLD FORCES — tangles (heartbeat crossings, Slice B) ===
    # Engine co-locates seeds that touch the same person/faction; it judges
    # nothing. Silent coexistence is valid -- these are orientation notes only.
    try:
        _tangles = _crossing_briefing_lines()
        if _tangles:
            results.append("=== \U0001f517 WORLD FORCES (tangles) ===")
            results.append("**Tensions that knotted together — you judge valence + volume:**")
            results.extend(_tangles)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6e-threats. ANTAGONIST FORCES — cultivated threats due / active ===
    # The read-back the cultivation store never had (spec 2026-06-18). Engine
    # surfaces; the DM decides. Non-critical.
    try:
        _threats = _antagonist_briefing_lines()
        if _threats:
            results.append("=== ☠ ANTAGONIST FORCES ===")
            results.append("**Cultivated threats due or active — you decide the beat:**")
            results.extend(_threats)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6e-parleys. OPEN PARLEYS (Task 8) — negotiations in progress ===
    # social_system owns the parley records; this reads them back so the DM
    # never opens a session having forgotten a live negotiation. Non-critical.
    try:
        _parleys = _parley_briefing_lines()
        if _parleys:
            results.extend(_parleys)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6f. FACTION STANDINGS (D1, 2026-06-13) ===
    # READ-ONLY briefing of party-level faction REP. Omitted entirely when empty.
    try:
        _fac_data, _fac_err = _load_factions()
        if not _fac_err and isinstance(_fac_data, dict):
            _fac_rows = [(s, r) for s, r in _fac_data.get("factions", {}).items()
                         if isinstance(r, dict)]
            if _fac_rows:
                _fac_rows.sort(key=lambda kv: _faction_clamp(kv[1].get("rep", 0)), reverse=True)
                try:
                    _fac_today = _thread_current_day()
                except Exception:
                    _fac_today = None
                results.append("=== ⚖ FACTION STANDINGS ===")
                for _fs, _fr in _fac_rows:
                    results.append(_faction_line(_fs, _fr))
                    # C4: flag records that may have drifted from play. A faction
                    # untouched for 20+ in-game days while the party has been
                    # dealing with it is a reconcile candidate (the Cacklemaw
                    # accord case: sealed in fiction, never ledgered).
                    if isinstance(_fac_today, int):
                        _fh = [h.get("day") for h in _fr.get("history", [])
                               if isinstance(h, dict) and isinstance(h.get("day"), int)]
                        _flast = max(_fh) if _fh else None
                        if _flast is not None and (_fac_today - _flast) > _FACTION_STALE_DAYS:
                            results.append(
                                f"   ⚠ not updated since day {_flast} "
                                f"({_fac_today - _flast} days) — reconcile if play moved it: "
                                + _pf.push_call("faction", action="status",
                                                name=_fr.get("name", _fs)))
                results.append(_pf.push_call("faction", action="status"))
                results.append("")
    except Exception:
        pass  # Non-critical

    # === 6h. SITE FEATURES (current place) — site-feature persistence ===
    try:
        _sf_lines = _site_features_briefing_lines()
        if _sf_lines:
            results.extend(_sf_lines)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6f-rel. RECENTLY SHIFTED RELATIONSHIPS (C29) ===
    # READ-ONLY briefing of the relationship() TOOL store — pairs whose status
    # changed in the last _REL_RECENT_DAYS in-game days, so an engine-recorded
    # shift (e.g. an alliance breaking) resurfaces at session start even before
    # both entities are present. One line + a pull handle per pair. Omitted when none.
    try:
        _rel_data, _rel_err = _load_relationships()
        if not _rel_err and isinstance(_rel_data, dict):
            try:
                _rel_today = _thread_current_day()
            except Exception:
                _rel_today = None
            _rel_rows = []
            for _rk, _rv in _rel_data.get("relationships", {}).items():
                if not isinstance(_rv, dict):
                    continue
                _rday = _rv.get("last_interaction_day")
                if not isinstance(_rday, int) or _rday <= 0:
                    continue
                if isinstance(_rel_today, int) and (_rel_today - _rday) > _REL_RECENT_DAYS:
                    continue
                _rel_rows.append((_rday, _rk, _rv))
            if _rel_rows:
                _rel_rows.sort(key=lambda t: t[0], reverse=True)
                results.append("=== 🔗 RECENTLY SHIFTED RELATIONSHIPS ===")
                for _rday, _rk, _rv in _rel_rows[:8]:
                    _ents = _rv.get("entities") or _rk.split("|")
                    _e1, _e2 = (_ents + ["?", "?"])[:2]
                    _status = _rv.get("status", "unknown")
                    _handle = "history" if _rv.get("history") else "get"
                    results.append(
                        f"- {_e1} ↔ {_e2} = {_status} (Day {_rday}) — "
                        + _pf.push_call("relationship", action=_handle,
                                        entity1=_e1, entity2=_e2))
                results.append("")
    except Exception:
        pass  # Non-critical

    # === 6g. ACTIVE SITE (site-exploration engine) ===
    # One-line cold-resume cue when a site is mid-exploration. Omitted when none.
    try:
        _site_line = _active_site_briefing_line()
        if _site_line:
            results.append(_site_line)
            results.append("")
    except Exception:
        pass  # Non-critical

    # === 6. LAST SESSION ===
    try:
        continuity_path = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"

        if not continuity_path.exists():
            last_session = "Ã¢Å¡Â Ã¯Â¸Â MASTER_CONTINUITY_CURRENT.md not found"
        else:
            content = continuity_path.read_text(encoding='utf-8')

            pattern = r'## SESSION SAVED - Day \d+[^\n]*\n(.*?)(?=\n---\n|## SESSION SAVED|\Z)'
            matches = list(re.finditer(pattern, content, re.DOTALL))

            if not matches:
                last_session = "Ã¢Å¡Â Ã¯Â¸Â No SESSION SAVED markers found"
            else:
                # Load last 1 session (reduced from 2 for token efficiency)
                sessions_to_load = matches[-1:]
                session_texts = []
                
                for match in sessions_to_load:
                    start = match.start() - 3
                    section_content = content[start:match.end()].strip()
                    
                    header_match = re.search(r'## SESSION SAVED - Day (\d+) \(([^)]+)\)', section_content)
                    if header_match:
                        day_num = header_match.group(1)
                        timestamp = header_match.group(2)
                        session_texts.append(f"**Day {day_num}** ({timestamp}):\n{section_content}")
                    else:
                        session_texts.append(section_content)
                
                last_session = "\n\n---\n\n".join(session_texts)
    except Exception as e:
        last_session = f"Ã¢Å¡Â Ã¯Â¸Â Error loading last session: {str(e)}"

    results.append("=== LAST SESSION ===")
    results.append(last_session)
    results.append("")

    # === 7. VECTOR SEARCH — DEFERRED to check_canon ===
    # check_canon runs progressive tier search with better parameters. ~300 token savings.

    # === 7b. CHARACTER PROFILES — REMOVED ===
    # Redundant with VOICE.md (@-imported) and CLAUDE.md tripwires. ~3k token savings.

    # === 8. CONTEXT RETRIEVAL RULES ===
    results.append("=== CONTEXT RETRIEVAL RULES ===")
    results.append("""1. check_canon(user_input) - Call on EVERY user message. No exceptions.
2. search(action="history") - Deep history, 80+ sessions. "Have we ever..." or "when did we first..."

Never skip #1.""")
    results.append("")

    # === 9. KNOWLEDGE BOUNDARIES — DEFERRED to check_canon ===
    # Identical logic runs in check_canon per-turn. ~150 token savings.

    # Cold-start seam: emit the player view at session start so the statusline,
    # /menu, and dashboard have data from turn 0 — otherwise the artifacts only
    # exist after the first state-changing tool fires (2026-07-06 table report:
    # dashboard showed its empty-state through a whole settlement session).
    try:
        _emit_player_view()
    except Exception:
        pass  # advisory surface — never block session start

    return "\n".join(results)


def ingest_distillations(
    session_id: str = Field(description="Identifier for the current session — used to mark cache entries as ingested."),
    force: bool = Field(default=False, description="Re-post EVERY cached distillation, even ones already marked ingested. Use to rebuild the collection after it has been wiped or recreated (the normal path only posts entries that have never been ingested)."),
) -> str:
    """Reach for this WHEN distill_session has just written new canon nuggets to the cache (session-end Step 7, second call): embed them into the canon_distillations ChromaDB collection, then run reindex_recent.

Ingest distillations from the cache into the canon_distillations ChromaDB collection.

    Called by the session-end subagent in Step 7 (INDEX). Reads
    .canon_distillations.json, embeds the learning text, upserts into ChromaDB,
    and marks each as ingested.

    Normal mode (force=False) posts only entries with ingested_at_session=None.
    Recovery mode (force=True) re-posts ALL entries — use when the collection has
    been emptied/rebuilt while the cache still marks entries as ingested (otherwise
    the normal path sees nothing to do and the collection stays empty).
    """
    try:
        from hooks.distillation_cache import DistillationCache
    except ImportError:
        from distillation_cache import DistillationCache

    cache = DistillationCache(_DISTILLATION_CACHE_PATH)
    # On direct (non-FastMCP) calls the Field default leaks through as a sentinel
    # object, which is truthy. Coerce anything that isn't a real bool to False so
    # the recovery path only fires when force=True is explicitly passed.
    if not isinstance(force, bool):
        force = False
    unposted = cache.all_entries() if force else cache.get_unposted()

    if not unposted:
        return "No unposted distillations to ingest. Collection unchanged."

    collection = get_canon_distillations_collection()
    successes = 0
    failures = []

    logging.info(f"ingest_distillations: processing {len(unposted)} entries")

    # Build the chromadb metadata for one entry. Prefer EXPLICIT fields (v3 nuggets
    # carry accurate type/characters/entities); fall back to the topic_key-split
    # heuristic only for legacy entries that lack them.
    def _dist_meta(entry, topic_key):
        parts = topic_key.split("_")
        suffix = entry.get("type") or (parts[-1] if parts else "")
        characters = entry.get("characters") or (parts[:-1] if parts else [])
        return {
            "topic_key": topic_key,
            "suffix": suffix,
            "type": entry.get("type", suffix),
            "characters": ",".join(characters),
            "entities": ",".join(entry.get("entities", []) or []),
            "arc": entry.get("arc", ""),
            "key_facts_count": len(entry.get("key_facts", []) or []),
            "refined_count": entry.get("refined_count", 1),
            "created_session": entry.get("created_session", "?"),
            "lorebook_mtime": entry.get("verified_against", {}).get("lorebook_mtime", 0),
        }

    # Drop empties, then BATCH-embed (one Ollama /api/embed call per slice) with the
    # DOCUMENT prefix. Stays additive: `unposted` is already only the delta.
    valid = []
    for entry in unposted:
        if (entry.get("learning") or "").strip():
            valid.append(entry)
        else:
            failures.append(f"{entry.get('topic_key', '?')}: empty learning text")

    DIST_BATCH_SIZE = 32
    for i in range(0, len(valid), DIST_BATCH_SIZE):
        batch = valid[i:i + DIST_BATCH_SIZE]
        texts = [e["learning"] for e in batch]
        try:
            embeddings = get_ollama_embeddings_batch(texts, timeout=120.0)
            collection.upsert(
                ids=[e["topic_key"] for e in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[_dist_meta(e, e["topic_key"]) for e in batch],
            )
            for e in batch:
                cache.mark_ingested(e["topic_key"], session_id)
            successes += len(batch)
        except Exception as batch_err:
            # One-at-a-time fallback so a single bad entry can't sink the whole batch.
            logging.warning(f"ingest_distillations: batch failed ({batch_err}); per-entry fallback")
            for e in batch:
                tk = e["topic_key"]
                try:
                    emb = get_ollama_embedding_sync(e["learning"])
                    collection.upsert(ids=[tk], embeddings=[emb],
                                      documents=[e["learning"]], metadatas=[_dist_meta(e, tk)])
                    cache.mark_ingested(tk, session_id)
                    successes += 1
                except Exception as e2:
                    failures.append(f"{tk}: {e2}")

    result_lines = [f"Ingested {successes} distillation(s) into canon_distillations collection."]
    if failures:
        result_lines.append(f"Failures ({len(failures)}):")
        result_lines.extend(f"  - {f}" for f in failures[:5])
    if successes > 0:
        result_lines.append(_pf.next_block(_pf.push_call("reindex_recent"), label="index step 7"))
    return "\n".join(result_lines)


def distill_session(
    action: str = Field(description="'analyze' to scan session text and find stale/candidate entries, or 'write' to create/update distillation entries."),
    session_text: str = Field(default="", description="Session continuity text (for analyze action)."),
    entries: list[dict] = Field(default_factory=list, description="List of distillation entries to write (for write action). Each must have: topic_key, learning, key_facts, source_pointers."),
    session_id: str = Field(default="", description="Session identifier for provenance tracking."),
) -> str:
    """Reach for this WHEN the session-end INDEX step (Step 7) begins: write the reconcile agent's distillation entries into the canon-nugget cache, before ingest_distillations embeds them.

Generate and manage canon distillations at session-end.

    Session-end Step 7 (INDEX): runs first — before ingest_distillations, then reindex_recent.
    The analyze action scans session text and identifies stale/candidate entries.
    The write action validates, deduplicates, and writes entries to the cache.
    """
    if action == "analyze":
        return _distill_analyze(session_text)
    elif action == "write":
        return _distill_write(entries, session_id)
    else:
        return f"ERROR: Unknown action '{action}'. Use 'analyze' or 'write'."


def _crystallize_nudge_block(removed_names, day):
    """Site-feature crystallization nudge (spec:
    2026-07-05-site-feature-persistence-design.md). When items left the
    party's hands this save, push the exact next call so a fresh DM can
    stamp any that stayed in the world. Empty string when nothing removed."""
    if not removed_names:
        return ""
    place = ""
    try:
        gs = json.loads((CAMPAIGN_DIR / "game_state.json").read_text(encoding="utf-8"))
        place = (gs.get("active_location_name") or "").strip()
    except Exception:
        pass
    call = _pf.push_call(
        "update_location_progress",
        location=place if place else _pf.raw('"<current place>"'),
        day=day,
        summary=_pf.raw('"<item> left at <spot>"'),
    )
    return ("🌱 CRYSTALLIZE? Left the party's hands: " + ", ".join(removed_names)
            + ". If any stayed in the world (set down, given, planted), stamp it:\n"
            + _pf.next_block(call))


# --- save-write chain state (Wave 8 slice 3): owned here; confirm_save reassigns it ---
PENDING_SAVE = {
    "token": None,
    "changes": None,  # Dict of file_path -> {"before": str, "after": str, "action": str}
    "params": None,   # Original save_state parameters
    "timestamp": None,
}


def save_state(
    session_summary: str,
    day: int,
    narrative_log: str = "",
    npc_changes: dict = None,
    inventory_changes: list = None,
    new_canon: list = None,
    scene_location: str = "",
    characters_present: str = "",
    last_speaker: str = "",
    last_beat: str = "",
    tension_mood: str = "",
    next_expected: str = "",
    # Arc context (optional - only update if arc changed)
    current_arc: str = "",
    arc_summary: str = "",
    arc_tension: str = "",
    # Emotional states (optional - per-character feelings)
    emotional_states: dict = None,  # {"Mira": "anxious about the verdict", "Odo": "hopeful"}
    # Legacy param kept for compatibility (used for location fallback)
    party_location: str = "",
    preview: bool = False,  # If True, return diff without writing (dry-run)
) -> str:
    """Reach for this WHEN you need the direct/legacy save path (bypassing the two-step review flow) — normally confirm_save() calls this internally; prefer prepare_save_state → confirm_save for user-review saves. NOTE: inventory_changes expects character-roster names; party wealth lives in party.json (the live ledger; owner ruling 2026-07-02 — the lorebook "rations" entry is consumption lore only).

    End-of-session save. Updates scene state, logs narrative, syncs HP. Prefer prepare_save_state() then confirm_save() for user review."""
    from datetime import datetime

    # ========================================
    # 0. PREVIEW MODE CHECK (BEFORE ANY WORK)
    # ========================================
    if preview:
        return prepare_save_state(
            session_summary=session_summary,
            day=day,
            narrative_log=narrative_log,
            npc_changes=npc_changes,
            inventory_changes=inventory_changes,
            new_canon=new_canon,
            scene_location=scene_location,
            characters_present=characters_present,
            last_speaker=last_speaker,
            last_beat=last_beat,
            tension_mood=tension_mood,
            next_expected=next_expected,
            current_arc=current_arc,
            arc_summary=arc_summary,
            arc_tension=arc_tension,
            party_location=party_location,
            emotional_states=emotional_states,
        )

    # ========================================
    # 1. ANTAGONIST CULTIVATION (AFTER PREVIEW CHECK)
    # ========================================
    # Notice threats before writing state
    # Build recent beats list from GAME_STATE
    recent_beats_text = []
    if "session_beats" in GAME_STATE:
        for beat_entry in GAME_STATE["session_beats"][-10:]:  # Last 10 beats
            if isinstance(beat_entry, dict):
                recent_beats_text.append(beat_entry.get("beat", ""))
            else:
                recent_beats_text.append(str(beat_entry))

    # Add current session summary to review context
    if session_summary:
        recent_beats_text.append(session_summary)

    # Review for antagonistic opportunities
    cultivation_review = _review_cultivation(
        recent_beats=recent_beats_text,
        current_day=day,
        session_summary=session_summary
    )

    # Load current cultivation file
    cult_content = _load_cultivation()

    # Check for time travel (day going backward)
    last_day_match = re.search(r'Last updated: Day (\d+)', cult_content)
    skip_cultivation = False
    if last_day_match:
        last_day = int(last_day_match.group(1))
        if day < last_day:
            _safe_print(f"WARNING: Time travel detected - Day {day} < last cultivation day {last_day}. Skipping cultivation update.")
            skip_cultivation = True

    if not skip_cultivation:
        # Normal cultivation flow follows...

            # Ensure all required sections exist
        required_sections = [
            ("## ACTIVE THREATS", "## ACTIVE THREATS\n*Things currently in motion, escalating*\n[None yet]\n"),
            ("## DORMANT SEEDS", "## DORMANT SEEDS\n*Resentments, mistakes, vulnerabilities not yet active*\n[None yet]\n"),
            ("## ESCALATION LOG", "## ESCALATION LOG\n[None yet]\n"),
            ("## OPPORTUNITIES", "## OPPORTUNITIES\n*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*\n[None yet]\n"),
            ("## PRUNING LOG", "## PRUNING LOG\n[None yet]\n"),
        ]

        for section_header, section_template in required_sections:
            if section_header not in cult_content:
                _safe_print(f"WARNING: {section_header} section missing, recreating...")
                # Append to end
                cult_content += "\n" + section_template

        # Update "Last updated" timestamp
        cult_content = re.sub(
            r'Last updated: Day \d+',
            f'Last updated: Day {day}',
            cult_content
        )

        # Append opportunities to OPPORTUNITIES section
        if cultivation_review["opportunities"]:
            # Find OPPORTUNITIES section
            opps_match = re.search(
                r'(## OPPORTUNITIES.*?\n)(.*?)(?=\n## |$)',
                cult_content,
                re.DOTALL
            )

            if opps_match:
                section_header = opps_match.group(1)
                existing_content = opps_match.group(2).strip()

                # Build new opportunities list (terse, one line per)
                new_opps = "\n".join([f"- Day {day}: {opp}" for opp in cultivation_review["opportunities"]])

                # Replace section
                if existing_content == "[None yet]":
                    new_content = new_opps
                else:
                    new_content = existing_content + "\n" + new_opps

                cult_content = cult_content[:opps_match.start()] + \
                              section_header + "\n" + new_content + "\n" + \
                              cult_content[opps_match.end():]
            else:
                _safe_print(f"WARNING: OPPORTUNITIES section not found in cultivation file")

        # Handle prunes (remove from DORMANT SEEDS)
        if cultivation_review["prunes"]:
            for seed_name in cultivation_review["prunes"]:
                # Find and remove this seed's section
                seed_pattern = rf'### {re.escape(seed_name)} - Day planted: \d+\n.*?(?=\n### |\n## |$)'
                cult_content = re.sub(seed_pattern, '', cult_content, flags=re.DOTALL)

                # TASK 8: Also remove from ESCALATION LOG
                escalation_pattern = rf'Day \d+: .*?{re.escape(seed_name)}.*?\n'
                cult_content = re.sub(escalation_pattern, '', cult_content, flags=re.MULTILINE)

                # Log in PRUNING LOG
                prune_match = re.search(
                    r'(## PRUNING LOG.*?\n)(.*?)(?=\n## |$)',
                    cult_content,
                    re.DOTALL
                )
                if prune_match:
                    prune_header = prune_match.group(1)
                    prune_existing = prune_match.group(2).strip()

                    prune_entry = f"- Day {day}: Pruned '{seed_name}' (20+ days dormant)"

                    if prune_existing == "[None yet]":
                        new_prune_content = prune_entry
                    else:
                        new_prune_content = prune_existing + "\n" + prune_entry

                    cult_content = cult_content[:prune_match.start()] + \
                                  prune_header + "\n" + new_prune_content + "\n" + \
                                  cult_content[prune_match.end():]
                else:
                    _safe_print(f"WARNING: PRUNING LOG section not found in cultivation file")

        # Enforce token budget (keep file under 2000 tokens ~6500 chars with safety margin)
        if len(cult_content) > 6500:
            # Truncate oldest opportunities (keep last 8 complete days)
            opps_match = re.search(
                r'(## OPPORTUNITIES.*?\n)(.*?)(?=\n## |$)',
                cult_content,
                re.DOTALL
            )
            if opps_match:
                opps_lines = opps_match.group(2).strip().split('\n')
                if len(opps_lines) > 20:  # Increased threshold from 15 to 20
                    # TASK 10: Group opportunities by day to preserve complete day context
                    day_groups = {}
                    for line in opps_lines:
                        if line.strip() and line.startswith("- Day "):
                            try:
                                day_num = int(line.split("Day ")[1].split(":")[0])
                                if day_num not in day_groups:
                                    day_groups[day_num] = []
                                day_groups[day_num].append(line)
                            except (IndexError, ValueError):
                                # Malformed line, put in special bucket
                                if -1 not in day_groups:
                                    day_groups[-1] = []
                                day_groups[-1].append(line)

                    # Keep last 8 complete days
                    sorted_days = sorted([d for d in day_groups.keys() if d >= 0])[-8:]
                    truncated_lines = []
                    for day in sorted_days:
                        truncated_lines.extend(day_groups[day])

                    # Include any malformed lines at the end
                    if -1 in day_groups:
                        truncated_lines.extend(day_groups[-1])

                    truncated = '\n'.join(truncated_lines)
                    cult_content = cult_content[:opps_match.start()] + \
                                  opps_match.group(1) + "\n" + truncated + "\n" + \
                                  cult_content[opps_match.end():]

        # Save updated cultivation file
        _save_cultivation(cult_content)

    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # ========================================
    # 1. MASTER_CONTINUITY_CURRENT.md - Narrative Log
    # ========================================
    if narrative_log:
        try:
            continuity_path = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"
            
            if continuity_path.exists():
                continuity_content = continuity_path.read_text(encoding='utf-8')
            else:
                continuity_content = "# MASTER CONTINUITY - CURRENT\
\
"
            
            # Build session block
            session_block = f"""
---

## SESSION SAVED - Day {day} ({timestamp})

{narrative_log}

---
"""
            # Append to file
            continuity_content = continuity_content.rstrip() + "\
" + session_block
            # Atomic + crash-safe: this is the append-of-record continuity log;
            # a truncate-then-write crash would lose the ENTIRE accumulated file.
            _atomic_text_write(continuity_path, continuity_content)
            
            results.append(f"Ã¢Å“â€¦ MASTER_CONTINUITY_CURRENT.md - Narrative logged (Day {day})")
        except Exception as e:
            results.append(f"Ã¢Å¡Â Ã¯Â¸Â MASTER_CONTINUITY_CURRENT.md failed: {str(e)}")
    else:
        results.append("Ã¢ÂÂ­Ã¯Â¸Â MASTER_CONTINUITY_CURRENT.md - No narrative provided, skipped")
    
    # ========================================
    # 1.5 ChromaDB - Index session for semantic search (TIERED)
    # ========================================
    if narrative_log and len(narrative_log.strip()) > 50:
        try:
            from datetime import datetime as dt

            # Build metadata for tiered chunking
            chunk_metadata = {
                "day": day,
                "arc": current_arc or "current",
                "characters": characters_present or "",
                "scene_type": _infer_scene_type(narrative_log),
                "timestamp": dt.now().strftime('%Y-%m-%d')
            }

            # Generate tiered chunks (150, 300, 800, 3000 chars with parent linking)
            session_id = f"session_day_{day}"
            chunks = chunk_text_tiered(
                text=narrative_log,
                metadata=chunk_metadata,
                session_id=session_id
            )

            if chunks:
                # Index to tiered collection
                collection = get_chroma_collection("campaign_history_tiered")

                indexed_count = 0
                failed_count = 0
                last_error = None
                tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
                BATCH_SIZE = 32

                for batch_start in range(0, len(chunks), BATCH_SIZE):
                    batch = chunks[batch_start:batch_start + BATCH_SIZE]
                    try:
                        embed_texts = [c.get("embedding_text", c["text"]) for c in batch]
                        embeddings = get_ollama_embeddings_batch(embed_texts, timeout=120.0)
                        collection.add(
                            ids=[c["id"] for c in batch],
                            embeddings=embeddings,
                            documents=[c["text"] for c in batch],
                            metadatas=[_stringify_metadata(c["metadata"]) for c in batch]
                        )
                        for c in batch:
                            indexed_count += 1
                            tier_counts[c["metadata"]["tier"]] += 1
                    except Exception as batch_err:
                        # Batch failed — fall back to one-by-one for this batch
                        for chunk in batch:
                            try:
                                embed_text = chunk.get("embedding_text", chunk["text"])
                                embedding = get_ollama_embedding_sync(embed_text, timeout=60.0)
                                collection.add(
                                    ids=[chunk["id"]],
                                    embeddings=[embedding],
                                    documents=[chunk["text"]],
                                    metadatas=[_stringify_metadata(chunk["metadata"])]
                                )
                                indexed_count += 1
                                tier_counts[chunk["metadata"]["tier"]] += 1
                            except Exception as chunk_err:
                                failed_count += 1
                                last_error = str(chunk_err)

                # Report with tier breakdown
                if indexed_count > 0:
                    tier_summary = ", ".join([f"T{t}={c}" for t, c in tier_counts.items() if c > 0])
                    if failed_count > 0:
                        results.append(f"ChromaDB - Indexed {indexed_count}/{indexed_count + failed_count} chunks ({tier_summary}) - {failed_count} failed: {last_error}")
                    else:
                        results.append(f"ChromaDB - Indexed {indexed_count} chunks for Day {day} ({tier_summary})")
                else:
                    results.append(f"ChromaDB - No chunks indexed ({failed_count} failures, last error: {last_error})")
            else:
                results.append("ChromaDB - Narrative too short to chunk")

        except Exception as e:
            results.append(f"ChromaDB indexing failed: {str(e)}")
    # ========================================
    # 2. CURRENT_STATUS.md - Update SCENE STATE section
    # ========================================
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        status_content = status_path.read_text(encoding='utf-8')
        # Normalize line endings to prevent \r\n regex mismatch
        status_content = status_content.replace('\r\n', '\n').replace('\r', '\n')

        # Update day in header
        status_content = re.sub(
            r'# CURRENT STATUS - DAY \d+',
            f'# CURRENT STATUS - DAY {day}',
            status_content
        )

        # Update Last Updated timestamp
        status_content = re.sub(
            r'\*\*Last Updated:\*\* [^\
]+',
            f'**Last Updated:** {timestamp}',
            status_content
        )

        # Build new SCENE STATE section
        # Only update fields that were provided
        scene_updates = []

        # Always update Day
        scene_updates.append(f"**Day:** {day}")

        if scene_location or party_location:
            scene_updates.append(f"**Location:** {scene_location or party_location}")

        if characters_present:
            scene_updates.append(f"**Present:** {characters_present}")

        # Get existing Last 3 Beats if not replacing
        if last_beat:
            # Read current beats, shift them, add new one as #3
            beats_match = re.search(r'\*\*Last 3 Beats:\*\*\s*\
((?:\d+\.\s*.+\
?)+)', status_content)
            if beats_match:
                old_beats = beats_match.group(1).strip().split('\n')
                # Take beats 2 and 3 (now become 1 and 2), add new as 3
                new_beats = []
                for i, beat in enumerate(old_beats[1:3]):  # Skip first, take next two
                    # Renumber
                    beat_text = re.sub(r'^\d+\.\s*', '', beat.strip())
                    new_beats.append(f"{i+1}. {beat_text}")
                new_beats.append(f"3. {last_beat}")
                scene_updates.append("**Last 3 Beats:**")
                scene_updates.extend(new_beats)
            else:
                scene_updates.append("**Last 3 Beats:**")
                scene_updates.append(f"1. {last_beat}")

        if last_speaker:
            scene_updates.append(f"**Last Speaker:** {last_speaker}")

        if tension_mood:
            scene_updates.append(f"**Tension/Mood:** {tension_mood}")

        if next_expected:
            scene_updates.append(f"**Next Expected:** {next_expected}")

        # Replace SCENE STATE section if we have updates
        if len(scene_updates) > 1:  # More than just the day
            new_scene_state = "## SCENE STATE (check_canon reads this section)\n\n" + "\n".join(scene_updates) + "\n"

            # Find and replace existing SCENE STATE section
            scene_pattern = r'## SCENE STATE \(check_canon reads this section\).*?(?=\
---\
|\
## [A-Z]|\Z)'
            if re.search(scene_pattern, status_content, re.DOTALL):
                status_content = re.sub(scene_pattern, new_scene_state.rstrip(), status_content, flags=re.DOTALL)
                results.append("SCENE STATE section updated")
            else:
                results.append("SCENE STATE section not found (structure may need repair)")

        # Update ARC CONTEXT if provided (consolidated to CURRENT_STATUS.md - single source of truth)
        if current_arc or arc_summary or arc_tension:
            arc_lines = []
            if current_arc:
                arc_lines.append(f"**Current Arc:** {current_arc}")
            if arc_summary:
                arc_lines.append(f"**Arc Summary:** {arc_summary}")
            if arc_tension:
                arc_lines.append(f"**Arc Tension:** {arc_tension}")

            if arc_lines:
                new_arc_content = "## ARC CONTEXT\n\n" + "\n".join(arc_lines) + "\n"
                arc_pattern = r'## ARC CONTEXT.*?(?=\
---\
|\
## [A-Z]|\Z)'
                if re.search(arc_pattern, status_content, re.DOTALL):
                    # Replace existing section
                    status_content = re.sub(arc_pattern, new_arc_content.rstrip(), status_content, flags=re.DOTALL)
                    results.append("ARC CONTEXT section updated in CURRENT_STATUS.md")
                else:
                    # Insert after SCENE STATE section (before first ---)
                    first_divider = status_content.find('\
---\
')
                    if first_divider > 0:
                        status_content = status_content[:first_divider] + "\n\n" + new_arc_content + status_content[first_divider:]
                        results.append("ARC CONTEXT section added to CURRENT_STATUS.md")
                    else:
                        status_content += "\n\n" + new_arc_content
                        results.append("ARC CONTEXT section appended to CURRENT_STATUS.md")


        # Update EMOTIONAL STATE if provided
        if emotional_states:
            # Build emotional state table
            emo_lines = ["## EMOTIONAL STATE", ""]
            emo_lines.append("| Character | Current State |")
            emo_lines.append("|-----------|---------------|")
            for char_name, state in emotional_states.items():
                emo_lines.append(f"| {char_name} | {state} |")
            emo_lines.append("")
            new_emo_section = "\n".join(emo_lines)

            # Check if EMOTIONAL STATE section already exists
            emo_pattern = r'## EMOTIONAL STATE.*?(?=\
---\
|\
## [A-Z]|\Z)'
            if re.search(emo_pattern, status_content, re.DOTALL):
                # Replace existing section
                status_content = re.sub(emo_pattern, new_emo_section.rstrip(), status_content, flags=re.DOTALL)
                results.append("EMOTIONAL STATE section updated in CURRENT_STATUS.md")
            else:
                # Insert after ARC CONTEXT section or SCENE STATE (before first ---)
                arc_end = status_content.find('\
## ARC CONTEXT')
                if arc_end > 0:
                    # Find the end of ARC CONTEXT section
                    arc_section_end = status_content.find('\
---\
', arc_end)
                    if arc_section_end > 0:
                        status_content = status_content[:arc_section_end] + "\n\n" + new_emo_section + status_content[arc_section_end:]
                    else:
                        first_divider = status_content.find('\
---\
')
                        if first_divider > 0:
                            status_content = status_content[:first_divider] + "\n\n" + new_emo_section + status_content[first_divider:]
                        else:
                            status_content += "\n\n" + new_emo_section
                else:
                    first_divider = status_content.find('\
---\
')
                    if first_divider > 0:
                        status_content = status_content[:first_divider] + "\n\n" + new_emo_section + status_content[first_divider:]
                    else:
                        status_content += "\n\n" + new_emo_section
                results.append("EMOTIONAL STATE section added to CURRENT_STATUS.md")

        # --- HP Sync (characters.json -> same in-memory status_content) ---
        try:
            # Load character data (split-file-first pattern)
            chars_dir = CAMPAIGN_DIR / "characters"
            meta_path = chars_dir / "_meta.json"

            hp_char_data = None
            if chars_dir.exists() and meta_path.exists():
                # Use split file structure - glob all character files
                hp_char_data = {'characters': {}}
                for p in sorted(chars_dir.glob("*.json")):
                    if p.name == "_meta.json":
                        continue
                    with open(p, 'r', encoding='utf-8') as f:
                        hp_char_data['characters'][p.stem] = json.load(f)

            if hp_char_data is None:
                # Split sheets are the sole source; monolithic fallback retired.
                hp_char_data = {'characters': {}}

            char_mapping = {}
            for json_key, char_info in hp_char_data.get('characters', {}).items():
                display_name = char_info.get('name', json_key.capitalize())
                char_mapping[display_name] = json_key

            hp_synced = 0
            hp_section_match = re.search(
                r'(## PARTY HP STATUS.*?\n\|[^\n]+\|\n\|[-\s|]+\|\n)(.*?)(\n\*|\n---|\Z)',
                status_content,
                re.DOTALL
            )

            if hp_section_match:
                hp_header = hp_section_match.group(1)
                hp_rows = hp_section_match.group(2)
                hp_suffix = hp_section_match.group(3)

                for display_name, json_key in char_mapping.items():
                    if json_key in hp_char_data['characters']:
                        hp_info = hp_char_data['characters'][json_key]
                        if 'hp' in hp_info:
                            current_hp = hp_info['hp']['current']
                            max_hp = hp_info['hp']['max']
                            row_pattern = rf"(\|\s*{re.escape(display_name)}\s*\|)\s*[^\|]+\s*(\|)\s*[^\|]+\s*(\|[^\|]+\|)"
                            replacement = rf"\g<1> {current_hp} \g<2> {max_hp} \g<3>"
                            if re.search(row_pattern, hp_rows):
                                hp_rows = re.sub(row_pattern, replacement, hp_rows)
                                hp_synced += 1

                new_hp_section = hp_header + hp_rows + hp_suffix
                status_content = (
                    status_content[:hp_section_match.start()] +
                    new_hp_section +
                    status_content[hp_section_match.end():]
                )
            results.append(f"[OK] HP synced from split files ({hp_synced} characters)")
        except Exception as e:
            results.append(f"[WARN] HP sync failed: {str(e)}")

        # --- Legacy section cleanup (same in-memory status_content) ---
        if "## SCENE CONTEXT" in status_content:
            status_content = re.sub(
                r'\n*## SCENE CONTEXT \(for session resumption\).*?(?=\n## [A-Z]|\Z)',
                '',
                status_content,
                flags=re.DOTALL
            )
            results.append("Cleaned up legacy SCENE CONTEXT section")

        if "## IMMEDIATE STATUS" in status_content:
            status_content = re.sub(
                r'\n*## IMMEDIATE STATUS.*?(?=\n## [A-Z]|\Z)',
                '',
                status_content,
                flags=re.DOTALL
            )
            results.append("Cleaned up legacy IMMEDIATE STATUS section")

        # --- Single write to disk ---
        # Normalize line endings before write
        status_content = status_content.replace('\r\n', '\n').replace('\r', '\n')
        # Atomic + crash-safe (C22): a truncate-then-write crash could otherwise
        # destroy the live status file mid-save.
        _atomic_text_write(status_path, status_content)
        results.append(f"CURRENT_STATUS.md saved (Day {day})")
    except Exception as e:
        results.append(f"Ã¢Å¡Â Ã¯Â¸Â CURRENT_STATUS.md failed: {str(e)}")
    
    # ========================================
    # 3. NPC_ROSTER.md - Relationship Updates
    # ========================================
    if npc_changes:
        try:
            npc_path = CAMPAIGN_DIR / "NPC_ROSTER.md"
            npc_content = npc_path.read_text(encoding='utf-8')
            
            npcs_updated = []
            npcs_not_found = []
            
            for npc_name, change_description in npc_changes.items():
                # Try to find NPC section (case-insensitive)
                npc_pattern = rf'(###?\s*{re.escape(npc_name)}[^\
]*\
)'
                match = re.search(npc_pattern, npc_content, re.IGNORECASE)
                
                if match:
                    # Find the end of this NPC's section
                    section_start = match.end()
                    next_section = re.search(r'\
###?\s', npc_content[section_start:])
                    
                    if next_section:
                        insert_point = section_start + next_section.start()
                    else:
                        insert_point = len(npc_content)
                    
                    # Insert update note
                    update_note = f"\
**Day {day} Update:** {change_description}\
"
                    npc_content = npc_content[:insert_point] + update_note + npc_content[insert_point:]
                    npcs_updated.append(npc_name)
                else:
                    npcs_not_found.append(npc_name)
            
            npc_path.write_text(npc_content, encoding='utf-8')
            
            if npcs_updated:
                results.append(f"Ã¢Å“â€¦ NPC_ROSTER.md - Updated: {', '.join(npcs_updated)}")
            if npcs_not_found:
                results.append(f"Ã¢Å¡Â Ã¯Â¸Â NPC_ROSTER.md - Not found: {', '.join(npcs_not_found)}")
        except Exception as e:
            results.append(f"Ã¢Å¡Â Ã¯Â¸Â NPC_ROSTER.md failed: {str(e)}")
    
    # ========================================
    # 4. lorebook.json - New Canon
    # ========================================
    lorebook_merge_pushes = []  # C15: hoisted so the summary always surfaces it
    if new_canon:
        try:
            lorebook_path = CAMPAIGN_DIR / "lorebook.json"

            if lorebook_path.exists():
                with open(lorebook_path, 'r', encoding='utf-8') as f:
                    lorebook = json.load(f)
            else:
                lorebook = {"meta": {"version": 1, "last_updated": "", "description": "Keyword-triggered context injection"}, "entries": []}

            entries_added = []
            entries_skipped = []
            entries_rejected = []
            merge_pushes = lorebook_merge_pushes  # C15: fresh context skipped as a dup -> push the merge call

            # Build existing keyword set once (not per-entry), plus a map to the
            # existing entry so a skipped keyword can surface its CURRENT context.
            existing_keywords = set()
            existing_by_kw = {}
            for entry in lorebook.get("entries", []):
                for kw in entry.get("keywords", []):
                    existing_keywords.add(kw.lower())
                    existing_by_kw.setdefault(kw.lower(), entry)

            for entry_data in new_canon:
                if not isinstance(entry_data, dict):
                    # Contract violation, NOT a duplicate — DROPPED, never crystallized.
                    entries_rejected.append(str(entry_data)[:60])
                    continue
                keywords = [k.strip().lower() for k in entry_data.get("keywords", "").split(",")]

                # Per-keyword dedup: keep novel keywords, skip duplicates
                novel_keywords = [kw for kw in keywords if kw not in existing_keywords]
                skipped_keywords = [kw for kw in keywords if kw in existing_keywords]

                if skipped_keywords:
                    entries_skipped.append(f"{skipped_keywords[0]} (keyword exists)")
                    # If the WHOLE entry was a dup (no novel keyword), the fresh
                    # context was about to evaporate — push the exact merge call.
                    if not novel_keywords:
                        _sk = skipped_keywords[0]
                        merge_pushes.append(_lorebook_merge_push(
                            _sk,
                            existing_by_kw.get(_sk, {}).get("context", ""),
                            entry_data.get("context", "")))

                if not novel_keywords:
                    continue

                new_entry = {
                    "keywords": novel_keywords,
                    "category": entry_data.get("category", "context").lower(),
                    "status": entry_data.get("status", "ESTABLISHED").upper(),
                    "context": entry_data.get("context", ""),
                    "source": f"session_day_{day}"
                }

                lorebook["entries"].append(new_entry)
                entries_added.append(novel_keywords[0])

                # Track novel keywords so subsequent entries detect them
                existing_keywords.update(novel_keywords)
            
            lorebook["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            
            _atomic_json_write(lorebook_path, lorebook)
            
            if entries_added:
                results.append(f"Ã¢Å“â€¦ lorebook.json - Added: {', '.join(entries_added)}")
            if entries_skipped:
                results.append(f"Ã¢ÂÂ­Ã¯Â¸Â lorebook.json - Skipped (duplicate keyword): {', '.join(entries_skipped)}")
            if entries_rejected:
                results.append(
                    f"!! lorebook.json - REJECTED {len(entries_rejected)} malformed new_canon "
                    f"entr{'y' if len(entries_rejected) == 1 else 'ies'} (NOT crystallized): "
                    f"{'; '.join(entries_rejected)} -- new_canon needs dicts "
                    f"{{keywords, category, status, context}}, not strings; fix the reconcile output."
                )
        except Exception as e:
            results.append(f"Ã¢Å¡Â Ã¯Â¸Â lorebook.json failed: {str(e)}")
    
    # ========================================
    
    # ========================================
    # 5. INVENTORY CHANGES (characters.json)
    # ========================================
    _removed_item_names = []
    if inventory_changes:
        try:
            inv_results = _apply_inventory_changes(inventory_changes, day)
            _removed_item_names = [
                # rsplit: the LAST " from " is the separator — item names
                # themselves may contain " from " ("Letter from Yam").
                r[len("REMOVED: "):].rsplit(" from ", 1)[0]
                for r in inv_results if r.startswith("REMOVED: ")
            ]
            for r in inv_results:
                if r.startswith("ERROR") or r.startswith("REJECTED") or r.startswith("SKIP") or r.startswith("NOT FOUND"):
                    results.append(f"[WARN] {r}")
                else:
                    results.append(f"[OK] {r}")
        except Exception as e:
            results.append(f"[WARN] Inventory changes failed: {str(e)}")
    
    # ========================================
    # 9. SYNC campaign_day to JSON files
    # ========================================
    try:
        # Sync day to character metadata (split-file-first pattern)
        chars_dir = CAMPAIGN_DIR / "characters"
        meta_path = chars_dir / "_meta.json"

        if chars_dir.exists() and meta_path.exists():
            # Split sheets are authoritative; only _meta.json carries the campaign day.
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = json.load(f)
            meta_data['campaign_day'] = day
            meta_data['last_updated'] = timestamp.split()[0]  # Just the date
            _atomic_json_write(meta_path, meta_data)
            results.append(f"✓ characters/_meta.json synced to Day {day}")
        else:
            results.append("⚠️ character split sheets (characters/_meta.json) not found; day not synced")
    except Exception as e:
        results.append(f"⚠️ character day sync failed: {str(e)}")

    try:
        # Sync party.json
        party_path = CAMPAIGN_DIR / "party.json"
        if party_path.exists():
            with open(party_path, 'r', encoding='utf-8') as f:
                party_data = json.load(f)
            party_data['meta']['campaign_day'] = day
            party_data['meta']['last_updated'] = timestamp.split()[0]
            _atomic_json_write(party_path, party_data)
            results.append(f"✓ party.json synced to Day {day}")
    except Exception as e:
        results.append(f"⚠️ party.json sync failed: {str(e)}")

    try:
        # Sync narrative_threads.json meta
        threads_path = CAMPAIGN_DIR / "narrative_threads.json"
        if threads_path.exists():
            threads_data = _load_cached_json(threads_path, 'threads')
            threads_data['meta']['last_updated'] = timestamp.split()[0]
            _atomic_json_write(threads_path, threads_data)
            results.append("✓ narrative_threads.json timestamp updated")
    except Exception as e:
        results.append(f"⚠️ narrative_threads.json sync failed: {str(e)}")

    try:
        # Sync npc_states.json meta
        npc_path = CAMPAIGN_DIR / "npc_states.json"
        if npc_path.exists():
            with open(npc_path, 'r', encoding='utf-8') as f:
                npc_data = json.load(f)
            npc_data['meta']['last_updated'] = timestamp.split()[0]
            _atomic_json_write(npc_path, npc_data)
            results.append("✓ npc_states.json timestamp updated")
    except Exception as e:
        results.append(f"⚠️ npc_states.json sync failed: {str(e)}")

    # ========================================
    # 10. Wealth Verification
    # ========================================
    try:
        status_content = (CAMPAIGN_DIR / "CURRENT_STATUS.md").read_text(encoding='utf-8')
        wealth_match = re.search(r'[Ww]ealth.*?(\d[\d,]*)\s+tokens', status_content)
        if wealth_match:
            results.append(f"Ã¢Å“â€¦ Wealth verified: {wealth_match.group(1)} tokens")
        else:
            results.append("Ã¢Å¡Â Ã¯Â¸Â Could not verify wealth in CURRENT_STATUS")
    except Exception as e:
        results.append(f"Ã¢Å¡Â Ã¯Â¸Â Wealth verification failed: {str(e)}")
    
    # ========================================
    # KNOWLEDGE BOUNDARY CHECK
    # ========================================
    # Check if any NPCs with knowledge_boundary entries were present
    boundary_reminder = ""
    if characters_present:
        try:
            lorebook_path = CAMPAIGN_DIR / "lorebook.json"
            if lorebook_path.exists():
                with open(lorebook_path, 'r', encoding='utf-8') as f:
                    lorebook = json.load(f)

                present_names = [name.strip().lower() for name in characters_present.split(',')]
                npcs_with_boundaries = []

                for entry in lorebook.get("entries", []):
                    if entry.get("category") == "knowledge_boundary":
                        entry_keywords = [kw.lower() for kw in entry.get("keywords", [])]
                        for present_name in present_names:
                            if any(present_name in kw or kw in present_name for kw in entry_keywords):
                                # Extract NPC name from context (first word after "KNOWLEDGE BOUNDARY - ")
                                context = entry.get("context", "")
                                if "KNOWLEDGE BOUNDARY - " in context:
                                    npc_name = context.split("KNOWLEDGE BOUNDARY - ")[1].split(":")[0]
                                    npcs_with_boundaries.append(npc_name)
                                break

                if npcs_with_boundaries:
                    boundary_reminder = f"""
{'='*60}
KNOWLEDGE BOUNDARY CHECK
{'='*60}
The following NPCs with knowledge boundaries were present this session:
{', '.join(npcs_with_boundaries)}

Did any secrets get revealed to them? If yes, update their lorebook entry:
  update_lorebook_entry(keyword="[npc_name]", field="context", new_value="[updated boundary]")

DM SECRETS: Did any *_PREP.md content get revealed through play?
If plot elements were discovered, they're now player knowledge - no update needed.
{'='*60}
"""
        except Exception:
            pass  # Non-critical, continue without reminder

    # ========================================
    # FINAL SUMMARY (compact format for token efficiency)
    # ========================================
    # Filter to only show errors and key successes
    key_results = [r for r in results if '✓' in r or 'WARN' in r or 'failed' in r or 'ERROR' in r or 'REJECTED' in r]

    # Count successes and failures
    success_count = sum(1 for r in results if '✓' in r or '[OK]' in r or 'updated' in r.lower() or 'synced' in r.lower())
    warn_count = sum(1 for r in results if 'WARN' in r or 'failed' in r.lower() or 'ERROR' in r or 'REJECTED' in r)

    summary = f"**Day {day} saved** | {success_count} ops OK"
    if warn_count > 0:
        summary += f" | {warn_count} warnings"

    # Only include boundary reminder if NPCs were detected
    if boundary_reminder and 'present this session' in boundary_reminder:
        summary += f"\n{boundary_reminder}"

    # For debugging, include full results only if there were issues
    if warn_count > 0:
        summary += "\n\nDetails:\n" + "\n".join(key_results)

    # C15: a new-canon fact skipped as a duplicate keyword would otherwise
    # evaporate — always surface the merge push so the session-end agent can
    # reconcile it, regardless of warn_count.
    if lorebook_merge_pushes:
        summary += ("\n\nlorebook.json — fresh context skipped (keyword exists); "
                    "merge it, don't lose it:\n" + "\n".join(lorebook_merge_pushes))

    try:
        _nudge = _crystallize_nudge_block(_removed_item_names, day)
        if _nudge:
            summary += "\n\n" + _nudge
    except Exception:
        pass  # nudge is advisory — never fail the save

    _emit_player_view()
    return summary


def prepare_save_state(
    session_summary: str,
    day: int,
    narrative_log: str = "",
    npc_changes: dict = None,
    inventory_changes: list = None,
    new_canon: list = None,
    scene_location: str = "",
    characters_present: str = "",
    last_speaker: str = "",
    last_beat: str = "",
    tension_mood: str = "",
    next_expected: str = "",
    current_arc: str = "",
    arc_summary: str = "",
    arc_tension: str = "",
    party_location: str = "",
    emotional_states: dict = None,  # NEW: {"Mira": "anxious about the verdict", "Odo": "hopeful"}
    force_day: bool = False,  # Bypass day-regression guard. Required if caller-day is >2 below meta.
) -> str:
    """Reach for this WHEN a session ends and you are ready to save: STEP 1 of 2 — builds the diff and returns a token for user review; PostToolUse verify_save hook fires here; call confirm_save(token) after user approves.

    Preview save_state changes without writing. Returns diff and confirmation token (valid 10 min). Pass token to confirm_save() to commit."""
    global PENDING_SAVE
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    changes = {}

    # ========================================
    # 0. INPUT SANITIZATION + DAY GUARD (defends against caller pollution)
    # See: _sanitize_param helper above. Pre-fix bug: LLM agent embedded
    # MCP tool-call envelope XML into parameter VALUES; server wrote them verbatim.
    # ========================================
    _audit_log(
        f"prepare_save_state IN: day={day!r} session_summary[:80]={(session_summary or '')[:80]!r} "
        f"tension_mood[:80]={(tension_mood or '')[:80]!r} arc_summary[:80]={(arc_summary or '')[:80]!r} "
        f"emotional_states_type={type(emotional_states).__name__}"
    )

    # Sanitize every string parameter
    session_summary = _sanitize_param(session_summary)
    narrative_log = _sanitize_param(narrative_log)
    scene_location = _sanitize_param(scene_location)
    characters_present = _sanitize_param(characters_present)
    last_speaker = _sanitize_param(last_speaker)
    last_beat = _sanitize_param(last_beat)
    tension_mood = _sanitize_param(tension_mood)
    next_expected = _sanitize_param(next_expected)
    current_arc = _sanitize_param(current_arc)
    arc_summary = _sanitize_param(arc_summary)
    arc_tension = _sanitize_param(arc_tension)
    party_location = _sanitize_param(party_location)
    emotional_states = _sanitize_emotional_states(emotional_states)

    # Day cross-check — block silent regression. The Day 121 stamping bug
    # was the caller passing day=121 because Phase 2.5 reconciliation read a
    # stale CURRENT_STATUS.md header. Refuse to commit a day that's >2 below meta
    # unless the caller explicitly asserts force_day=True.
    meta_day = _resolve_meta_day()
    if meta_day is not None and not force_day:
        try:
            day_int = int(day)
        except (TypeError, ValueError):
            return (
                f"ERROR: prepare_save_state received non-integer day={day!r}. "
                f"Day must be an int. Re-call get_current_day() and pass the integer result."
            )
        if day_int < meta_day - 2:
            _audit_log(f"BLOCK: caller day={day_int} is {meta_day - day_int} below meta day={meta_day}")
            return (
                f"ERROR: prepare_save_state was called with day={day_int}, but CURRENT_STATUS.md "
                f"header shows DAY {meta_day}. Day-regression guard blocked the save to prevent "
                f"the Day 121 header bug. Likely cause: Phase 2.5 reconciliation did not run, or "
                f"get_current_day() was not re-called after advance_day().\n\n"
                f"To proceed: re-run Phase 2.5 reconciliation, call get_current_day() to get the "
                f"correct current day, and re-call prepare_save_state with that day. "
                f"If you genuinely intend a backdated save, pass force_day=True (rare — backups only)."
            )

    # ========================================
    # 1. MASTER_CONTINUITY_CURRENT.md preview
    # ========================================
    if narrative_log:
        try:
            continuity_path = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"
            before = continuity_path.read_text(encoding='utf-8') if continuity_path.exists() else ""

            session_block = f"""
---

## SESSION SAVED - Day {day} ({timestamp})

{narrative_log}

---
"""
            after = before.rstrip() + "\n" + session_block
            changes["MASTER_CONTINUITY_CURRENT.md"] = {
                "before": before,
                "after": after,
                "action": "APPEND narrative log",
                "diff": _compute_diff(before[-2000:] if len(before) > 2000 else before, after[-2000:])  # Show tail
            }
        except Exception as e:
            changes["MASTER_CONTINUITY_CURRENT.md"] = {"error": str(e)}

    # ========================================
    # 2. CURRENT_STATUS.md preview
    # ========================================
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        before = status_path.read_text(encoding='utf-8')
        after = before
        # Normalize line endings to prevent \r\n regex mismatch
        after = after.replace('\r\n', '\n').replace('\r', '\n')

        # Update day in header
        after = re.sub(r'# CURRENT STATUS - DAY \d+', f'# CURRENT STATUS - DAY {day}', after)

        # Update Last Updated
        after = re.sub(r'\*\*Last Updated:\*\* [^\n]+', f'**Last Updated:** {timestamp}', after)

        # Build SCENE STATE updates
        if any([scene_location, party_location, characters_present, last_beat, last_speaker, tension_mood, next_expected]):
            scene_updates = [f"**Day:** {day}"]

            if scene_location or party_location:
                scene_updates.append(f"**Location:** {scene_location or party_location}")
            if characters_present:
                scene_updates.append(f"**Present:** {characters_present}")

            # Handle Last 3 Beats
            if last_beat:
                beats_match = re.search(r'\*\*Last 3 Beats:\*\*\s*\n((?:\d+\.\s*.+\n?)+)', after)
                if beats_match:
                    old_beats = beats_match.group(1).strip().split('\n')
                    new_beats = []
                    for i, beat in enumerate(old_beats[1:3]):
                        beat_text = re.sub(r'^\d+\.\s*', '', beat.strip())
                        new_beats.append(f"{i+1}. {beat_text}")
                    new_beats.append(f"3. {last_beat}")
                    scene_updates.append("**Last 3 Beats:**")
                    scene_updates.extend(new_beats)
                else:
                    scene_updates.append("**Last 3 Beats:**")
                    scene_updates.append(f"1. {last_beat}")

            if last_speaker:
                scene_updates.append(f"**Last Speaker:** {last_speaker}")
            if tension_mood:
                scene_updates.append(f"**Tension/Mood:** {tension_mood}")
            if next_expected:
                scene_updates.append(f"**Next Expected:** {next_expected}")

            # MANAGED BLOCK (audit 2026-06-07, ruling #5): SCENE STATE is rebuilt
            # WHOLESALE from the known fields assembled above. Any stray field hand-
            # written into this block is DROPPED here by design (the regex below
            # replaces the whole block). Durable data that must survive a save MUST
            # live in its OWN '## ...' section (e.g. ## ACTIVE SCENE), which the
            # boundary regex (stops at the next '---' or '## CAPS') leaves intact.
            # Locked by tests/test_save_load_roundtrip.py::test_scene_state_managed_block_drops_stray_fields
            new_scene_state = "## SCENE STATE (check_canon reads this section)\n\n" + "\n".join(scene_updates) + "\n"
            scene_pattern = r'## SCENE STATE \(check_canon reads this section\).*?(?=\n---\n|\n## [A-Z]|\Z)'
            if re.search(scene_pattern, after, re.DOTALL):
                after = re.sub(scene_pattern, new_scene_state.rstrip(), after, flags=re.DOTALL)

        changes["CURRENT_STATUS.md"] = {
            "before": before,
            "after": after,
            "action": "UPDATE scene state",
            "diff": _compute_diff(before, after)
        }
    except Exception as e:
        changes["CURRENT_STATUS.md"] = {"error": str(e)}

    # ========================================
    # 2b. ARC CONTEXT in CURRENT_STATUS.md (consolidated - no longer uses arc_context.md)
    # ========================================
    if current_arc or arc_summary or arc_tension:
        arc_lines = []
        if current_arc:
            arc_lines.append(f"**Current Arc:** {current_arc}")
        if arc_summary:
            arc_lines.append(f"**Arc Summary:** {arc_summary}")
        if arc_tension:
            arc_lines.append(f"**Arc Tension:** {arc_tension}")

        if arc_lines:
            new_arc_section = "## ARC CONTEXT\n\n" + "\n".join(arc_lines) + "\n"
            # Update the 'after' content for CURRENT_STATUS.md with arc context
            if "CURRENT_STATUS.md" in changes and "after" in changes["CURRENT_STATUS.md"]:
                current_after = changes["CURRENT_STATUS.md"]["after"]
                # Check if ARC CONTEXT section already exists
                arc_pattern = r'## ARC CONTEXT.*?(?=\n---\n|\n## [A-Z]|\Z)'
                if re.search(arc_pattern, current_after, re.DOTALL):
                    # Replace existing section
                    current_after = re.sub(arc_pattern, new_arc_section.rstrip(), current_after, flags=re.DOTALL)
                else:
                    # Insert after SCENE STATE section (before first ---)
                    first_divider = current_after.find('\n---\n')
                    if first_divider > 0:
                        current_after = current_after[:first_divider] + "\n\n" + new_arc_section + current_after[first_divider:]
                    else:
                        current_after += "\n\n" + new_arc_section
                changes["CURRENT_STATUS.md"]["after"] = current_after
                changes["CURRENT_STATUS.md"]["action"] = "UPDATE scene state + arc context"
                changes["CURRENT_STATUS.md"]["diff"] = _compute_diff(changes["CURRENT_STATUS.md"]["before"], current_after)

    # ========================================
    # 2c. EMOTIONAL STATE preview in CURRENT_STATUS.md
    # ========================================
    if emotional_states:
        # Build emotional state table
        emo_lines = ["## EMOTIONAL STATE", ""]
        emo_lines.append("| Character | Current State |")
        emo_lines.append("|-----------|---------------|")
        for char_name, state in emotional_states.items():
            emo_lines.append(f"| {char_name} | {state} |")
        emo_lines.append("")
        new_emo_section = "\n".join(emo_lines)

        # Update the 'after' content for CURRENT_STATUS.md with emotional states
        if "CURRENT_STATUS.md" in changes and "after" in changes["CURRENT_STATUS.md"]:
            current_after = changes["CURRENT_STATUS.md"]["after"]
            emo_pattern = r'## EMOTIONAL STATE.*?(?=\n---\n|\n## [A-Z]|\Z)'
            if re.search(emo_pattern, current_after, re.DOTALL):
                # Replace existing section
                current_after = re.sub(emo_pattern, new_emo_section.rstrip(), current_after, flags=re.DOTALL)
            else:
                # Insert after ARC CONTEXT or SCENE STATE
                arc_end = current_after.find('\n## ARC CONTEXT')
                if arc_end > 0:
                    arc_section_end = current_after.find('\n---\n', arc_end)
                    if arc_section_end > 0:
                        current_after = current_after[:arc_section_end] + "\n\n" + new_emo_section + current_after[arc_section_end:]
                    else:
                        first_divider = current_after.find('\n---\n')
                        if first_divider > 0:
                            current_after = current_after[:first_divider] + "\n\n" + new_emo_section + current_after[first_divider:]
                        else:
                            current_after += "\n\n" + new_emo_section
                else:
                    first_divider = current_after.find('\n---\n')
                    if first_divider > 0:
                        current_after = current_after[:first_divider] + "\n\n" + new_emo_section + current_after[first_divider:]
                    else:
                        current_after += "\n\n" + new_emo_section
            changes["CURRENT_STATUS.md"]["after"] = current_after
            changes["CURRENT_STATUS.md"]["action"] = "UPDATE scene state + arc + emotional"
            changes["CURRENT_STATUS.md"]["diff"] = _compute_diff(changes["CURRENT_STATUS.md"]["before"], current_after)

# 3. lorebook.json preview (new_canon)
    # ========================================
    if new_canon:
        try:
            lorebook_path = CAMPAIGN_DIR / "lorebook.json"
            with open(lorebook_path, 'r', encoding='utf-8') as f:
                before_data = json.load(f)

            after_data = json.loads(json.dumps(before_data))  # Deep copy
            entries_to_add = []
            entries_skipped = []
            entries_rejected = []
            merge_pushes = []  # C15: fresh context skipped as a dup -> push the merge call

            existing_keywords = set()
            existing_by_kw = {}
            for entry in after_data.get("entries", []):
                for kw in entry.get("keywords", []):
                    existing_keywords.add(kw.lower())
                    existing_by_kw.setdefault(kw.lower(), entry)

            for entry_data in new_canon:
                if not isinstance(entry_data, dict):
                    # Contract violation, NOT a duplicate: new_canon must be dicts
                    # {keywords, category, status, context}. These entries are
                    # DROPPED and never reach lorebook.json — surface it loudly.
                    entries_rejected.append(str(entry_data)[:60])
                    continue
                keywords = [k.strip().lower() for k in entry_data.get("keywords", "").split(",")]

                _dups = [kw for kw in keywords if kw in existing_keywords]
                if _dups:
                    entries_skipped.append(keywords[0] if keywords else "unknown")
                    # Whole entry is a dup — its fresh context would evaporate.
                    merge_pushes.append(_lorebook_merge_push(
                        _dups[0],
                        existing_by_kw.get(_dups[0], {}).get("context", ""),
                        entry_data.get("context", "")))
                    continue

                new_entry = {
                    "keywords": keywords,
                    "category": entry_data.get("category", "context").lower(),
                    "status": entry_data.get("status", "ESTABLISHED").upper(),
                    "context": entry_data.get("context", ""),
                    "source": f"session_day_{day}"
                }
                after_data["entries"].append(new_entry)
                entries_to_add.append(keywords[0] if keywords else "unknown")

            after_data["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

            # Create readable diff
            diff_text = []
            if entries_to_add:
                diff_text.append(f"  + Adding entries: {', '.join(entries_to_add)}")
            if entries_skipped:
                diff_text.append(f"  ~ Skipping (duplicate keyword): {', '.join(entries_skipped)}")
            for _mp in merge_pushes:
                diff_text.append(_mp)
            if entries_rejected:
                diff_text.append(
                    f"  !! REJECTED {len(entries_rejected)} malformed new_canon entr"
                    f"{'y' if len(entries_rejected) == 1 else 'ies'} — these will NOT reach "
                    f"lorebook.json. new_canon must be dicts {{keywords, category, status, "
                    f"context}}, not strings; fix the reconcile output. Dropped: "
                    f"{'; '.join(entries_rejected)}"
                )

            changes["lorebook.json"] = {
                "before": json.dumps(before_data, indent=2),
                "after": json.dumps(after_data, indent=2),
                "action": f"ADD {len(entries_to_add)} entries",
                "diff": '\
'.join(diff_text) if diff_text else "(no changes)"
            }
        except Exception as e:
            changes["lorebook.json"] = {"error": str(e)}

    # ========================================
    # 4. NPC_ROSTER.md preview (npc_changes)
    # ========================================
    if npc_changes:
        try:
            npc_path = CAMPAIGN_DIR / "NPC_ROSTER.md"
            before = npc_path.read_text(encoding='utf-8')
            after = before

            diff_text = []
            for npc_name, change_description in npc_changes.items():
                npc_pattern = rf'(###?\s*{re.escape(npc_name)}[^\
]*\
)'
                match = re.search(npc_pattern, after, re.IGNORECASE)

                if match:
                    section_start = match.end()
                    next_section = re.search(r'\
###?\s', after[section_start:])
                    insert_point = section_start + next_section.start() if next_section else len(after)

                    update_note = f"\
**Day {day} Update:** {change_description}\
"
                    after = after[:insert_point] + update_note + after[insert_point:]
                    diff_text.append(f"  + {npc_name}: {change_description[:60]}...")
                else:
                    diff_text.append(f"  ! {npc_name}: NOT FOUND in roster")

            changes["NPC_ROSTER.md"] = {
                "before": before,
                "after": after,
                "action": f"UPDATE {len(npc_changes)} NPCs",
                "diff": '\
'.join(diff_text)
            }
        except Exception as e:
            changes["NPC_ROSTER.md"] = {"error": str(e)}

    # ========================================
    # 5. INVENTORY CHANGES preview (character split sheets)
    # ========================================
    if inventory_changes:
        try:
            inv_preview = []
            for change in inventory_changes:
                char_name = change.get("character", "?")
                action = change.get("action", "add")
                if action == "add":
                    item = change.get("item", {})
                    item_name = item.get("name", item.get("id", "?"))
                    slots = item.get("slots", 1)
                    inv_preview.append(f"  + {char_name}: ADD {item_name} ({slots} slot(s))")
                elif action == "remove":
                    item_id = change.get("item_id", "?")
                    inv_preview.append(f"  - {char_name}: REMOVE {item_id}")
            
            changes["character sheets (inventory)"] = {
                "action": f"MODIFY {len(inventory_changes)} items",
                "diff": '\
'.join(inv_preview) if inv_preview else "(no changes)"
            }
        except Exception as e:
            changes["character sheets (inventory)"] = {"error": str(e)}

    # ========================================
    # 6. JSON sync preview (party.json, etc.)
    # ========================================
    # Note: the character day bump now lives in characters/_meta.json (flat schema);
    # it's surfaced via the party.json row below and the actual sync results, not here.
    json_files = ["party.json", "narrative_threads.json", "npc_states.json"]
    for json_file in json_files:
        try:
            json_path = CAMPAIGN_DIR / json_file
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    before_data = json.load(f)

                after_data = json.loads(json.dumps(before_data))
                if 'meta' in after_data:
                    if json_file in ["party.json"]:
                        after_data['meta']['campaign_day'] = day
                    after_data['meta']['last_updated'] = timestamp.split()[0]

                changes[json_file] = {
                    "before": json.dumps(before_data.get('meta', {}), indent=2),
                    "after": json.dumps(after_data.get('meta', {}), indent=2),
                    "action": "SYNC meta timestamp/day",
                    "diff": f"  campaign_day: {before_data.get('meta', {}).get('campaign_day', '?')} → {day}\
  last_updated: {before_data.get('meta', {}).get('last_updated', '?')} → {timestamp.split()[0]}"
                }
        except Exception as e:
            changes[json_file] = {"error": str(e)}

    # ========================================
    # Generate confirmation token and store pending state
    # ========================================
    token = _generate_save_token()
    PENDING_SAVE["token"] = token
    PENDING_SAVE["changes"] = changes
    PENDING_SAVE["params"] = {
        "session_summary": session_summary,
        "day": day,
        "narrative_log": narrative_log,
        "npc_changes": npc_changes,
        "inventory_changes": inventory_changes,
        "new_canon": new_canon,
        "scene_location": scene_location,
        "characters_present": characters_present,
        "last_speaker": last_speaker,
        "last_beat": last_beat,
        "tension_mood": tension_mood,
        "next_expected": next_expected,
        "current_arc": current_arc,
        "arc_summary": arc_summary,
        "arc_tension": arc_tension,
        "party_location": party_location,
        "emotional_states": emotional_states,  # NEW
    }
    PENDING_SAVE["timestamp"] = datetime.now()

    # ========================================
    # Format output
    # ========================================
    output = []
    output.append("=" * 60)
    output.append(f"SAVE STATE PREVIEW - Day {day}")
    output.append("=" * 60)
    output.append("")
    output.append(f"Session Summary: {session_summary}")
    output.append("")

    for file_name, change_data in changes.items():
        output.append(f"### {file_name}")
        if "error" in change_data:
            output.append(f"  ERROR: {change_data['error']}")
        else:
            output.append(f"  Action: {change_data.get('action', 'update')}")
            output.append(f"  Changes:")
            output.append(change_data.get('diff', '(no diff computed)'))
        output.append("")

    # Add ChromaDB indexing notice if narrative_log will trigger it
    if narrative_log and len(narrative_log.strip()) > 50:
        output.append("### ChromaDB Semantic Indexing")
        output.append("  Action: INDEX narrative for semantic search")
        output.append(f"  Estimated chunks: {max(1, len(narrative_log) // 1200)}")
        output.append("  (This enables conversation_search to find this session later)")
        output.append("")

    output.append("=" * 60)
    output.append(f"CONFIRMATION TOKEN: {token}")
    output.append("=" * 60)
    output.append("")
    output.append(_pf.next_block(_pf.push_call("confirm_save", token=token), label="commit save — after user approves"))
    output.append("To make corrections: call prepare_save_state() again with corrected params")
    output.append("Token expires in 10 minutes.")

    return '\n'.join(output)


def confirm_save(token: str) -> str:
    """Reach for this WHEN the user has approved the diff from prepare_save_state: STEP 2 of 2 — pass the token here and the save commits; do not call without prior prepare_save_state approval.

    Commit a prepared save after user approval.

    Args:
        token: The confirmation token from prepare_save_state()

    Returns: Save result (same as save_state would return)
    """
    global PENDING_SAVE
    from datetime import datetime

    # Validate token
    if PENDING_SAVE["token"] is None:
        return "ERROR: No pending save. Call prepare_save_state() first."

    if PENDING_SAVE["token"] != token:
        return f"ERROR: Invalid token. Expected '{PENDING_SAVE['token']}', got '{token}'"

    # Check expiration (10 minutes)
    if PENDING_SAVE["timestamp"]:
        age_seconds = (datetime.now() - PENDING_SAVE["timestamp"]).total_seconds()
        if age_seconds > 600:
            PENDING_SAVE = {"token": None, "changes": None, "params": None, "timestamp": None}
            return "ERROR: Token expired (>10 minutes). Call prepare_save_state() again."

    # Execute the save with stored parameters
    params = PENDING_SAVE["params"]

    # Clear pending state BEFORE executing (prevent double-commit)
    PENDING_SAVE = {"token": None, "changes": None, "params": None, "timestamp": None}

    # Evolve the prose blacklist from this session's catches (fail-safe side-effect).
    _evolve_prose_blacklist_safe()

    # Call the actual save_state with bypass flag
    _save_result = save_state(
        session_summary=params["session_summary"],
        day=params["day"],
        narrative_log=params["narrative_log"],
        npc_changes=params["npc_changes"],
        inventory_changes=params["inventory_changes"],
        new_canon=params["new_canon"],
        scene_location=params["scene_location"],
        characters_present=params["characters_present"],
        last_speaker=params["last_speaker"],
        last_beat=params["last_beat"],
        tension_mood=params["tension_mood"],
        next_expected=params["next_expected"],
        current_arc=params["current_arc"],
        arc_summary=params["arc_summary"],
        arc_tension=params["arc_tension"],
        party_location=params["party_location"],
        emotional_states=params.get("emotional_states"),  # NEW
    )
    # Session-end Step 6->7 kickoff: a committed save is the trigger for the INDEX
    # step. Name it in-band so a post-compaction DM is pulled forward even if the
    # session-end skill's checklist was dropped during compaction.
    if not _save_result.lstrip().startswith("ERROR"):
        _save_result += "\n\n" + _pf.next_block(_pf.push_call(
            "distill_session", action="write",
            entries=_pf.raw("<facts.distillation_entries>"),
            session_id=_pf.raw("<facts.session_id>")),
            label="index step 7")
    return _save_result


_INJECTED = ('CAMPAIGN_DIR', 'GAME_STATE', 'THREADS_FILE', '_DISTILLATION_CACHE_PATH', '_active_site_briefing_line', '_apply_inventory_changes', '_atomic_json_write', '_atomic_text_write', '_audit_log', '_build_prose_observer_summary', '_compute_diff', '_distill_analyze', '_distill_write', '_emit_player_view', '_evolve_prose_blacklist_safe', '_faction_clamp', '_faction_line', '_generate_save_token', '_get_tool_tags', '_infer_scene_type', '_load_cached_json', '_load_cultivation', '_load_factions', '_load_relationships', '_load_threads', '_lorebook_merge_push', '_pf', '_read_current_status_day', '_resolve_meta_day', '_review_cultivation', '_safe_print', '_sanitize_emotional_states', '_sanitize_param', '_save_cultivation', '_stringify_metadata', '_thread_current_day', '_world_forces_people_lines', '_crossing_briefing_lines', '_antagonist_briefing_lines', '_parley_briefing_lines', '_startup_prep_scream_lines', 'chunk_text_tiered', 'get_canon_distillations_collection', 'get_chroma_collection', 'get_ollama_embedding_sync', 'get_ollama_embeddings_batch', 'read_file', 'rulebook_system')


def register_session_tools(mcp, srv):
    """Inject server-resident deps, then register the moved tools.

    Called once from server.py at module load, after every injected symbol is
    defined. Tool names are preserved (mcp.tool()(fn) uses fn.__name__).
    """
    g = globals()
    for _name in _INJECTED:
        g[_name] = getattr(srv, _name)
    mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags=_get_tool_tags("load_last_session"),
    )(load_last_session)
    mcp.tool()(verify_session_save)
    mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags=_get_tool_tags("full_session_startup"),
    )(full_session_startup)
    mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": True},
        tags=_get_tool_tags("ingest_distillations"),
    )(ingest_distillations)
    mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": False},
        tags=_get_tool_tags("distill_session"),
    )(distill_session)
    mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": False},
        tags=_get_tool_tags("save_state"),
    )(save_state)
    mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags=_get_tool_tags("prepare_save_state"),
    )(prepare_save_state)
    mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": False},
        tags=_get_tool_tags("confirm_save"),
    )(confirm_save)
