"""C22 — MASTER_CONTINUITY_CURRENT.md and CURRENT_STATUS.md must be written
atomically. A plain write_text/open('w') truncates the existing file BEFORE the
new bytes land, so a crash mid-save can destroy the entire accumulated file.

_atomic_text_write writes to a temp file then atomically replaces the target
(sharing _atomic_json_write's Windows transient-lock retry loop) and cleans up
the temp file on failure. Mirrors the 95bce6c cultivation-file precedent.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine_core
from engine_core import _atomic_text_write, _atomic_replace_with_retry


def test_writes_content_roundtrip(tmp_path):
    target = tmp_path / "CURRENT_STATUS.md"
    _atomic_text_write(target, "hello world\nsecond line")
    assert target.read_text(encoding="utf-8") == "hello world\nsecond line"


def test_no_temp_file_left_on_success(tmp_path):
    target = tmp_path / "MASTER_CONTINUITY_CURRENT.md"
    _atomic_text_write(target, "content")
    assert not (tmp_path / "MASTER_CONTINUITY_CURRENT.md.tmp").exists()
    # The temp is a distinct sibling, so an existing .md is untouched by naming.
    assert target.exists()


def test_original_preserved_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "MASTER_CONTINUITY_CURRENT.md"
    target.write_text("ORIGINAL — 50 days of canon", encoding="utf-8")

    def boom(_tmp, _path, attempts=5):
        raise PermissionError("simulated crash during replace")

    monkeypatch.setattr(engine_core, "_atomic_replace_with_retry", boom)
    with pytest.raises(PermissionError):
        _atomic_text_write(target, "NEW partial bytes")

    # The accumulated file must be intact — never truncated.
    assert target.read_text(encoding="utf-8") == "ORIGINAL — 50 days of canon"


def test_temp_file_cleaned_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "CURRENT_STATUS.md"
    target.write_text("orig", encoding="utf-8")

    def boom(_tmp, _path, attempts=5):
        raise PermissionError("simulated")

    monkeypatch.setattr(engine_core, "_atomic_replace_with_retry", boom)
    with pytest.raises(PermissionError):
        _atomic_text_write(target, "new")

    # No stray .tmp left behind.
    assert not (tmp_path / "CURRENT_STATUS.md.tmp").exists()


def test_replace_retries_transient_windows_lock(tmp_path, monkeypatch):
    """The shared retry loop must survive a transient PermissionError and then
    succeed, not crash on the first WinError-5."""
    target = tmp_path / "CURRENT_STATUS.md"
    src = tmp_path / "CURRENT_STATUS.md.tmp"
    src.write_text("payload", encoding="utf-8")

    calls = {"n": 0}
    real_replace = Path.replace

    def flaky_replace(self, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("WinError 5 transient")
        return real_replace(self, dst)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    _atomic_replace_with_retry(src, target)
    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == "payload"


def test_write_file_routes_through_atomic(tmp_path, monkeypatch):
    """engine_core.write_file must go through the atomic text writer so
    advance_day's CURRENT_STATUS.md write is crash-safe."""
    monkeypatch.setattr(engine_core, "CAMPAIGN_DIR", tmp_path)
    seen = {}

    def spy(path, content, encoding="utf-8"):
        seen["path"] = str(path)
        seen["content"] = content

    monkeypatch.setattr(engine_core, "_atomic_text_write", spy)
    assert engine_core.write_file("CURRENT_STATUS.md", "day 42 status") is True
    assert seen["content"] == "day 42 status"
    assert seen["path"].endswith("CURRENT_STATUS.md")
