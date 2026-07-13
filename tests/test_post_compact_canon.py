"""C27 — post_compact must force check_canon on the first post-compaction turn.

Compaction is the DM's most amnesiac moment, but the per-turn canon_required gate
stays off while the scene fingerprint is unchanged (as it is right after a
compaction). post_compact now blanks scene_fingerprint so turn_reset computes
scene_changed=True -> canon_required=True next turn, and prints an explicit
'check_canon is REQUIRED' reminder.
"""
import pytest


def _run_post_compact(monkeypatch, tmp_path, state):
    import hooks.hook_utils as hu
    import hooks.post_compact as pc
    monkeypatch.setattr(hu, "STATE_FILE", tmp_path / ".hook_state.json")
    monkeypatch.setattr(hu, "LOCK_FILE", tmp_path / ".hook_state.lock")
    # Isolate vault re-derivation from any real campaign dir.
    monkeypatch.setattr(pc, "CAMPAIGN_DIR", tmp_path)
    hu.save_state(state)
    with pytest.raises(SystemExit) as exc:
        pc.main()
    return exc.value.code, hu.load_state()


def test_post_compact_blanks_scene_fingerprint(tmp_path, monkeypatch, capsys):
    state = {"session_type": "gameplay", "session_started": True,
             "scene_fingerprint": "stable-scene-abc123"}
    code, new_state = _run_post_compact(monkeypatch, tmp_path, state)
    assert code == 0
    assert new_state.get("scene_fingerprint") == ""
    out = capsys.readouterr().out
    assert "check_canon is REQUIRED on your next narrative turn." in out


def test_post_compact_still_resets_validate_prose(tmp_path, monkeypatch, capsys):
    # The pre-existing resets must survive alongside the new fingerprint clear.
    state = {"session_type": "gameplay", "session_started": True,
             "scene_fingerprint": "x", "validate_prose_called": True}
    _code, new_state = _run_post_compact(monkeypatch, tmp_path, state)
    assert new_state.get("validate_prose_called") is False
    assert new_state.get("canon_delivered") == {}


def test_post_compact_skips_when_not_gameplay(tmp_path, monkeypatch, capsys):
    # In development/maintenance the hook exits early and must NOT touch state.
    state = {"session_type": "development", "scene_fingerprint": "keep-me"}
    code, new_state = _run_post_compact(monkeypatch, tmp_path, state)
    assert code == 0
    assert new_state.get("scene_fingerprint") == "keep-me"
