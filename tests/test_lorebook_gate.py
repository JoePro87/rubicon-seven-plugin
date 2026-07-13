"""Tripwire enforcement coverage for hooks/lorebook_gate.py.

The lorebook gate is the data-driven guard that arms the stop-check when a user
message contains a lore-bearing keyword and no lorebook(view, ...) call fired.
Its tripwire vocabulary is the union of:
  - lorebook.json keywords (campaign data-driven, auto-extends)
  - ENGINE_AUGMENT_KEYWORDS (always-on, book/generic hard-coded tripwires)
  - the campaign-side lorebook_gate_words.json file's augment_keywords (fail-open)
minus:
  - ENGINE_EXCLUDE_KEYWORDS (generic-English/domain noise, hard-coded)
  - the campaign-side gate-words file's exclude_keywords (fail-open)
  - party-roster names, subtracted PER CALL from the live roster
    (hook_utils.load_party_names) — never hardcoded or cached.

Confirms clean input is NOT flagged, and guards against a silent-disable
regression where the keyword set goes empty (which would turn the entire
tripwire gate into a no-op).

Why this matters: a regression to an empty keyword set would silently disable
ALL tripwire enforcement with no visible failure during play.
"""
import json
import sys
from pathlib import Path

import pytest

MCP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MCP_DIR))

from hooks import lorebook_gate  # noqa: E402
from hooks.lorebook_gate import (  # noqa: E402
    AUGMENT_KEYWORDS,
    extract_triggers,
    load_lorebook_keywords,
    should_skip_message,
    lorebook_was_called,
    assistant_turn_is_tool_only,
)

# The production lorebook.json — the real source of truth for the data-driven
# tripwire vocabulary. The shared conftest fixture redirects RUBICON_CAMPAIGN_DIR
# to an empty temp dir, so the keyword-loading path must be pointed at the real
# file to exercise the gate as it runs in production.
REAL_LOREBOOK = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign" / "lorebook.json"


@pytest.fixture
def real_lorebook(monkeypatch):
    """Point the gate at the production lorebook.json and reset its mtime cache.

    extract_triggers()/load_lorebook_keywords() read a module-level LOREBOOK_PATH
    and an mtime cache. We repoint both and force a reload so the data-driven
    tripwire keywords (e.g. 'telepathy') are actually loaded under test.

    CAMPAIGN_DIR/GATE_WORDS_PATH are left untouched (they still point at the
    isolated test temp dir from conftest.py), so this fixture exercises real
    campaign lorebook data without picking up the owner's live gate-words file
    or roster — those are covered separately via _gate_env.
    """
    if not REAL_LOREBOOK.exists():
        pytest.skip(f"production lorebook.json not found at {REAL_LOREBOOK}")
    monkeypatch.setattr(lorebook_gate, "LOREBOOK_PATH", REAL_LOREBOOK)
    # Invalidate the mtime cache so the next load re-reads from the real file.
    monkeypatch.setattr(
        lorebook_gate, "_CACHE", {"mtime": -1.0, "gw_mtime": -1.0, "keywords": frozenset()}
    )
    yield


