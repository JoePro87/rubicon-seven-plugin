import factions as F


def test_standing_bands_cover_the_book_table():
    labels = [b["label"] for b in F.STANDING_BANDS]
    assert labels == ["Hero", "Friend", "Liked", "Neutral", "Disliked", "Enemy", "Nemesis"]


def test_standing_for_every_boundary():
    cases = {
        11: "Hero", 10: "Hero", 9: "Friend", 4: "Friend", 3: "Liked", 1: "Liked",
        0: "Neutral", -1: "Disliked", -3: "Disliked", -4: "Enemy", -9: "Enemy",
        -10: "Nemesis", -11: "Nemesis",
    }
    for rep, label in cases.items():
        assert F.standing_for(rep)["label"] == label, f"rep {rep} -> {label}"


def test_reaction_hints():
    assert F.standing_for(2)["reaction"] == "ADV"
    assert F.standing_for(-2)["reaction"] == "DIS"
    assert F.standing_for(0)["reaction"] == "standard"
    assert F.standing_for(6)["reaction"] == "favorable"
    assert F.standing_for(10)["reaction"] == "favorable"
    assert F.standing_for(-6)["reaction"] == "hostile"
    assert F.standing_for(-10)["reaction"] == "hostile"


def test_effect_text_is_verbatim_snippet():
    assert "die to assist you" in F.standing_for(10)["effect"]
    assert "reaction roll has ADV" in F.standing_for(2)["effect"]
    assert "hunted down" in F.standing_for(-10)["effect"]


def test_minor_tables_are_each_d20():
    for key in ("reputation", "type", "goal", "leader", "assets", "rival"):
        assert len(F.MINOR_FACTION_TABLES[key]) == 20, key
        assert all(isinstance(v, str) and v for v in F.MINOR_FACTION_TABLES[key])


def test_minor_table_endpoints_verbatim():
    t = F.MINOR_FACTION_TABLES
    assert t["reputation"][0] == "Venerable" and t["reputation"][19] == "Paranoid"
    assert t["type"][0] == "Alchemical College" and t["type"][19] == "Fool's Guild"
    assert t["goal"][0] == "Revenge on Rival Faction" and t["goal"][19] == "Serve Cosmic Being"
    assert t["goal"][12] == "Aquire Exotica"
    assert t["leader"][0] == "Pretends to be Stupid" and t["leader"][19] == "Generally Well Liked"
    assert t["leader"][4] == "Obssesses Over Trivia"
    assert t["assets"][0] == "Vast Material Wealth" and t["assets"][19] == "Pact with Quantum Daemon"
    assert t["rival"][0] == "Water Prospectors' Guild" and t["rival"][19] == "Alchemical College"


def test_generate_minor_faction_with_fixed_rolls():
    rec = F.generate_minor_faction(rolls={
        "reputation": 1, "type": 4, "goal": 20, "leader": 16,
        "assets": [1, 20], "rival": 8,
    })
    assert rec["reputation_adjective"] == "Venerable"
    assert rec["type"] == "Death Cult"
    assert rec["goal"] == "Serve Cosmic Being"
    assert rec["leader"] == "Violent Temper"
    assert rec["assets"] == ["Vast Material Wealth", "Pact with Quantum Daemon"]
    assert rec["rival"] == "Mystic College"


def test_generate_minor_faction_rolls_itself():
    rec = F.generate_minor_faction(rng=lambda a, b: a)
    assert rec["reputation_adjective"] == "Venerable"
    assert len(rec["assets"]) == 2
