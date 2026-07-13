"""Tests for Active Map field parsing + writing in CURRENT_STATUS.md."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import server


STATUS_NONE = """# CURRENT STATUS
**Location:** Rooftop Garden, Ceruline
**Scene Type:** social
**Active Prep:** CERULINE_ARCOLOGY_PREP.md
**Active Map:** None
"""

STATUS_SET = STATUS_NONE.replace("**Active Map:** None", "**Active Map:** chromatic_wound")


def test_parse_active_map_none():
    parsed = server._parse_status_content(STATUS_NONE)
    assert parsed["active_map"] == "None"


def test_parse_active_map_set():
    parsed = server._parse_status_content(STATUS_SET)
    assert parsed["active_map"] == "chromatic_wound"


def test_parse_active_map_default_when_absent():
    parsed = server._parse_status_content("# CURRENT STATUS\n**Location:** Nowhere\n")
    assert parsed["active_map"] == "None"


def test_update_active_map_writes_field(tmp_path, monkeypatch):
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(STATUS_NONE, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    ok = server._update_current_status_active_map("chromatic_wound")
    assert ok is True
    assert "**Active Map:** chromatic_wound" in status.read_text(encoding="utf-8")


def test_update_active_map_false_when_field_absent(tmp_path, monkeypatch):
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("# CURRENT STATUS\n**Location:** Nowhere\n", encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    ok = server._update_current_status_active_map("x")
    assert ok is False  # do not fabricate the field if the template lacks it


def test_write_then_parse_roundtrip(tmp_path, monkeypatch):
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(STATUS_NONE, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    assert server._update_current_status_active_map("chromatic_wound") is True
    parsed = server._parse_status_content(status.read_text(encoding="utf-8"))
    assert parsed["active_map"] == "chromatic_wound"


def test_write_handles_special_chars_in_name(tmp_path, monkeypatch):
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(STATUS_NONE, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    # a name with a regex-special replacement sequence must not raise
    assert server._update_current_status_active_map("wound\\1.v2") is True
    assert "**Active Map:** wound\\1.v2" in status.read_text(encoding="utf-8")
