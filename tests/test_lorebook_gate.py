"""Tripwire enforcement coverage for hooks/lorebook_gate.py.

The lorebook gate is the data-driven guard that arms the stop-check when a user
message contains a lore-bearing keyword and no lorebook(view, ...) call fired.
Its tripwire vocabulary is the union of:
  - lorebook.json keywords (data-driven, auto-extends)
  - AUGMENT_KEYWORDS (always-on, hard-coded high-risk tripwires)

This suite locks down the three named CLAUDE.md tripwires that the gate must
keep catching (Creenash never eats / neobloom biology, Bugsie glides via
patagia, private telepathy), confirms clean input is NOT flagged, and guards
against a silent-disable regression where the keyword set goes empty (which
would turn the entire tripwire gate into a no-op).

Why this matters: a regression to an empty keyword set would silently disable
ALL tripwire enforcement with no visible failure during play. These are the
DM-only facts whose violation breaks immersion (offering Creenash food, Bugsie
flying, NPCs overhearing the private bond).
"""
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
    """
    if not REAL_LOREBOOK.exists():
        pytest.skip(f"production lorebook.json not found at {REAL_LOREBOOK}")
    monkeypatch.setattr(lorebook_gate, "LOREBOOK_PATH", REAL_LOREBOOK)
    # Invalidate the mtime cache so the next load re-reads from the real file.
    monkeypatch.setattr(
        lorebook_gate, "_CACHE", {"mtime": -1.0, "keywords": frozenset()}
    )
    yield


# ---------------------------------------------------------------------------
# Silent-disable regression guard — the keyword set must never be empty.
# ---------------------------------------------------------------------------

def test_augment_keyword_set_is_non_empty():
    """The always-on tripwire augment list must never be silently emptied.

    AUGMENT_KEYWORDS is the hard-coded floor of tripwire vocabulary. If this
    ever collapses to empty, lorebook.json could also be empty/missing and the
    gate would enforce nothing — a silent disable. This is the floor guard.
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
# ---------------------------------------------------------------------------

def test_tripwire_photosynthesis_is_armed():
    """'photosynthesis' is an always-on tripwire (Creenash-never-eats biology)."""
    assert "photosynthesis" in AUGMENT_KEYWORDS


def test_tripwire_creenash_eats_message_flags(real_lorebook):
    """A message touching neobloom feeding biology must surface a trigger."""
    msg = "You set a plate of food down and watch his photosynthesis at work."
    triggers = extract_triggers(msg)
    assert "photosynthesis" in triggers, (
        f"Creenash-eats tripwire not flagged; got {triggers}"
    )


def test_tripwire_neobloom_biology_terms_armed():
    """The cluster of neobloom-biology tripwires are all present in the augment set."""
    for term in ("neobloom", "voxpod", "voxpods", "photosynthesize"):
        assert term in AUGMENT_KEYWORDS, f"{term} missing from tripwire augment set"


# ---------------------------------------------------------------------------
# Named tripwire #2 — Bugsie glides via patagia (must climb to glide again).
# ---------------------------------------------------------------------------

def test_tripwire_patagia_is_armed():
    """'patagia' is an always-on tripwire (Bugsie glides, not flies)."""
    assert "patagia" in AUGMENT_KEYWORDS


def test_tripwire_bugsie_glides_message_flags(real_lorebook):
    """A message about a PC's patagia/gliding must surface a trigger."""
    msg = "She spreads her patagia membranes and prepares to leap from the ledge."
    triggers = extract_triggers(msg)
    assert "patagia" in triggers, f"Bugsie-glides tripwire not flagged; got {triggers}"


# ---------------------------------------------------------------------------
# Named tripwire #3 — private telepathy (others never hear the bond).
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


def test_party_names_are_excluded_from_triggers(real_lorebook):
    """Bare party names must not arm the gate (covered by VOICE.md discipline).

    Creenash/Vela etc. are in EXCLUDE_KEYWORDS so a plain mention does not fire.
    """
    msg = "Vela looks at Creenash and Kess waits quietly by the door for them."
    triggers = extract_triggers(msg)
    for name in ("creenash", "vela", "kess"):
        assert name not in triggers, f"party name {name} wrongly flagged"


# ---------------------------------------------------------------------------
# extract_triggers bounding / case behavior.
# ---------------------------------------------------------------------------

def test_extract_triggers_is_case_insensitive(real_lorebook):
    """Tripwire matching ignores case."""
    assert "patagia" in extract_triggers("PATAGIA wings flare wide in the cold air")


def test_extract_triggers_respects_max_cap(real_lorebook):
    """The trigger list is capped to max_triggers."""
    msg = (
        "photosynthesis patagia telepathy neobloom voxpod kronophage "
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
    AUGMENT_KEYWORDS so the gate never degrades to a no-op."""
    monkeypatch.setattr(lorebook_gate, "LOREBOOK_PATH", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(lorebook_gate, "_CACHE", {"mtime": -1.0, "keywords": frozenset()})
    kw = load_lorebook_keywords()
    assert kw, "missing lorebook collapsed the tripwire set to empty (gate is a no-op)"
    assert AUGMENT_KEYWORDS <= kw, "always-on tripwire keywords dropped on missing lorebook"
