"""Task 10 Fix Batch 2 — push audit: save chain + Step-7 index chain + prep-validation pushes.

Six findings:
  7. validate_campaign_state: NEXT (fix drift): sync_campaign_day() ONLY when DAY DRIFT in issues
  8. prepare_save_state: NEXT (commit save): confirm_save(token="<literal-token>")
  9. verify_session_save pass 1 PASS: NEXT (save): prepare_save_state(session_summary=..., day=<n>)
     (session_summary + day are REQUIRED params — the push must be valid on copy-paste)
 10. _distill_write success: NEXT (index step 7): ingest_distillations(session_id="<id>")
     (session_id is REQUIRED — empty input coerces to "unknown" and is always rendered)
 11. ingest_distillations success (count>0): NEXT (index step 7): reindex_recent()
 12. validate_prep_file PASS path: NEXT (load prep): map(action="init", map_name="<derived>", prep_file="<file>")
     (map_name is REQUIRED by map() — derived from the prep filename)

Negative cases:
  7-: no drift in issues → old "Run `sync_campaign_day()`" prose is GONE; no NEXT advisory at all
  9-: pass 2 → no prepare_save_state push
  9-: pass 1 FAIL → no prepare_save_state push
 11-: zero ingested → no reindex_recent push
 12-: FAIL/warnings only → no map push
 10-: missing session_id → push renders session_id="unknown" (never "None"/"")
"""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import server
import session_tools
import push_format as _pf


# ============================================================
# Helpers shared across findings
# ============================================================

def _stub_batch_embed(monkeypatch):
    """Make the batch embedder return one 768-vector per input text."""
    def fake_batch(texts, timeout=120.0):
        return [[0.1] * 768 for _ in texts]
    monkeypatch.setattr(server, "get_ollama_embeddings_batch", fake_batch)
    monkeypatch.setattr(session_tools, "get_ollama_embeddings_batch", server.get_ollama_embeddings_batch)  # Wave 8 fault-line twin


# ============================================================
# Finding 7: validate_campaign_state — conditional drift advisory
# ============================================================

_FULL_STATUS_MD = """\
# CURRENT STATUS - DAY {day}

**Last Updated:** 2026-01-01 00:00

---

## SCENE STATE

**Day:** {day}
**Location:** The Tessik Well
**Present:** Roscar, Vela

**Last 3 Beats:**
1. Entered the well.
2. Fought a Cacogen.
3. Found a cache.

**Next Expected:** Descent to level 2.

---

## PHOTOSYNTHESIS

**Last Fed:** Day {day}
**Due:** Day {next_feed}

---

## ACTIVE THREADS

*None active.*

---
"""


def _seed_validate_dir(tmp_path, char_day, party_day, current_day):
    """Build minimal campaign structure for validate_campaign_state."""
    next_feed = current_day + 3
    (tmp_path / "CURRENT_STATUS.md").write_text(
        _FULL_STATUS_MD.format(day=current_day, next_feed=next_feed),
        encoding="utf-8",
    )

    # characters.json — the monolithic format that validate_campaign_state reads
    (tmp_path / "characters.json").write_text(
        json.dumps({"meta": {"campaign_day": char_day}}), encoding="utf-8"
    )
    # party.json — meta.campaign_day
    (tmp_path / "party.json").write_text(
        json.dumps({"meta": {"campaign_day": party_day}}), encoding="utf-8"
    )


def test_validate_campaign_state_with_drift_has_sync_push(monkeypatch, tmp_path):
    """When issues contains a DAY DRIFT entry, output must carry
    NEXT (fix drift): sync_campaign_day().
    Drift threshold is abs(diff) > 2, so char_day=45 vs current=50 triggers it."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", server.CAMPAIGN_DIR)  # Wave 8 fault-line twin
    _seed_validate_dir(tmp_path, char_day=45, party_day=45, current_day=50)

    out = server.validate_campaign_state()

    assert "DAY DRIFT" in out
    assert _pf.push_call("sync_campaign_day") in out
    assert "NEXT" in out
    assert "fix drift" in out


def test_validate_campaign_state_no_drift_no_sync_push(monkeypatch, tmp_path):
    """When no day drift is detected, the old unconditional advisory is GONE
    and there is no NEXT sync advisory at all."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", server.CAMPAIGN_DIR)  # Wave 8 fault-line twin
    _seed_validate_dir(tmp_path, char_day=50, party_day=50, current_day=50)

    out = server.validate_campaign_state()

    # Old unconditional prose must be gone
    assert "Run `sync_campaign_day()" not in out
    # No push advisory at all
    assert "sync_campaign_day" not in out
    assert "NEXT" not in out


