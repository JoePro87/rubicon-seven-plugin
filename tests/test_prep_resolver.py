"""Prep-injection resolver fix (handoff PREP_INJECTION_DEAD_2026-07-24).

The `**Active Prep:**` value in CURRENT_STATUS.md is a DISPLAY LABEL, not a path
(`THYRICOST_PREP (Node 13 expedition — …)` — parenthetical, no `.md`). One shared
resolver must normalize it to the real file; an unresolvable active prep must
SCREAM instead of silently killing prep injection + prep: provenance.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


DISPLAY = "THYRICOST_PREP (Node 13 expedition — salt-bore descent, buried arcology)"


def _campaign(tmp_path, monkeypatch, *, prep_body="# Thyricost\n\nOverview line.\n",
              active_prep_line=DISPLAY, game_state_field=None,
              write_prep=True, prep_name="THYRICOST_PREP.md"):
    """Stand up a tmp campaign dir with a CURRENT_STATUS.md + optional prep file,
    monkeypatch server.CAMPAIGN_DIR and GAME_STATE['active_prep_file']."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", game_state_field)
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(
        "# CURRENT STATUS\n"
        "**Location:** Node 13\n"
        "**Scene Type:** vault_exploration\n"
        f"**Active Prep:** {active_prep_line}\n",
        encoding="utf-8",
    )
    if write_prep:
        (tmp_path / prep_name).write_text(prep_body, encoding="utf-8")
    return tmp_path


# ── _normalize_prep_ref (pure) ──────────────────────────────────────────────

def test_normalize_display_label():
    # verbatim, truncated, truncated+.md — in priority order
    assert server._normalize_prep_ref(DISPLAY) == [
        DISPLAY, "THYRICOST_PREP", "THYRICOST_PREP.md",
    ]


def test_normalize_bare_name():
    assert server._normalize_prep_ref("THYRICOST_PREP") == [
        "THYRICOST_PREP", "THYRICOST_PREP.md",
    ]


def test_normalize_verbatim_md():
    assert server._normalize_prep_ref("THYRICOST_PREP.md") == ["THYRICOST_PREP.md"]


def test_normalize_empty_and_none():
    for raw in ("", "   ", "None", "none", "(none)", "(NONE)"):
        assert server._normalize_prep_ref(raw) == []


# ── _resolve_active_prep_path (existing path or None) ───────────────────────

def test_acceptance1_display_label_resolves(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch)
    p = server._resolve_active_prep_path()
    assert p is not None
    assert p.name == "THYRICOST_PREP.md"
    assert p.exists()


def test_bare_name_resolves(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, active_prep_line="THYRICOST_PREP")
    p = server._resolve_active_prep_path()
    assert p is not None and p.name == "THYRICOST_PREP.md"


def test_verbatim_md_resolves(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, active_prep_line="THYRICOST_PREP.md")
    p = server._resolve_active_prep_path()
    assert p is not None and p.name == "THYRICOST_PREP.md"


def test_none_line_returns_none(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, active_prep_line="None", write_prep=False)
    assert server._resolve_active_prep_path() is None


def test_missing_line_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS\n**Location:** Nowhere\n", encoding="utf-8")
    assert server._resolve_active_prep_path() is None


def test_missing_file_returns_none_not_phantom(tmp_path, monkeypatch):
    # line present, no file on disk -> None (not CAMPAIGN_DIR / "<label>")
    _campaign(tmp_path, monkeypatch, write_prep=False)
    assert server._resolve_active_prep_path() is None


def test_game_state_field_wins_when_set(tmp_path, monkeypatch):
    # field names OTHER_PREP.md (exists); status line names a different prep
    _campaign(tmp_path, monkeypatch, game_state_field="OTHER_PREP.md")
    (tmp_path / "OTHER_PREP.md").write_text("# Other\n", encoding="utf-8")
    p = server._resolve_active_prep_path()
    assert p is not None and p.name == "OTHER_PREP.md"


# ── Acceptance 3: prep: provenance revival via _active_prep_full_text ────────

def test_acceptance3_prep_full_text_returns_body(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, prep_body="The keeper maintains the stacks.\n")
    assert "keeper maintains the stacks" in server._active_prep_full_text()


def test_prep_full_text_empty_when_unresolved(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, write_prep=False)
    assert server._active_prep_full_text() == ""


# ── Task 2: check_canon prep-injection helper (resolve or scream) ────────────

PREP_WITH_SECRET = (
    "# Thyricost\n\n"
    "The salt-bore descends into a buried arcology.\n\n"
    "## ROOM: SaltHall\n\nA wide hall.\n\n"
    "⛔ DM ONLY ⛔\n"
    "- The keeper is a Planeyfolk observer with no authority to grant passage.\n"
    "⛔ END DM ONLY ⛔\n"
)


def test_acceptance2_injection_lines_resolved_with_secret(tmp_path):
    p = tmp_path / "THYRICOST_PREP.md"
    p.write_text(PREP_WITH_SECRET, encoding="utf-8")
    lines = server._prep_injection_lines(
        DISPLAY, p, PREP_WITH_SECRET, "vault_exploration")
    blob = "\n".join(lines)
    # display line uses the RESOLVED filename, not the raw display label
    assert "**ACTIVE PREP FILE:** THYRICOST_PREP.md" in blob
    assert "⛔ SECRETS (do not reveal until discovered):" in blob
    assert "no authority to grant passage" in blob


def test_acceptance4_injection_lines_unresolved_screams():
    lines = server._prep_injection_lines(
        "GHOST_PREP (does not exist)", None, "", "vault_exploration")
    blob = "\n".join(lines)
    assert "ACTIVE PREP UNRESOLVED" in blob
    assert "GHOST_PREP (does not exist)" in blob
    assert "prep: provenance are DEAD" in blob


