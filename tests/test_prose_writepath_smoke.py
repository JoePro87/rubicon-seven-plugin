"""End-to-end smoke test for the prose-pillar WRITE path on real Stop-hook stdin.

Background: between ~2026-05-23 and the 2026-06-12 fix (commit 68eccce), the
soft Stop checks were silent no-ops in live play. Real Stop-hook stdin carries
only `transcript_path`, but the checks read `hook_input["transcript_messages"]`,
which was empty — so the catch-logger never logged and the prose observer never
spawned. That is exactly why catch_analytics.json froze on 2026-05-23 while the
(independent) phrase-reminder primer kept firing.

The fix: `_hydrate_transcript_messages` populates `transcript_messages` once from
`transcript_path`. The existing port test (test_stop_checks_transcript_port.py)
proves the readers SEE the text. This test proves the two write-path endpoints
that actually froze come back to life:

  1. _check_anti_pattern  -> _analytics_log_catch  (phrase catch logging)
  2. _check_semantic_observer -> _spawn_observer   (the Haiku critic)

Each is asserted both ways: DEAD without hydration (the pre-fix live bug) and
ALIVE with it. The dead/alive contrast is what makes the fix load-bearing rather
than incidental.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

import consolidated_stop_check as csc  # noqa: E402
from consolidated_stop_check import (  # noqa: E402
    _check_anti_pattern,
    _check_semantic_observer,
    _get_response_text,
    _hydrate_transcript_messages,
)

_SENTINEL = "gleaming sentinel phrase"


# --- JSONL record builders (same shape as the real transcript) -------------

def _jl_user(text):
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "text", "text": text}]}}


def _jl_assistant(text, tool_uses=None):
    content = [{"type": "text", "text": text}]
    for name, tool_input in (tool_uses or []):
        content.append({"type": "tool_use", "name": name, "input": tool_input})
    return {"type": "assistant",
            "message": {"role": "assistant", "content": content}}


def _real_stdin(tmp_path, records):
    """Hook input shaped like real Stop-hook stdin: path only, no messages."""
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return {"session_id": "smoke", "transcript_path": str(p)}


# --- Shared monkeypatches --------------------------------------------------

def _patch_anti_pattern_deps(monkeypatch):
    """Make the blacklist scan deterministic and the catch-logger observable.

    Returns the list that captures _analytics_log_catch calls.
    """
    # Controlled blacklist: one sentinel pattern, so the test never rots when
    # the live blacklist.json changes.
    monkeypatch.setattr(
        csc, "_load_blacklist_cached",
        lambda: ([(re.compile(_SENTINEL, re.IGNORECASE), _SENTINEL)], []),
    )
    # Deterministic scene + no disk side effects from the corrections log.
    monkeypatch.setattr(csc, "_read_scene_type", lambda: "settlement")
    monkeypatch.setattr(csc, "log_correction", lambda **kw: None)

    logged = []
    monkeypatch.setattr(
        csc, "_analytics_log_catch",
        lambda phrase, scene_type, catch_count, turn_count: logged.append(
            (phrase, scene_type, catch_count, turn_count)
        ),
    )
    return logged


# --- 1) Anti-pattern catch logging -----------------------------------------

def test_anti_pattern_writepath_dead_without_hydration(tmp_path, monkeypatch):
    """Pre-fix live behavior: real stdin, NO hydration -> nothing logged."""
    logged = _patch_anti_pattern_deps(monkeypatch)
    hook_input = _real_stdin(tmp_path, [
        _jl_user("narrate the market"),
        _jl_assistant(f"The stalls catch the light, a {_SENTINEL} over the crowd."),
    ])
    # Deliberately skip _hydrate_transcript_messages -> response_text is blank.
    response_text = _get_response_text(hook_input)
    assert response_text == ""

    state = {"session_type": "gameplay", "validate_prose_called": True}
    fired, _, updates = _check_anti_pattern(hook_input, state, response_text)

    assert logged == []          # the bug: catch-logger never reached
    assert "catch_count" not in updates


def test_anti_pattern_writepath_alive_with_hydration(tmp_path, monkeypatch):
    """Post-fix: hydrate -> the sentinel is seen and logged to analytics."""
    logged = _patch_anti_pattern_deps(monkeypatch)
    hook_input = _real_stdin(tmp_path, [
        _jl_user("narrate the market"),
        _jl_assistant(f"The stalls catch the light, a {_SENTINEL} over the crowd."),
    ])
    _hydrate_transcript_messages(hook_input)
    response_text = _get_response_text(hook_input)
    assert _SENTINEL in response_text

    state = {"session_type": "gameplay", "validate_prose_called": True,
             "turn_count": 7, "catch_count": 0}
    _check_anti_pattern(hook_input, state, response_text)

    # The write path the freeze killed is reached: one catch logged for the sentinel.
    assert len(logged) == 1
    phrase, scene_type, catch_count, turn_count = logged[0]
    assert phrase == _SENTINEL
    assert scene_type == "settlement"
    assert catch_count == 1
    assert turn_count == 7


# --- 2) Prose observer (Haiku critic) spawn --------------------------------

def _narrative_records():
    narration = (
        "The arcology breathes around you. Vines thread the broken arches, and "
        "somewhere below a sleeper turns in its glass cradle. Varro watches "
        "from the balcony, saying nothing, while the water-tokens click in your "
        "palm like small cold teeth. The light here is the colour of old bruises, "
        "and the long corridor ahead swallows the sound of your boots until even "
        "your own breathing feels borrowed from the building itself."
    )
    assert len(narration) >= csc._MIN_NARRATIVE_CHARS  # clears the narrative bar
    return [_jl_user("look around"), _jl_assistant(narration)], narration


def test_observer_spawn_dead_without_hydration(tmp_path, monkeypatch):
    """Pre-fix live behavior: real stdin, NO hydration -> observer never spawns."""
    spawned = []
    monkeypatch.setattr(
        csc, "_spawn_observer",
        lambda text, sid, tid: spawned.append((text, sid, tid)),
    )
    records, _ = _narrative_records()
    hook_input = _real_stdin(tmp_path, records)
    # No hydration -> response_text blank -> _is_narrative_turn short-circuits.
    response_text = _get_response_text(hook_input)
    _check_semantic_observer(hook_input, {"turn_count": 7}, response_text)
    assert spawned == []


def test_observer_spawn_alive_with_hydration(tmp_path, monkeypatch):
    """Post-fix: hydrate -> narrative turn classified, critic gets spawned."""
    spawned = []
    monkeypatch.setattr(
        csc, "_spawn_observer",
        lambda text, sid, tid: spawned.append((text, sid, tid)),
    )
    records, narration = _narrative_records()
    hook_input = _real_stdin(tmp_path, records)
    _hydrate_transcript_messages(hook_input)
    response_text = _get_response_text(hook_input)

    _check_semantic_observer(hook_input, {"turn_count": 7}, response_text)

    assert len(spawned) == 1
    text, sid, tid = spawned[0]
    assert narration[:30] in text
    assert sid == "smoke"
    assert tid == 7


def test_observer_respects_maintenance_bypass(tmp_path, monkeypatch):
    """Even hydrated, skip_canon_enforcement must keep the critic asleep."""
    spawned = []
    monkeypatch.setattr(
        csc, "_spawn_observer",
        lambda text, sid, tid: spawned.append((text, sid, tid)),
    )
    records, _ = _narrative_records()
    hook_input = _real_stdin(tmp_path, records)
    _hydrate_transcript_messages(hook_input)
    response_text = _get_response_text(hook_input)

    _check_semantic_observer(
        hook_input,
        {"turn_count": 7, "skip_canon_enforcement": True},
        response_text,
    )
    assert spawned == []
