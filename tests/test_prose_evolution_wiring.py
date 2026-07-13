"""The prose learning loop must actually fire on session commit (fail-safe)."""
import server


def test_evolve_helper_calls_run_evolution(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "_run_prose_evolution", lambda: called.setdefault("ran", True) or {"added": 0})
    # The helper the commit path uses must invoke run_evolution and return its result.
    # (Direct call — see Step 3 for the helper name.)
    server._evolve_prose_blacklist_safe()
    assert called.get("ran") is True


def test_evolve_helper_is_fail_safe(monkeypatch):
    def boom():
        raise RuntimeError("evolver exploded")
    monkeypatch.setattr(server, "_run_prose_evolution", boom)
    # Must NOT raise — a broken evolver can never break a session save.
    result = server._evolve_prose_blacklist_safe()
    assert result is None
