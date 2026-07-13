import sys
sys.path.insert(0, r"C:\rubicon-seven-mcp\.claude\worktrees\queued-followups")
import server
import bestiary_encounter


def _react(**kw):
    fn = getattr(server._roll_reaction, "fn", server._roll_reaction)
    return fn(**kw)


def test_four_bands_present(monkeypatch):
    monkeypatch.setattr(server.dice, "d20", lambda: 1)
    assert "Negative" in _react(character_ego=0)
    monkeypatch.setattr(server.dice, "d20", lambda: 10)
    assert "Indifferent" in _react(character_ego=0)
    monkeypatch.setattr(server.dice, "d20", lambda: 18)
    assert "Positive" in _react(character_ego=0)
    monkeypatch.setattr(server.dice, "d20", lambda: 20)
    assert "Actively Helpful" in _react(character_ego=2)  # 20+2=22 -> 21+


def test_no_seven_band_strings(monkeypatch):
    monkeypatch.setattr(server.dice, "d20", lambda: 5)
    out = _react(character_ego=0)
    assert "Could Be Swayed" not in out and "Wary" not in out and "Uninterested" not in out


def test_advantage_takes_higher(monkeypatch):
    rolls = iter([3, 18])
    monkeypatch.setattr(server.dice, "d20", lambda: next(rolls))
    out = _react(character_ego=0, advantage=True)
    assert "Positive" in out  # took the 18, not the 3


def test_resolver_truekin_vs_truekin_is_adv():
    adv, dis, notes = server._reaction_modifiers(
        char={"ancestry": "true-kin", "augmentations": {}},
        vs_ancestry="true-kin", vs_faction=None)
    assert adv >= 1 and "Pure of Blood" in " ".join(notes)


def test_resolver_headbank_is_unconditional_adv():
    char = {"ancestry": "true-kin",
            "augmentations": {"EGO": {"name": "Etiquette HeadBank",
                                      "reaction": {"adv": "all"}}}}
    adv, dis, notes = server._reaction_modifiers(char, vs_ancestry=None, vs_faction=None)
    assert adv >= 1 and "HeadBank" in " ".join(notes)


def test_resolver_faction_disliked_is_dis(monkeypatch):
    # _faction_rep moved to bestiary_encounter (slice 4); called via a mover->mover edge
    # inside _reaction_modifiers, so patch BOTH namespaces (server alias + module home).
    monkeypatch.setattr(server, "_faction_rep", lambda slug: -2)  # Disliked band
    monkeypatch.setattr(bestiary_encounter, "_faction_rep", lambda slug: -2)
    char = {"ancestry": "newbeast", "augmentations": {}}
    adv, dis, notes = server._reaction_modifiers(char, vs_ancestry=None, vs_faction="cacklemaw")
    assert dis >= 1
