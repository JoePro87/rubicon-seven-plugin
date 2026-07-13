import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import weapon_schema as ws

def test_damage_type_vocab():
    assert ws.DAMAGE_TYPES == {"kinetic", "beam", "blast", "flame", "electrical", "TOX"}
    assert ws.KINETIC_SUBTYPES == {"slashing", "piercing", "bludgeoning"}

def test_valid_damage_type():
    assert ws.is_valid_damage_type("beam")
    assert ws.is_valid_damage_type("kinetic")
    assert not ws.is_valid_damage_type("psychic")   # creature type, not a damage type
    assert not ws.is_valid_damage_type("")

def test_weapon_type_map_covers_all_base_weapons():
    import server
    names = {w["name"] for w in server.MELEE_WEAPONS.values()} | \
            {w["name"] for w in server.RANGED_WEAPONS.values()}
    assert set(ws.BASE_WEAPON_TYPES) == names, "every base weapon needs a type"

def test_sample_assignments():
    assert ws.BASE_WEAPON_TYPES["Sword"][:2] == ("kinetic", "slashing")
    assert ws.BASE_WEAPON_TYPES["Mace"][:2] == ("kinetic", "bludgeoning")
    assert ws.BASE_WEAPON_TYPES["Spear"][:2] == ("kinetic", "piercing")
    assert ws.BASE_WEAPON_TYPES["Laser Rifle"][:2] == ("beam", None)
    assert ws.BASE_WEAPON_TYPES["Shock Baton"][:2] == ("electrical", None)
    assert ws.BASE_WEAPON_TYPES["Grenade Launcher"][:2] == ("blast", None)
    assert ws.BASE_WEAPON_TYPES["Railgun"][:2] == ("kinetic", "piercing")

def test_every_value_is_valid():
    for name, (dt, sub, conf) in ws.BASE_WEAPON_TYPES.items():
        assert ws.is_valid_damage_type(dt), name
        assert sub in (None, *ws.KINETIC_SUBTYPES), name
        assert (sub is None) or (dt == "kinetic"), f"{name}: subtype only on kinetic"
        assert conf in ("high", "review")

def test_tag_registry_engine_keys():
    assert ws.resolve_tag("Psyche-Suppressant") == "psyche-suppressant"
    assert ws.resolve_tag("Anti-Paradoxical") == "anti-paradoxical"
    assert ws.resolve_tag("Eroding") == "eroding"
    assert ws.resolve_tag("Psyche-Suppressant (2x damage vs psychic creatures)") == "psyche-suppressant"
    assert ws.resolve_tag("Luminous") is None
    assert ws.resolve_tag("Blasphemous") is None

def test_tag_damage_override():
    assert ws.tag_damage_override("Flaming") == "flame"
    assert ws.tag_damage_override("Psyche-Suppressant") is None

def test_engine_tags_extracts_only_known_keys():
    prose = ["Blasphemous (DIS on reaction rolls)", "Psyche-Suppressant (2x vs psychic)", "Nano-edged (gains 2 dice)"]
    assert ws.engine_tags_from_prose(prose) == ["psyche-suppressant"]

def test_build_weapon_from_base():
    w = ws.build_weapon(name="Sword", damage="d8", slots=2, prose_tags=[])
    assert w["damage_type"] == "kinetic" and w["kinetic_subtype"] == "slashing"
    assert w["engine_tags"] == [] and w["damage"] == "d8" and w["slots"] == 2

def test_build_weapon_tag_overrides_damage_type():
    w = ws.build_weapon(name="Sword", damage="d8", slots=2, prose_tags=["Flaming (sets alight)"])
    assert w["damage_type"] == "flame" and w["kinetic_subtype"] is None

def test_build_weapon_extracts_engine_tags():
    w = ws.build_weapon(name="Railgun", damage="3d12", slots=5,
                        prose_tags=["Psyche-Suppressant (2x vs psychic)"])
    assert w["engine_tags"] == ["psyche-suppressant"]
    assert w["damage_type"] == "kinetic" and w["kinetic_subtype"] == "piercing"

def test_build_weapon_explicit_override_wins():
    w = ws.build_weapon(name="Sword", damage="d8", slots=2, prose_tags=[], damage_type="beam")
    assert w["damage_type"] == "beam" and w["kinetic_subtype"] is None

def test_build_armour():
    a = ws.build_armour(name="Hazard Wrap", av_bonus=2, slots=3, prose_tags=[])
    assert a["av_bonus"] == 2 and a["slots"] == 3 and a["engine_tags"] == []

def test_validate_weapon_obj():
    ok = ws.build_weapon(name="Sword", damage="d8", slots=2, prose_tags=[])
    assert ws.validate_weapon(ok) == []
    bad = dict(ok); bad["damage_type"] = "psychic"
    assert ws.validate_weapon(bad)
    bad2 = dict(ok); bad2["engine_tags"] = ["not-a-real-tag"]
    assert ws.validate_weapon(bad2)
    bad3 = dict(ok); bad3["damage_type"] = "beam"; bad3["kinetic_subtype"] = "slashing"
    assert ws.validate_weapon(bad3)


