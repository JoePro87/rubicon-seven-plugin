"""Cold-start seam: full_session_startup emits the player view.

Table report 2026-07-06: the dashboard sat on its empty-state through a whole
settlement session because nothing writes player_view.json until the first
state-changing tool fires. Session start must emit so the statusline, /menu,
and dashboard have data from turn 0.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402  (injects session_tools deps)
import session_tools  # noqa: E402


def test_startup_emits_player_view(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "_emit_player_view",
                        lambda *a, **k: calls.append(1))
    out = session_tools.full_session_startup(characters_present="Nobody")
    assert isinstance(out, str) and out  # startup completed on an empty campaign
    assert calls, "full_session_startup must emit the player view (cold-start seam)"


def test_startup_survives_broken_emitter(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("emitter down")
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "_emit_player_view", _boom)
    out = session_tools.full_session_startup(characters_present="Nobody")
    assert isinstance(out, str) and out  # advisory surface never blocks startup
