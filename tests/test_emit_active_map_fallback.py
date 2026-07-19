"""_emit_player_view resolves the active map itself when not passed.

D135 dashboard pass (2026-07-19): only map() actions handed a map name to the
emitter, so player_map.txt went stale across advance_day/rest/combat/save and
could show the previous site after travel. The bare-call fallback reads the
**Active Map:** field from CURRENT_STATUS.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import player_view  # noqa: E402


def _wire(tmp_path, monkeypatch, status_text):
    if status_text is not None:
        (tmp_path / "CURRENT_STATUS.md").write_text(status_text, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    rendered = []
    monkeypatch.setattr(server.map_system, "render_fog",
                        lambda name: rendered.append(name) or f"FOG:{name}")
    written = []
    monkeypatch.setattr(player_view, "write_player_view",
                        lambda d, fog_map_text=None: written.append(fog_map_text))
    return rendered, written


def test_bare_emit_falls_back_to_active_map_field(tmp_path, monkeypatch):
    rendered, written = _wire(tmp_path, monkeypatch,
                              "# Status\n**Active Map:** thyricost\n")
    server._emit_player_view()
    assert rendered == ["thyricost"]
    assert written == ["FOG:thyricost"]


def test_bare_emit_with_active_map_none_skips_fog(tmp_path, monkeypatch):
    rendered, written = _wire(tmp_path, monkeypatch,
                              "# Status\n**Active Map:** None\n")
    server._emit_player_view()
    assert rendered == []
    assert written == [None]  # view still written, map file untouched


def test_bare_emit_without_status_file_skips_fog(tmp_path, monkeypatch):
    rendered, written = _wire(tmp_path, monkeypatch, None)
    server._emit_player_view()
    assert rendered == []
    assert written == [None]


def test_explicit_map_arg_still_wins(tmp_path, monkeypatch):
    rendered, written = _wire(tmp_path, monkeypatch,
                              "# Status\n**Active Map:** thyricost\n")
    server._emit_player_view("ceruline")
    assert rendered == ["ceruline"]
    assert written == ["FOG:ceruline"]