def _gate_env(tmp_path, monkeypatch, lorebook=None, gate_words=None, roster=None):
    """Point lorebook_gate at a temp campaign; reset its cache."""
    import hooks.lorebook_gate as lg
    monkeypatch.setattr(lg, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(lg, "LOREBOOK_PATH", tmp_path / "lorebook.json")
    monkeypatch.setattr(lg, "GATE_WORDS_PATH", tmp_path / "lorebook_gate_words.json")
    lg._CACHE.update({"mtime": -1.0, "gw_mtime": -1.0, "keywords": frozenset()})
    if lorebook is not None:
        (tmp_path / "lorebook.json").write_text(json.dumps(lorebook), encoding="utf-8")
    if gate_words is not None:
        (tmp_path / "lorebook_gate_words.json").write_text(json.dumps(gate_words), encoding="utf-8")
    if roster is not None:
        cdir = tmp_path / "characters"
        cdir.mkdir(exist_ok=True)
        for slug, name in roster.items():
            (cdir / f"{slug}.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return lg


# ---------------------------------------------------------------------------
# Silent-disable regression guard — the keyword set must never be empty.
# ---------------------------------------------------------------------------

def test_augment_keyword_set_is_non_empty():
    """The always-on tripwire augment list must never be silently emptied.

    AUGMENT_KEYWORDS (alias of ENGINE_AUGMENT_KEYWORDS) is the hard-coded floor
    of tripwire vocabulary. If this ever collapses to empty, lorebook.json could
    also be empty/missing and the gate would enforce nothing — a silent disable.
    This is the floor guard.
    """
    assert len(AUGMENT_KEYWORDS) > 0, (
        "AUGMENT_KEYWORDS is empty — tripwire enforcement is silently disabled"
    )


def test_loaded_keyword_set_is_non_empty(real_lorebook):
    """The active keyword set (lorebook + augment union) must be non-empty.

    This is what extract_triggers() consults. An empty set means the gate
    matches nothing and never arms — a silent disable of the whole tripwire
    mechanism.
    """
    keywords = load_lorebook_keywords()
    assert len(keywords) > 0, (
        "load_lorebook_keywords() returned an empty set — gate disabled"
    )


def test_augment_keywords_subset_of_loaded_keywords(real_lorebook):
    """Every always-on augment tripwire must survive into the active set.

    load_lorebook_keywords() unions AUGMENT_KEYWORDS in; if a future refactor
    drops the union, the always-on tripwires would vanish even while
    lorebook.json keywords remain. This catches that.
    """
    keywords = load_lorebook_keywords()
    missing = AUGMENT_KEYWORDS - keywords
    assert not missing, f"Augment tripwires dropped from active set: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Named tripwire #1 — Creenash never eats (neobloom photosynthesis biology).
# This is book/generic neobloom biology vocabulary, so it stays engine-side.
# ---------------------------------------------------------------------------

def test_tripwire_photosynthesis_is_armed():
    """'photosynthesis' is an always-on tripwire (Creenash-never-eats biology)."""
    assert "photosynthesis" in AUGMENT_KEYWORDS


def test_tripwire_creenash_eats_message_flags(tmp_path, monkeypatch):
    """A message touching neobloom feeding biology must surface a trigger.

    Driven through a temp campaign dir (no owner lorebook data needed —
    'photosynthesis' is an engine augment, always present)."""
    lg = _gate_env(tmp_path, monkeypatch, lorebook={"entries": []})
    msg = "You set a plate of food down and watch his photosynthesis at work."
    triggers = lg.extract_triggers(msg)
    assert "photosynthesis" in triggers, (
        f"Creenash-eats tripwire not flagged; got {triggers}"
    )


def test_tripwire_neobloom_biology_terms_armed():
    """The cluster of neobloom-biology tripwires are all present in the augment set."""
    for term in ("neobloom", "voxpod", "voxpods", "photosynthesize"):
        assert term in AUGMENT_KEYWORDS, f"{term} missing from tripwire augment set"


# ---------------------------------------------------------------------------
# 'patagia' (Bugsie-glides tripwire) moved campaign-side 2026-07-13: it was
# never book/generic vocabulary, so it is no longer engine-hardcoded. The
# mechanism that makes it work — the campaign-side gate-words file's
# augment_keywords — is proven directly below (test_campaign_augment_words_fire),
# using patagia itself as the worked example.
# ---------------------------------------------------------------------------

def test_patagia_not_hardcoded_engine_side():
    """'patagia' must NOT be an engine augment — it is a campaign mover word."""
    assert "patagia" not in AUGMENT_KEYWORDS


# ---------------------------------------------------------------------------
# Named tripwire #2 — private telepathy (others never hear the bond).
# 'telepathy' is sourced from the campaign lorebook.json data (not hardcoded
# engine vocabulary), so this legitimately exercises the real campaign file.
# ---------------------------------------------------------------------------

def test_tripwire_telepathy_is_armed(real_lorebook):
    """'telepathy' must be in the active keyword set (private-telepathy tripwire).

    Sourced from lorebook.json keywords rather than the augment list, so this
    asserts against the loaded union (the surface extract_triggers consults).
    """
    keywords = load_lorebook_keywords()
    assert "telepathy" in keywords, "private-telepathy tripwire not in active set"


def test_tripwire_telepathy_message_flags(real_lorebook):
    """A message implying others overhear the bond must surface a trigger."""
    msg = "The whole room seems to overhear the telepathy passing between them."
    triggers = extract_triggers(msg)
    assert "telepathy" in triggers, (
        f"private-telepathy tripwire not flagged; got {triggers}"
    )


# ---------------------------------------------------------------------------
# Clean input must NOT be flagged (false-positive guard).
# ---------------------------------------------------------------------------

def test_clean_message_produces_no_triggers(real_lorebook):
    """Ordinary scene prose with no lore keywords must not arm the gate."""
    msg = "The wind blows softly across an open courtyard as the light fades."
    triggers = extract_triggers(msg)
    assert triggers == [], f"Clean message wrongly flagged: {triggers}"


def test_empty_message_produces_no_triggers():
    """Empty input is never a tripwire."""
    assert extract_triggers("") == []


# ---------------------------------------------------------------------------
# Party exclusion — now derived from the LIVE roster, not a hardcoded list.
# ---------------------------------------------------------------------------

def test_roster_names_excluded_from_triggers(tmp_path, monkeypatch):
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["Zephyrine"], "context": "PC"}]},
                    roster={"zeph": "Zephyrine"})
    assert lg.extract_triggers("We ask Zephyrine about the ruins near the delta.") == []


