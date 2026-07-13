"""_roll_stat_expr: resolve creature stats that may be ints or dice expressions
(Quantum Daemon 'LVL 2d6', 'AV d6 + 8', 'ML +2d6', etc.) so variable-stat creatures
no longer collapse to the L1/HP4 fallback in _combat_init."""
import server


def test_roll_stat_expr_int_passthrough():
    assert server._roll_stat_expr(5) == 5
    assert server._roll_stat_expr(0) == 0


def test_roll_stat_expr_simple_die():
    for _ in range(50):
        assert 1 <= server._roll_stat_expr("d6") <= 6


def test_roll_stat_expr_multi_die():
    for _ in range(50):
        assert 2 <= server._roll_stat_expr("2d6") <= 12


def test_roll_stat_expr_die_plus_flat():
    for _ in range(50):
        assert 13 <= server._roll_stat_expr("3d6 + 10") <= 28


def test_roll_stat_expr_flat_plus_die():
    for _ in range(50):
        assert 9 <= server._roll_stat_expr("8+d8") <= 16


def test_roll_stat_expr_leading_plus():  # morale notation '+2d6'
    for _ in range(50):
        assert 2 <= server._roll_stat_expr("+2d6") <= 12


def test_roll_stat_expr_garbage_returns_default():
    assert server._roll_stat_expr("Special", default=0) == 0
    assert server._roll_stat_expr("=LVL", default=0) == 0
    assert server._roll_stat_expr(None, default=4) == 4
    assert server._roll_stat_expr("", default=3) == 3


def test_combat_init_rolls_variable_stats(monkeypatch):
    fix = [{"id": "creature-quantum-daemon", "keywords": ["quantum daemon"],
            "contexts": ["combat_active"],
            "stats": {"type": "Outsider", "level": "2d6", "hp": None,
                      "av": "d6 + 8", "morale": "+2d6", "attacks": [], "special": []}}]
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": fix})
    monkeypatch.setattr(server, "_load_characters", lambda: ({"characters": {}}, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    server._combat_init(["Quantum Daemon"])
    e = next(iter(server.GAME_STATE["active_combat"]["enemies"].values()))
    assert 2 <= e["lvl"] <= 12          # rolled, not collapsed to 1
    assert e["hp"] == e["lvl"] * 4      # HP derived from rolled level when book gives none
    assert 9 <= e["av"] <= 14           # d6 + 8
    assert 2 <= e["morale"] <= 12       # +2d6
