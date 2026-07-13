"""Regression: _atomic_json_write must survive a TRANSIENT Windows file lock.

The destination of the tmp->final rename can be briefly locked on Windows (AV
scanner / search indexer / a not-yet-released handle), surfacing as
PermissionError (WinError 5). This caused a full-suite-only flake (a lost save
read back as stale state) AND would silently lose saves in live Windows play.
The write retries the rename a few times before giving up.
"""
import json
import pathlib

import pytest

import server


def test_atomic_write_retries_transient_permission_error(isolate_campaign_dir, monkeypatch):
    target = server.CAMPAIGN_DIR / "retry_probe.json"
    real_replace = pathlib.Path.replace
    calls = {"n": 0}

    def flaky_replace(self, dst):
        calls["n"] += 1
        if calls["n"] < 3:           # fail the first two attempts, then succeed
            raise PermissionError(13, "WinError 5 simulated: target locked")
        return real_replace(self, dst)

    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace)
    server._atomic_json_write(target, {"saved": True})

    assert calls["n"] == 3                         # retried, didn't give up early
    assert json.loads(target.read_text(encoding="utf-8")) == {"saved": True}


def test_atomic_write_raises_after_exhausting_retries(isolate_campaign_dir, monkeypatch):
    target = server.CAMPAIGN_DIR / "retry_probe2.json"

    def always_locked(self, dst):
        raise PermissionError(13, "WinError 5 simulated: permanently locked")

    monkeypatch.setattr(pathlib.Path, "replace", always_locked)
    with pytest.raises(PermissionError):
        server._atomic_json_write(target, {"saved": True})