def test_multiword_roster_name_tokens_excluded(tmp_path, monkeypatch):
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["Windrider"], "context": "PC"}]},
                    roster={"z": "Zeph Windrider"})
    assert lg.extract_triggers("The Windrider legend follows her everywhere here.") == []


def test_no_roster_means_no_party_exclusion(tmp_path, monkeypatch):
    """Missing/empty roster fails open — nothing is excluded, gate keeps working."""
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["Zephyrine"], "context": "PC"}]})
    assert lg.extract_triggers("We ask Zephyrine about the ruins near the delta.") == ["zephyrine"]


# ---------------------------------------------------------------------------
# Campaign-side gate-words file — exclude/augment merge, fail-open.
# ---------------------------------------------------------------------------

def test_campaign_augment_words_fire(tmp_path, monkeypatch):
    """Campaign augment_keywords fire even though they're not in lorebook.json
    or ENGINE_AUGMENT_KEYWORDS — proves the moved 'patagia' mover still works
    when a campaign supplies it via lorebook_gate_words.json."""
    lg = _gate_env(tmp_path, monkeypatch, lorebook={"entries": []},
                    gate_words={"augment_keywords": ["patagia", "glimmerfall"]})
    hits = lg.extract_triggers("Her patagia caught the light over Glimmerfall today.")
    assert "patagia" in hits and "glimmerfall" in hits


def test_campaign_exclude_words_subtract(tmp_path, monkeypatch):
    # Message deliberately avoids any ENGINE_AUGMENT_KEYWORDS term (e.g. "before"
    # is a time-chronology augment) — campaign excludes only subtract from the
    # lorebook-derived set, not the engine augment union (spec §3).
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["waystation"], "context": "x"}]},
                    gate_words={"exclude_keywords": ["waystation"]})
    assert lg.extract_triggers("They stopped at the waystation for a while.") == []


def test_gate_words_fail_open_on_malformed(tmp_path, monkeypatch):
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["thornback"], "context": "x"}]})
    (tmp_path / "lorebook_gate_words.json").write_text("{broken", encoding="utf-8")
    assert "thornback" in lg.extract_triggers("A thornback crossed the dunes ahead of us.")


def test_gate_words_fail_open_on_missing_file(tmp_path, monkeypatch):
    """No campaign gate-words file at all: engine-only lists still work."""
    lg = _gate_env(tmp_path, monkeypatch,
                    lorebook={"entries": [{"keywords": ["thornback"], "context": "x"}]})
    assert "thornback" in lg.extract_triggers("A thornback crossed the dunes ahead of us.")


def test_cache_invalidates_on_gate_words_change(tmp_path, monkeypatch):
    lg = _gate_env(tmp_path, monkeypatch, lorebook={"entries": []})
    assert lg.extract_triggers("The glimmerfall approach takes two days on foot.") == []
    import os, time
    (tmp_path / "lorebook_gate_words.json").write_text(
        json.dumps({"augment_keywords": ["glimmerfall"]}), encoding="utf-8")
    ts = time.time() + 2
    os.utime(tmp_path / "lorebook_gate_words.json", (ts, ts))
    assert "glimmerfall" in lg.extract_triggers("The glimmerfall approach takes two days on foot.")


# ---------------------------------------------------------------------------
# extract_triggers bounding / case behavior.
# ---------------------------------------------------------------------------