# ============================================================
# Finding 8: prepare_save_state — push_format token round-trip
# ============================================================

def _seed_prepare_dir(campaign_dir):
    """Seed the minimal campaign dir for prepare_save_state."""
    chars_dir = campaign_dir / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    char = {"name": "Roscar", "level": 3,
            "xp": {"current": 0, "needed": 3},
            "hp": {"current": 18, "max": 20}}
    (chars_dir / "roscar.json").write_text(
        json.dumps(char, indent=2), encoding="utf-8"
    )
    (chars_dir / "_meta.json").write_text(
        json.dumps({"version": 1, "campaign_day": 50, "system": "Vaults of Vaarn"}),
        encoding="utf-8",
    )
    status = campaign_dir / "CURRENT_STATUS.md"
    if not status.exists():
        status.write_text(
            "# CURRENT STATUS - DAY 50\n"
            "**Day:** 50\n"
            "**Location:** Test Location\n"
            "**Present:** Roscar\n",
            encoding="utf-8",
        )
    cont = campaign_dir / "MASTER_CONTINUITY_CURRENT.md"
    if not cont.exists():
        cont.write_text("# MASTER CONTINUITY - CURRENT SESSION\n\n", encoding="utf-8")


def test_prepare_save_state_token_in_push(isolate_campaign_dir):
    """The push in prepare_save_state output must carry the LITERAL runtime token
    and NOT the old prose 'To commit these changes: confirm_save(token=...'."""
    _seed_prepare_dir(Path(server.CAMPAIGN_DIR))

    out = server.prepare_save_state(
        session_summary="Batch 2 push test.",
        day=50,
        scene_location="Test Location",
    )

    # Token is 8 hex chars
    m = re.search(r"CONFIRMATION TOKEN:\s*([0-9a-f]{8})", out)
    assert m, f"No CONFIRMATION TOKEN in output:\n{out}"
    token = m.group(1)

    # The push must carry the literal token
    assert f'confirm_save(token="{token}")' in out
    assert "NEXT" in out
    assert "commit save" in out

    # Output must be NEWLINE-joined (the old backslash-continuation join fused
    # every line into one wall of text) — the push must sit on its own line.
    assert '\nNEXT (' in out

    # Old prose must be gone
    assert "To commit these changes:" not in out

    # Token in push must match PENDING_SAVE
    assert session_tools.PENDING_SAVE["token"] == token


def test_prepare_save_state_push_token_matches_pending_save(isolate_campaign_dir):
    """The token shown in the push call equals the one stored in PENDING_SAVE."""
    _seed_prepare_dir(Path(server.CAMPAIGN_DIR))

    out = server.prepare_save_state(
        session_summary="Token round-trip check.",
        day=50,
        scene_location="Test Location",
    )

    m = re.search(r'confirm_save\(token="([0-9a-f]{8})"\)', out)
    assert m, f"No pushed confirm_save token in output:\n{out}"
    pushed_token = m.group(1)

    assert pushed_token == session_tools.PENDING_SAVE["token"], (
        f"Pushed token {pushed_token!r} does not match "
        f"PENDING_SAVE token {session_tools.PENDING_SAVE['token']!r}"
    )


# ============================================================
# Finding 9: verify_session_save — pass 1 PASS only
# ============================================================

def _make_verify_report(overall_ok=True, pass_number=1, checks=None, vital_signs=None):
    """Stub report dict as returned by run_verification."""
    report = {
        "overall_ok": overall_ok,
        "checks": checks or [{"ok": True, "target": "facts_file", "detail": "present"}],
    }
    if vital_signs:
        report["vital_signs"] = vital_signs
    return report