# ── Task 3: persist the exact filename at write points + startup scream ──────

def _persist_env(tmp_path, monkeypatch):
    """CAMPAIGN_DIR + GAME_STATE_FILE both in tmp so _save_game_state never
    touches the live campaign dir."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "GAME_STATE_FILE", tmp_path / "game_state.json")
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)


def test_persist_active_prep_file_from_display_label(tmp_path, monkeypatch):
    _persist_env(tmp_path, monkeypatch)
    (tmp_path / "THYRICOST_PREP.md").write_text("# T\n", encoding="utf-8")
    got = server._persist_active_prep_file(DISPLAY)
    assert got == "THYRICOST_PREP.md"
    assert server.GAME_STATE["active_prep_file"] == "THYRICOST_PREP.md"
    import json
    on_disk = json.loads((tmp_path / "game_state.json").read_text(encoding="utf-8"))
    assert on_disk["active_prep_file"] == "THYRICOST_PREP.md"


def test_persist_active_prep_file_unresolved_leaves_state(tmp_path, monkeypatch):
    _persist_env(tmp_path, monkeypatch)
    assert server._persist_active_prep_file("GHOST_PREP (x)") is None
    assert server.GAME_STATE["active_prep_file"] is None


def test_update_current_status_prep_persists_filename(tmp_path, monkeypatch):
    _persist_env(tmp_path, monkeypatch)
    (tmp_path / "THYRICOST_PREP.md").write_text("# T\n", encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS\n**Active Prep:** None\n**Scene Type:** social\n"
        "**Last Updated:** old\n", encoding="utf-8")
    assert server._update_current_status_prep("THYRICOST_PREP.md") is True
    assert server.GAME_STATE["active_prep_file"] == "THYRICOST_PREP.md"


def test_update_active_prep_tool_persists_filename(tmp_path, monkeypatch):
    _persist_env(tmp_path, monkeypatch)
    (tmp_path / "THYRICOST_PREP.md").write_text(
        "# Thyricost\n\nOverview.\n", encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS\n**Active Prep:** None\n", encoding="utf-8")
    out = server.update_active_prep(None, "THYRICOST_PREP.md", True)
    assert "ERROR" not in out
    assert server.GAME_STATE["active_prep_file"] == "THYRICOST_PREP.md"


def test_startup_scream_when_unresolved(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, write_prep=False)  # label present, no file
    lines = server._startup_prep_scream_lines()
    assert any("ACTIVE PREP UNRESOLVED" in l for l in lines)


def test_startup_scream_silent_when_resolved(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch)  # label + real file
    assert server._startup_prep_scream_lines() == []


def test_startup_scream_silent_when_none(tmp_path, monkeypatch):
    _campaign(tmp_path, monkeypatch, active_prep_line="None", write_prep=False)
    assert server._startup_prep_scream_lines() == []


# ── Review fixes I1 / M1: end-to-end through the real check_canon ────────────
# check_canon is directly callable with a mock ctx (hooks/gate are PreToolUse,
# bypassed here). The autouse isolate_campaign_dir fixture (conftest.py) gives
# each test its own campaign dir at server.CAMPAIGN_DIR.

class _MockCtx:
    """check_canon never touches ctx before the prep block we exercise."""


def _write_status(body: str):
    import json as _json
    # check_canon reads lorebook.json early and returns a stub if it's absent —
    # seed an empty one so the call reaches the prep-injection block.
    (server.CAMPAIGN_DIR / "lorebook.json").write_text(
        _json.dumps({"entries": []}), encoding="utf-8")
    (server.CAMPAIGN_DIR / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS - DAY 50\n\n"
        "**Day:** 50\n"
        "**Present:** Creenash, Vela\n" + body,
        encoding="utf-8")


def test_i1_none_sentinel_no_scream_no_injection(monkeypatch, caplog):
    """Review I1: the `(none)` sentinel the scaffolder writes must NOT fire the
    UNRESOLVED scream, must inject no prep, and must log no error — a prepless
    campaign is a normal state, not a fault."""
    import logging as _logging
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    _write_status("**Location:** Test Plaza\n"
                  "**Scene Type:** social\n"
                  "**Active Prep:** (none)\n")
    with caplog.at_level(_logging.ERROR):
        out = server.check_canon(
            _MockCtx(), user_input="We look around the plaza.", needs=["prep"])
    assert "ACTIVE PREP UNRESOLVED" not in out
    assert "**ACTIVE PREP FILE:**" not in out
    assert not any("ACTIVE PREP UNRESOLVED" in r.getMessage()
                   for r in caplog.records)


def test_m1_registry_matches_resolved_name_no_false_mismatch(monkeypatch):
    """Review M1: the LOCATION/PREP mismatch block must compare the registry's
    clean filename against the RESOLVED name, not the raw display label — else
    a display-style Active Prep false-positives a mismatch every turn."""
    import json as _json
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    (server.CAMPAIGN_DIR / "THYRICOST_PREP.md").write_text(
        "# Thyricost\n\nOverview.\n", encoding="utf-8")
    (server.CAMPAIGN_DIR / "LOCATION_REGISTRY.json").write_text(
        _json.dumps({"locations": {"Node 13": "THYRICOST_PREP.md"}}),
        encoding="utf-8")
    _write_status(
        "**Location:** Node 13\n"
        "**Scene Type:** vault_exploration\n"
        "**Active Prep:** THYRICOST_PREP (Node 13 expedition — salt-bore)\n")
    out = server.check_canon(
        _MockCtx(), user_input="We descend the salt-bore.", needs=["prep"])
    assert "**ACTIVE PREP FILE:** THYRICOST_PREP.md" in out  # resolved + injected
    assert "LOCATION/PREP MISMATCH" not in out  # registry name == resolved name