def test_extract_triggers_is_case_insensitive(real_lorebook):
    """Tripwire matching ignores case."""
    assert "photosynthesis" in extract_triggers("PHOTOSYNTHESIS blooms in the strange light")


def test_extract_triggers_respects_max_cap(real_lorebook):
    """The trigger list is capped to max_triggers."""
    msg = (
        "photosynthesis telepathy neobloom voxpod kronophage "
        "hegemony ceruline kalaxis communion gleam exotica"
    )
    triggers = extract_triggers(msg, max_triggers=3)
    assert len(triggers) <= 3, f"max_triggers cap not honored: {triggers}"


# ---------------------------------------------------------------------------
# should_skip_message — gate-bypass routing.
# ---------------------------------------------------------------------------

def test_skip_short_message():
    assert should_skip_message("hi there") is True


def test_skip_admin_command():
    assert should_skip_message("/session-start now please begin the day") is True


def test_skip_parenthetical_meta():
    assert should_skip_message("(this is an out of character meta note for the DM)") is True


def test_skip_hook_echo_feedback():
    """Echoed stop-hook feedback must not re-arm the gate (self-cascade guard)."""
    echo = "LOREBOOK GAP: halyn was not called this turn, please fix the delivery."
    assert should_skip_message(echo) is True


def test_normal_inplay_message_not_skipped():
    """A normal in-character line of sufficient length is not skipped."""
    msg = "You step into the garden and study the strange flowers along the wall."
    assert should_skip_message(msg) is False


# ---------------------------------------------------------------------------
# Transcript-scanning helpers — lorebook_was_called / assistant_turn_is_tool_only.
# ---------------------------------------------------------------------------

def _assistant_msg(*blocks):
    return {"role": "assistant", "content": list(blocks)}


def test_lorebook_was_called_detects_lorebook_tool_use():
    hook_input = {
        "transcript_messages": [
            _assistant_msg(
                {"type": "tool_use", "name": "mcp__rubicon-seven__lorebook"}
            )
        ]
    }
    assert lorebook_was_called(hook_input) is True


def test_lorebook_was_called_false_for_other_tool():
    hook_input = {
        "transcript_messages": [
            _assistant_msg(
                {"type": "tool_use", "name": "mcp__rubicon-seven__check_canon"}
            )
        ]
    }
    assert lorebook_was_called(hook_input) is False


def test_lorebook_was_called_empty_transcript():
    assert lorebook_was_called({"transcript_messages": []}) is False


def test_assistant_turn_is_tool_only_true():
    hook_input = {
        "transcript_messages": [
            _assistant_msg(
                {"type": "tool_use", "name": "mcp__rubicon-seven__check_canon"}
            )
        ]
    }
    assert assistant_turn_is_tool_only(hook_input) is True


def test_assistant_turn_is_tool_only_false_when_narrative_present():
    hook_input = {
        "transcript_messages": [
            _assistant_msg(
                {"type": "tool_use", "name": "mcp__rubicon-seven__check_canon"},
                {
                    "type": "text",
                    "text": (
                        "You step into the garden and the cold air bites at your "
                        "skin as the flowers turn toward you in slow recognition."
                    ),
                },
            )
        ]
    }
    assert assistant_turn_is_tool_only(hook_input) is False


def test_missing_lorebook_falls_back_to_augment_keywords(monkeypatch, tmp_path):
    """A missing/unreadable lorebook.json must NOT silently disable tripwires.

    Cold-start regression guard: if the file can't be stat'd and nothing is
    cached yet, load_lorebook_keywords() must still return the always-on
    ENGINE_AUGMENT_KEYWORDS (union campaign augments, fail-open here since no
    gate-words file exists) so the gate never degrades to a no-op."""
    monkeypatch.setattr(lorebook_gate, "LOREBOOK_PATH", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(lorebook_gate, "GATE_WORDS_PATH", tmp_path / "no_gate_words.json")
    monkeypatch.setattr(
        lorebook_gate, "_CACHE", {"mtime": -1.0, "gw_mtime": -1.0, "keywords": frozenset()}
    )
    kw = load_lorebook_keywords()
    assert kw, "missing lorebook collapsed the tripwire set to empty (gate is a no-op)"
    assert AUGMENT_KEYWORDS <= kw, "always-on tripwire keywords dropped on missing lorebook"
