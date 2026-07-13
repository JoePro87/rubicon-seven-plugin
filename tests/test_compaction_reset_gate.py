"""Blocking gate: the compaction hook must (a) be registered and (b) wipe the
fold memory so folded blocks re-ship full after a compaction. The whole fold
safety model depends on this. If this fails, do not proceed."""
# Complements tests/test_post_compact_canon_delivered.py: this is the blocking
# gate — it adds the settings.json wiring check and runs the reset in-process
# (monkeypatch isolation) rather than via subprocess.
import json
import sys
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MCP_DIR))

CAMPAIGN_SETTINGS = MCP_DIR.parent / "rubicon-seven-campaign" / ".claude" / "settings.json"


def test_post_compact_is_registered_for_compaction():
    """WIRING half: campaign settings.json must register post_compact.py under PostCompact."""
    settings = json.loads(CAMPAIGN_SETTINGS.read_text())
    hooks = settings.get("hooks", {})
    assert "PostCompact" in hooks, "PostCompact event not registered — fold resets will not fire"
    cmds = json.dumps(hooks["PostCompact"])
    assert "post_compact.py" in cmds, "post_compact.py not wired to PostCompact"


def test_post_compact_empties_canon_delivered(tmp_path, monkeypatch):
    """BEHAVIOR half: running the hook on a gameplay state wipes canon_delivered.

    Monkeypatching strategy:
      load_state() and save_state() in hook_utils.py both reference the module-level
      STATE_FILE constant directly.  file_lock() uses the module-level LOCK_FILE.
      post_compact.py imports these three names *from* hook_utils, so the functions
      still close over hook_utils's namespace.  Patching STATE_FILE and LOCK_FILE on
      the hook_utils module is sufficient — no reload needed.
    """
    import hooks.hook_utils as hook_utils

    state_file = tmp_path / ".hook_state.json"
    lock_file = tmp_path / ".hook_state.lock"

    # M2 guard: record whether the REAL hooks/ lock pre-exists so we can prove
    # the LOCK_FILE patch took (no lock leaked into the real hooks/ directory).
    real_lock = MCP_DIR / "hooks" / ".hook_state.lock"
    real_lock_existed_before = real_lock.exists()

    state_file.write_text(json.dumps({
        "session_type": "gameplay",
        "skip_canon_enforcement": False,
        "validate_prose_called": True,
        "canon_delivered": {"scene:emotional_state": {"h": "abc", "t": 5}},
    }))

    # Redirect STATE_FILE and LOCK_FILE in hook_utils so that load_state /
    # save_state / file_lock all operate on our temp files.
    monkeypatch.setattr(hook_utils, "STATE_FILE", state_file)
    monkeypatch.setattr(hook_utils, "LOCK_FILE", lock_file)

    # Import (or re-use already-imported) post_compact and run the hook body.
    import hooks.post_compact as pc
    try:
        pc.main()
    except SystemExit:
        pass

    after = json.loads(state_file.read_text())
    assert after["canon_delivered"] == {}, "compaction did not reset fold memory"

    # M2: the LOCK_FILE patch must have routed locking to the temp path. The hook
    # acquires/releases its lock inside main(), so a leaked real lock would mean
    # the patch silently failed and the hook touched the real hooks/ directory.
    if not real_lock_existed_before:
        assert not real_lock.exists(), (
            "real hooks/.hook_state.lock was created — LOCK_FILE patch did not take, "
            "hook operated on the real hooks/ directory instead of the temp path"
        )