def _patch_verify_session_save(monkeypatch, tmp_path, report):
    """Patch all the internals verify_session_save needs so we can control the report."""
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"day": 50}), encoding="utf-8")

    monkeypatch.setattr(server, "_read_current_status_day", lambda: "50")
    monkeypatch.setattr(session_tools, "_read_current_status_day", lambda: "50")  # Wave 8: verify_session_save reads it from session_tools

    # run_verification is imported locally inside verify_session_save from
    # hooks.session_verify — patch the module attribute there.
    try:
        import hooks.session_verify as _sv
        monkeypatch.setattr(_sv, "run_verification", lambda *a, **kw: report)
    except ImportError:
        import session_verify as _sv
        monkeypatch.setattr(_sv, "run_verification", lambda *a, **kw: report)

    # FabricationBans and DistillationCache are also imported locally — stub them
    try:
        import hooks.fabrication_bans as _fb
        monkeypatch.setattr(_fb, "FabricationBans",
                            lambda path: MagicMock())
    except ImportError:
        pass
    try:
        import hooks.distillation_cache as _dc
        monkeypatch.setattr(_dc, "DistillationCache",
                            lambda path: MagicMock())
    except ImportError:
        pass

    return facts


def test_verify_session_save_pass1_pass_has_prepare_save_push(tmp_path, monkeypatch):
    """Pass 1 PASS must append a VALID prepare_save_state push carrying the
    REQUIRED params: session_summary (placeholder) + day (the literal current day)."""
    facts = _patch_verify_session_save(
        monkeypatch, tmp_path, _make_verify_report(overall_ok=True)
    )
    out = server.verify_session_save(facts_path=str(facts), pass_number=1)

    assert 'prepare_save_state(session_summary="<2-3 sentence summary>", day=50)' in out
    assert "NEXT (save):" in out


def test_verify_session_save_pass2_no_prepare_save_push(tmp_path, monkeypatch):
    """Pass 2 must NOT have a prepare_save_state push."""
    facts = _patch_verify_session_save(
        monkeypatch, tmp_path, _make_verify_report(overall_ok=True)
    )
    out = server.verify_session_save(facts_path=str(facts), pass_number=2)

    assert 'prepare_save_state(' not in out
    assert "NEXT (save):" not in out


def test_verify_session_save_pass1_fail_no_prepare_save_push(tmp_path, monkeypatch):
    """Pass 1 FAIL must NOT have a prepare_save_state push."""
    facts = _patch_verify_session_save(
        monkeypatch, tmp_path, _make_verify_report(overall_ok=False)
    )
    out = server.verify_session_save(facts_path=str(facts), pass_number=1)

    assert 'prepare_save_state(' not in out
    assert "NEXT (save):" not in out


# ============================================================
# Finding 10: _distill_write — ingest_distillations push
# ============================================================

def _make_minimal_cache(tmp_path):
    """Create a minimal canon distillations cache for _distill_write tests."""
    cache_path = tmp_path / ".canon_distillations.json"
    cache_path.write_text(json.dumps({"schema_version": 1, "distillations": {}}))
    return cache_path


