"""R3: the four AV-special tags resolve to engine keys; dash-clause stripping."""
import server
import weapon_schema as ws


def test_four_av_tags_resolve():
    assert ws.resolve_tag("Vibroactive") == "vibroactive"
    assert ws.resolve_tag("Piercing") == "piercing"
    assert ws.resolve_tag("Mauling") == "mauling"
    assert ws.resolve_tag("Dimensional Edge") == "dimensional-edge"


def test_dash_clause_stripped():
    # em dash, en dash, spaced hyphen -- all strip the trailing clause
    assert ws.resolve_tag("Dimensional Edge — attacks treat target AV as 10 (unarmored)") == "dimensional-edge"
    assert ws.resolve_tag("Dimensional Edge – treat AV as 10") == "dimensional-edge"
    assert ws.resolve_tag("Dimensional Edge - treat AV as 10") == "dimensional-edge"
    # parenthetical-only still works (pre-existing behavior)
    assert ws.resolve_tag("Piercing (extra die vs AV 16+)") == "piercing"


def test_hyphenated_names_unaffected():
    # no-space hyphens are part of the tag name, never a clause separator
    assert ws.resolve_tag("Anti-Paradoxical") == "anti-paradoxical"
    assert ws.resolve_tag("Psyche-Suppressant") == "psyche-suppressant"


def test_build_weapon_stamps_av_tags():
    w = ws.build_weapon("Sword", "d8", 2, prose_tags=["Rusty", "Piercing"])
    assert w["engine_tags"] == ["piercing"]
    assert ws.validate_weapon(w) == []


def test_validator_accepts_new_keys():
    w = ws.build_weapon("Dagger", "d4", 1, prose_tags=["Vibroactive", "Mauling"])
    assert set(w["engine_tags"]) == {"vibroactive", "mauling"}
    assert ws.validate_weapon(w) == []


def test_generator_round_trip_stamps_vibroactive_and_piercing():
    # exotic tier carries one advanced + one exotic tag: force Piercing (adv 16)
    # + Vibroactive (exotic 20). build_weapon must stamp both engine keys.
    w = server._generate_weapon_obj("exotic", "melee", base_roll=1,
                                    basic_roll=1, adv_roll=16, exotic_roll=20)
    assert "piercing" in w["engine_tags"]
    assert "vibroactive" in w["engine_tags"]
