"""edge-cases (low) — _combat_init must fail loud, not crash, when the character
roster can't load.

_combat_init did `chars_data, _ = _load_characters()` (discarding the error) then
immediately iterated chars_data["characters"]. _load_characters returns
(None, err) on any failure (missing split-sheet dir, corrupt JSON), so combat
init on a broken roster raised a raw 'NoneType is not subscriptable' traceback at
the exact moment the DM most needs a legible message.
"""
import server


def test_combat_init_returns_clean_error_on_roster_failure(monkeypatch):
    monkeypatch.setattr(server, "GAME_STATE", {})
    monkeypatch.setattr(server, "_load_characters", lambda: (None, "split sheets not found"))
    result = server._combat_init(["ghoul"])
    assert isinstance(result, str)
    assert "ERROR" in result
    assert "roster" in result.lower()
    assert "split sheets not found" in result


def test_combat_init_error_does_not_arm_combat(monkeypatch):
    gs = {}
    monkeypatch.setattr(server, "GAME_STATE", gs)
    monkeypatch.setattr(server, "_load_characters", lambda: (None, "corrupt JSON"))
    server._combat_init(["ghoul"])
    # A failed init must not leave combat half-armed.
    assert not gs.get("active_combat")