# --- range guarantee (A1): every weapon build outputs ranged/melee -----------

def test_ranged_base_weapons_set_matches_server():
    # The schema's ranged-name set must stay in lockstep with the server's
    # RANGED_WEAPONS table so range-derivation can never silently drift.
    import server
    server_ranged = {w["name"] for w in server.RANGED_WEAPONS.values()}
    assert ws.RANGED_BASE_WEAPONS == server_ranged

def test_build_weapon_always_stamps_valid_range():
    # Explicit class is preserved.
    assert ws.build_weapon("Sword", "d8", 2, range="melee")["range"] == "melee"
    assert ws.build_weapon("Rifle", "d8", 2, range="ranged")["range"] == "ranged"
    # Omitted class is derived from the weapon name.
    assert ws.build_weapon("Laser Rifle", "d8", 2)["range"] == "ranged"
    assert ws.build_weapon("Sword", "d8", 2)["range"] == "melee"
    # A junk/distance value (the old Sniper-Rifle bug) is corrected, not trusted.
    assert ws.build_weapon("Railgun", "d12", 6, range="long")["range"] == "ranged"
    # Unknown name with no class defaults to melee — explicit, never blank.
    w = ws.build_weapon("Whatsit", "d6", 1)
    assert w["range"] == "melee"
    # In every case the field exists and is valid.
    assert w["range"] in ("ranged", "melee")

def test_validate_weapon_rejects_missing_or_bad_range():
    ok = ws.build_weapon(name="Sword", damage="d8", slots=2, prose_tags=[])
    assert ws.validate_weapon(ok) == []
    no_range = dict(ok); no_range.pop("range", None)
    assert ws.validate_weapon(no_range)
    bad_range = dict(ok); bad_range["range"] = "long"
    assert ws.validate_weapon(bad_range)

def test_all_tiers_and_types_generate_valid_range():
    # Basic, Advanced, Exotica x melee, ranged — every generated weapon must
    # come out with the correct, valid range marker.
    import server
    rolls = dict(base_roll=1, basic_roll=1, adv_roll=1, exotic_roll=1)
    for tier in ("basic", "advanced", "exotic"):
        for wtype in ("melee", "ranged"):
            obj = server._generate_weapon_obj(tier=tier, weapon_type=wtype, **rolls)
            assert obj["range"] == wtype, f"{tier}/{wtype} -> {obj.get('range')!r}"
            assert obj["range"] in ("ranged", "melee")


def test_build_weapon_stamps_ammo_max():
    w = ws.build_weapon("Railgun", "d12", 6, range="ranged", ammo="Ud6")
    assert w["ammo"] == "Ud6"
    assert w["ammo_max"] == "Ud6"   # born with it


def test_build_weapon_melee_has_no_ammo_max():
    w = ws.build_weapon("Sword", "d8", 2, range="melee")
    assert "ammo" not in w
    assert "ammo_max" not in w


def test_parasitic_fungal_are_engine_tags():
    w = ws.build_weapon("Spore Thrower", "d10", 3, range="ranged", ammo="Ud8",
                        prose_tags=["Fungal", "Parasitic"])
    assert "fungal" in w["engine_tags"]
    assert "parasitic" in w["engine_tags"]
    assert ws.validate_weapon(w) == []   # known engine_tags, still valid


def test_ammo_faces():
    assert ws._ammo_faces("Ud8") == 8
    assert ws._ammo_faces("ud20") == 20
    assert ws._ammo_faces("Expended") == 0
    assert ws._ammo_faces(None) == 0
    assert ws._ammo_faces("d8") == 0     # bare damage die is NOT ammo
    assert ws._ammo_faces("") == 0
    assert ws._ammo_faces("ud0") == 0
    assert ws._ammo_faces("u0") == 0


def test_validate_weapon_requires_ammo_max():
    bad = ws.build_weapon("Railgun", "d12", 6, range="ranged", ammo="Ud6")
    del bad["ammo_max"]
    assert any("ammo_max" in e for e in ws.validate_weapon(bad))


def test_validate_weapon_ammo_max_not_smaller():
    bad = ws.build_weapon("Railgun", "d12", 6, range="ranged", ammo="Ud6")
    bad["ammo_max"] = "Ud4"   # smaller than current
    assert any("smaller" in e for e in ws.validate_weapon(bad))


def test_validate_weapon_expended_ok_with_max():
    w = ws.build_weapon("Railgun", "d12", 6, range="ranged", ammo="Ud6")
    w["ammo"] = "Expended"    # depleted, max still present
    assert ws.validate_weapon(w) == []
