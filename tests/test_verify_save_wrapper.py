"""Guard for the save-verification wrapper (`hooks/verify_save.verify_save_content`).

This is the PostToolUse hook that diffs a proposed save against the transcript
by shelling out to scripts/verify_save_agent.py. We don't run the LLM subagent
here; we pin the wrapper's branching: a clean pass, a corrections-made result,
malformed agent output, a missing agent script, a nonzero exit, and a timeout.
The agent subprocess and the script path are both monkeypatched.
"""
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks import verify_save


def _fake_run(stdout="", returncode=0, stderr=""):
    def _run(*args, **kwargs):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


def _arm_script(monkeypatch, tmp_path):
    """Make the agent script 'exist' so the wrapper proceeds to subprocess."""
    (tmp_path / "verify_save_agent.py").write_text("# stub")
    monkeypatch.setattr(verify_save, "SCRIPTS_DIR", tmp_path)


def test_all_claims_verified_passes_through(monkeypatch, tmp_path):
    _arm_script(monkeypatch, tmp_path)
    monkeypatch.setattr(verify_save.subprocess, "run",
                        _fake_run(stdout='{"corrections_made": false}'))
    result = verify_save.verify_save_content({"summary": "x"}, "/tmp/transcript.jsonl")
    assert result == {"corrections_made": False}


def test_corrections_made_returns_corrected_fields(monkeypatch, tmp_path):
    _arm_script(monkeypatch, tmp_path)
    payload = '{"corrections_made": true, "corrected_fields": {"summary": "fixed"}, "change_log": "x->fixed"}'
    monkeypatch.setattr(verify_save.subprocess, "run", _fake_run(stdout=payload))
    result = verify_save.verify_save_content({"summary": "x"}, "/tmp/t.jsonl")
    assert result["corrections_made"] is True
    assert result["corrected_fields"]["summary"] == "fixed"


def test_missing_agent_script_is_error(monkeypatch, tmp_path):
    # do NOT create the script
    monkeypatch.setattr(verify_save, "SCRIPTS_DIR", tmp_path)
    result = verify_save.verify_save_content({}, "/tmp/t.jsonl")
    assert "not found" in result["error"].lower()


def test_nonzero_exit_is_error(monkeypatch, tmp_path):
    _arm_script(monkeypatch, tmp_path)
    monkeypatch.setattr(verify_save.subprocess, "run",
                        _fake_run(returncode=1, stderr="boom"))
    result = verify_save.verify_save_content({}, "/tmp/t.jsonl")
    assert "failed" in result["error"].lower() and "boom" in result["error"]


def test_malformed_agent_json_is_error(monkeypatch, tmp_path):
    _arm_script(monkeypatch, tmp_path)
    monkeypatch.setattr(verify_save.subprocess, "run", _fake_run(stdout="not json at all"))
    result = verify_save.verify_save_content({}, "/tmp/t.jsonl")
    assert "invalid json" in result["error"].lower()


def test_timeout_is_error(monkeypatch, tmp_path):
    _arm_script(monkeypatch, tmp_path)

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="verify", timeout=90)
    monkeypatch.setattr(verify_save.subprocess, "run", _raise)
    result = verify_save.verify_save_content({}, "/tmp/t.jsonl")
    assert "timed out" in result["error"].lower()