def test_distill_write_with_session_id_pushes_ingest(tmp_path, monkeypatch):
    """_distill_write with a real session_id must push
    NEXT (index step 7): ingest_distillations(session_id="<id>")."""
    cache_path = _make_minimal_cache(tmp_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    # Disable Ollama overlap check to avoid network call
    monkeypatch.setattr(server, "check_ollama_health", lambda: False)

    entries = [{
        "topic_key": "test_entry",
        "learning": "The Chromatic Wound glows at night.",
        "key_facts": ["glow fact"],
        "source_pointers": ["session-50"],
    }]
    out = server._distill_write(entries, session_id="session-50")

    assert 'ingest_distillations(session_id="session-50")' in out
    assert "NEXT" in out
    assert "index step 7" in out


def test_distill_write_missing_session_id_push_no_equals_none(tmp_path, monkeypatch):
    """_distill_write coerces an empty session_id to "unknown" — the push must
    carry session_id="unknown" (the param is REQUIRED on ingest_distillations)
    and MUST NOT render session_id="None" or session_id=""."""
    cache_path = _make_minimal_cache(tmp_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    monkeypatch.setattr(server, "check_ollama_health", lambda: False)

    entries = [{
        "topic_key": "test_entry2",
        "learning": "Another fact about the Wound.",
        "key_facts": ["fact"],
        "source_pointers": [],
    }]
    # Pass empty session_id — _distill_write coerces it to "unknown"
    out = server._distill_write(entries, session_id="")

    # The push must render the coerced session_id (valid call, never bounces)
    assert 'ingest_distillations(session_id="unknown")' in out
    assert "NEXT" in out
    # Must NOT render session_id="None" or an empty value
    assert 'session_id="None"' not in out
    assert 'session_id=""' not in out


# ============================================================
# Finding 11: ingest_distillations — reindex_recent push
# ============================================================

def _make_cache_with_unposted(tmp_path):
    cache_path = tmp_path / ".canon_distillations.json"
    data = {
        "schema_version": 1,
        "distillations": {
            "test_nugget": {
                "topic_key": "test_nugget",
                "learning": "The Chromatic Wound is ancient.",
                "key_facts": ["ancient"],
                "source_pointers": [],
                "verified_against": {},
                "created_turn": 1, "created_session": "s1",
                "refined_turn": 1, "refined_count": 1,
                "ingested_at_session": None,
            }
        },
    }
    cache_path.write_text(json.dumps(data))
    return cache_path


def test_ingest_distillations_success_pushes_reindex(tmp_path, monkeypatch):
    """When at least one distillation is ingested, output must carry
    NEXT (index step 7): reindex_recent()."""
    cache_path = _make_cache_with_unposted(tmp_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin
    _stub_batch_embed(monkeypatch)

    out = server.ingest_distillations(session_id="s_test")

    assert 'reindex_recent()' in out
    assert "NEXT" in out
    assert "index step 7" in out


def test_ingest_distillations_zero_count_no_reindex_push(tmp_path, monkeypatch):
    """When the cache is empty (nothing ingested), NO reindex_recent push."""
    cache_path = tmp_path / ".canon_distillations.json"
    cache_path.write_text(json.dumps({"schema_version": 1, "distillations": {}}))
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin
    _stub_batch_embed(monkeypatch)

    out = server.ingest_distillations(session_id="s_test")

    # No push when count == 0
    assert 'reindex_recent()' not in out
    # Nothing was ingested
    assert mock_coll.upsert.call_count == 0


# ============================================================
# Finding 12: validate_prep_file — PASS path map push
# ============================================================

# Minimal valid prep file content (schema fields that pass validation)
_VALID_PREP_CONTENT = """\
# TEST_PREP.md

## ROOMS

### ROOM: entrance
- **Name:** The Entrance
- **Floor:** 1
- **Description:** A dusty entrance hall.
- **Exits:** office
- **dm_only:** Nothing hidden here.

### ROOM: office
- **Name:** The Office
- **Floor:** 1
- **Description:** A cluttered office.
- **Exits:** entrance
- **dm_only:** Secret lever behind the desk.
"""

_VALID_PREP_DATA = {
    "rooms": {
        "entrance": {"name": "The Entrance", "floor": 1,
                     "description": "A dusty entrance hall.", "exits": ["office"]},
        "office": {"name": "The Office", "floor": 1,
                   "description": "A cluttered office.", "exits": ["entrance"]},
    },
    "secrets": {},
    "raw_content": _VALID_PREP_CONTENT,
}


def test_validate_prep_file_pass_has_map_push(monkeypatch, tmp_path):
    """PASS path must append a VALID map push: map() REQUIRES map_name, so the
    push carries map_name derived from the filename (TEST_PREP.md -> "test")."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", server.CAMPAIGN_DIR)  # Wave 8 fault-line twin

    prep_file = "TEST_PREP.md"
    prep_path = tmp_path / prep_file
    prep_path.write_text(_VALID_PREP_CONTENT, encoding="utf-8")

    # Stub _load_prep_file and _validate_prep_schema so we control the outcome
    monkeypatch.setattr(server, "_load_prep_file",
                        lambda pf: (_VALID_PREP_DATA, None))
    monkeypatch.setattr(server, "_validate_prep_schema",
                        lambda data, pf: ([], []))

    # Stub the walkability cross-check so it also returns clean
    try:
        from map_system import MapSystem as _MS
        monkeypatch.setattr(_MS, "_parse_rooms_from_prep",
                            lambda self, content: list(_VALID_PREP_DATA["rooms"].keys()))
    except Exception:
        pass

    out = server.validate_prep_file(prep_file=prep_file)

    assert "VALID" in out
    # map_name is REQUIRED by map() — must be present and derived from the filename
    assert f'map(action="init", map_name="test", prep_file="{prep_file}")' in out
    assert "NEXT" in out
    assert "load prep" in out


def test_validate_prep_file_fail_no_map_push(monkeypatch, tmp_path):
    """FAIL path (critical errors) must NOT have a NEXT map push
    (prose containing 'map(action=\"init\"' is fine; a NEXT push is not)."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", server.CAMPAIGN_DIR)  # Wave 8 fault-line twin

    prep_file = "BAD_PREP.md"
    prep_path = tmp_path / prep_file
    prep_path.write_text("# empty\n", encoding="utf-8")

    monkeypatch.setattr(server, "_load_prep_file",
                        lambda pf: ({"rooms": {}, "secrets": {}, "raw_content": ""}, None))
    monkeypatch.setattr(server, "_validate_prep_schema",
                        lambda data, pf: (["Missing required field: rooms"], []))

    out = server.validate_prep_file(prep_file=prep_file)

    assert "CRITICAL" in out or "ERROR" in out
    # No NEXT push advisory; existing prose that says "will block map(action="init")" is OK
    assert "NEXT" not in out
    assert "load prep" not in out


def test_validate_prep_file_warnings_only_no_map_push(monkeypatch, tmp_path):
    """Warnings-only path (no critical errors, but warnings) must NOT have a map push."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", server.CAMPAIGN_DIR)  # Wave 8 fault-line twin

    prep_file = "WARN_PREP.md"
    prep_path = tmp_path / prep_file
    prep_path.write_text("# warn\n", encoding="utf-8")

    monkeypatch.setattr(server, "_load_prep_file",
                        lambda pf: ({"rooms": {"r1": {}}, "secrets": {}, "raw_content": ""}, None))
    monkeypatch.setattr(server, "_validate_prep_schema",
                        lambda data, pf: ([], ["Missing dm_only note in room r1"]))

    out = server.validate_prep_file(prep_file=prep_file)

    assert "WARNING" in out or "warn" in out.lower()
    assert 'map(action="init"' not in out


# ============================================================
# Chain-end pushes (2026-06-18): the two ends the middle chain was missing
#  - reindex_recent success (Step 7, last INDEX call) -> verify_session_save pass 2
#    (confirm_save -> distill_session is covered in test_save_load_roundtrip.py)
# ============================================================

def test_reindex_recent_names_verify_pass2(monkeypatch, tmp_path):
    """Step 7->8 close: a successful reindex names verify_session_save(pass 2)
    in-band (reindex_ok=True since we are on the success path)."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "MASTER_CONTINUITY_CURRENT.md").write_text(
        "## SESSION SAVED - Day 50\nA beat.", encoding="utf-8")
    monkeypatch.setattr(server, "check_ollama_health", lambda: True)
    coll = MagicMock()
    coll.get.return_value = {"ids": []}
    coll.count.return_value = 4
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(
        server, "chunk_text_tiered",
        lambda text, metadata, session_id: [
            {"id": "c1", "text": "Day 50 beat", "embedding_text": "x",
             "metadata": {"tier": 4, "day": 50}}])
    monkeypatch.setattr(server, "get_ollama_embeddings_batch",
                        lambda texts, timeout=120.0: [[0.1] * 768 for _ in texts])

    out = server.reindex_recent()

    assert "ERROR" not in out, out
    assert "verify_session_save(" in out
    assert "pass_number=2" in out          # raw, unquoted -> valid on copy-paste
    assert "verify pass 2" in out
