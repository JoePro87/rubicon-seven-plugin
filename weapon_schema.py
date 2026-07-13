"""Single source of truth for weapon/armour combat schema.

Owns the damage-type vocabulary, the base-weapon type map, the weapon-tag
registry, and the build_weapon/build_armour helpers. Generators, combat, and
the schema validator all read from here so structured weapon data can never
drift from prose (the prose is rendered FROM the structured object).
"""

import re

DAMAGE_TYPES = {"kinetic", "beam", "blast", "flame", "electrical", "TOX"}
KINETIC_SUBTYPES = {"slashing", "piercing", "bludgeoning"}

def _ammo_faces(s) -> int:
    """Face count of a usage-die notation ('Ud8' -> 8). 'Expended'/None -> 0."""
    s = str(s or "").strip().lower()
    if s in ("", "expended", "ud0", "u0"):
        return 0
    m = re.match(r"ud(\d+)$", s)
    return int(m.group(1)) if m else 0

def is_valid_damage_type(dt: str) -> bool:
    return dt in DAMAGE_TYPES

# (damage_type, kinetic_subtype, confidence). "high" = derived from an inherent
# book tag (Beam/Electrical/Blast/Concussive); "review" = judgment (melee shape,
# bullet=piercing) -- surfaced for a human pass, not hidden.
BASE_WEAPON_TYPES = {
    # --- melee ---
    "Dagger": ("kinetic", "piercing", "review"),
    "Flail": ("kinetic", "bludgeoning", "review"),
    "Whip": ("kinetic", "slashing", "review"),
    "Axe": ("kinetic", "slashing", "review"),
    "Club": ("kinetic", "bludgeoning", "review"),
    "Fleshripper": ("kinetic", "slashing", "review"),
    "Shock Baton": ("electrical", None, "high"),
    "Razordisk": ("kinetic", "slashing", "review"),
    "War Fan": ("kinetic", "slashing", "review"),
    "Scythe": ("kinetic", "slashing", "review"),
    "Sword": ("kinetic", "slashing", "review"),
    "Mace": ("kinetic", "bludgeoning", "review"),
    "Rapier": ("kinetic", "piercing", "review"),
    "Spear": ("kinetic", "piercing", "review"),
    "Quarterstaff": ("kinetic", "bludgeoning", "review"),
    "War Hammer": ("kinetic", "bludgeoning", "review"),
    "Great Mace": ("kinetic", "bludgeoning", "review"),
    "Great Axe": ("kinetic", "slashing", "review"),
    "Halberd": ("kinetic", "slashing", "review"),
    "Great Sword": ("kinetic", "slashing", "review"),
    # --- ranged ---
    "Sling": ("kinetic", "bludgeoning", "review"),
    "Revolver": ("kinetic", "piercing", "review"),
    "Pistol": ("kinetic", "piercing", "review"),
    "Musket": ("kinetic", "piercing", "review"),
    "Shotgun": ("kinetic", "piercing", "review"),
    "Crossbow": ("kinetic", "piercing", "review"),
    "Longbow": ("kinetic", "piercing", "review"),
    "Rifle": ("kinetic", "piercing", "review"),
    "Laser Pistol": ("beam", None, "high"),
    "Hand Cannon": ("kinetic", "piercing", "review"),
    "Shock Bow": ("electrical", None, "high"),
    "Auto-Rifle": ("kinetic", "piercing", "review"),
    "Scattergun": ("kinetic", "piercing", "review"),
    "Laser Rifle": ("beam", None, "high"),
    "Concussion Rifle": ("blast", None, "high"),
    "Spore Thrower": ("blast", None, "high"),
    "Grenade Launcher": ("blast", None, "high"),
    "Laser Cannon": ("beam", None, "high"),
    "Port-A-Cannon": ("blast", None, "high"),
    "Railgun": ("kinetic", "piercing", "review"),
}

# Canonical ranged base-weapon names — MUST stay in lockstep with server.py's
# RANGED_WEAPONS table (test_ranged_base_weapons_set_matches_server guards this).
# Used to derive a weapon's ranged/melee class from its name when a caller does
# not supply one. Every name in BASE_WEAPON_TYPES not in here is melee.
RANGED_BASE_WEAPONS = frozenset({
    "Sling", "Revolver", "Pistol", "Musket", "Shotgun", "Crossbow", "Longbow",
    "Rifle", "Laser Pistol", "Hand Cannon", "Shock Bow", "Auto-Rifle",
    "Scattergun", "Laser Rifle", "Concussion Rifle", "Spore Thrower",
    "Grenade Launcher", "Laser Cannon", "Port-A-Cannon", "Railgun",
})
VALID_RANGES = ("ranged", "melee")

def normalize_range(value, name=None) -> str:
    """Resolve a weapon's range class to exactly 'ranged' or 'melee'.

    Precedence: a valid explicit value wins; otherwise derive from the weapon
    name (known ranged base -> 'ranged'); unknown -> 'melee'. Never returns
    None/blank, and a junk value like a distance ('long', '80ft') is corrected
    rather than trusted — so no generated weapon can fall through to the combat
    engine's silent melee default.
    """
    v = str(value or "").strip().lower()
    if v in VALID_RANGES:
        return v
    return "ranged" if name in RANGED_BASE_WEAPONS else "melee"

# Engine-relevant tags only. name (lowercased, pre-paren) -> engine_key.
# Everything not here is flavor (resolve_tag -> None).
_TAG_ENGINE_KEY = {
    "psyche-suppressant": "psyche-suppressant",
    "anti-paradoxical": "anti-paradoxical",
    "eroding": "eroding",
    "hypergeometric": "hypergeometric",   # adv. tag 13: double vs Hypergeometric creatures
    "parasitic": "parasitic",
    "fungal": "fungal",
    # R3 -- AV-interacting specials (engine-owned: combat resolves these).
    "vibroactive": "vibroactive",          # hit as if target AV 10 (cap, never raise)
    "piercing": "piercing",                # extra die vs AV>=16; halved vs AV<=13
    "mauling": "mauling",                  # extra die vs AV<=13; halved vs AV>=16
    "dimensional edge": "dimensional-edge",  # campaign-homebrew tag = vibroactive mechanic
}
# Tags that override a weapon's damage_type.
_TAG_DAMAGE_OVERRIDE = {
    "flaming": "flame",
    "shock": "electrical",
    "electrical": "electrical",
}

def _tag_key(name: str) -> str:
    """Normalize a prose tag to its bare lowercased name: strip a parenthetical
    suffix and any clause after a SPACED dash (em/en/hyphen). No-space hyphens
    ('Anti-Paradoxical') are part of the name and survive."""
    return re.split(r"\s*\(|\s+[\u2014\u2013-]\s+",
                    str(name).strip().lower())[0].strip()

def resolve_tag(name: str):
    """Return the engine key for a tag name, or None if it's flavor-only."""
    return _TAG_ENGINE_KEY.get(_tag_key(name))

def tag_damage_override(name: str):
    return _TAG_DAMAGE_OVERRIDE.get(_tag_key(name))

def engine_tags_from_prose(prose_tags) -> list:
    """Extract the normalized engine keys from a prose tag list (deduped, ordered)."""
    out = []
    for t in (prose_tags or []):
        k = resolve_tag(t)
        if k and k not in out:
            out.append(k)
    return out

def build_weapon(name, damage, slots, prose_tags=None, range=None, ammo=None,
                 damage_type=None, kinetic_subtype=None):
    """Mint a structured weapon object. The ONLY way generators/backfill create
    weapons. Precedence for damage_type: explicit arg > tag override > base-map > 'kinetic'."""
    prose_tags = list(prose_tags or [])
    base_dt, base_sub, _conf = BASE_WEAPON_TYPES.get(name, ("kinetic", None, "review"))
    override_dt = None
    for t in prose_tags:
        override_dt = override_dt or tag_damage_override(t)
    dt = damage_type or override_dt or base_dt
    if dt == "kinetic":
        sub = kinetic_subtype if kinetic_subtype is not None else (base_sub if not override_dt else None)
    else:
        sub = None  # subtype only meaningful for kinetic
    obj = {
        "name": name, "damage": damage, "slots": slots,
        "damage_type": dt, "kinetic_subtype": sub,
        "engine_tags": engine_tags_from_prose(prose_tags),
        "tags": prose_tags,
    }
    obj["range"] = normalize_range(range, name)  # always 'ranged' or 'melee'
    if ammo is not None:
        obj["ammo"] = ammo
        obj["ammo_max"] = ammo   # birth value; feed/reload cap restoration to this
    return obj

# Book-cited armour properties (Crimson Hound Explorer's Guide, p.34). These are
# SITUATIONAL save/skill modifiers the DM adjudicates — NOT combat-resistance engine
# tags. The combat engine reads only weapon engine_tags; armour engine_tags stays
# empty (AV is the sole armour output the engine consumes).
ARMOUR_TYPE_PROPERTIES = {
    "Hazard Wrap": "ADV on Saves vs Radiation and Toxins",
    "Plate Armour": "DIS when swimming or climbing.",
}


def build_armour(name, av_bonus, slots, prose_tags=None):
    """Mint a structured armour object. AV is the primary engine output; engine_tags
    is a forward-compatible slot (armour-tag vocabulary is book-verified, not invented)."""
    prose_tags = list(prose_tags or [])
    return {
        "name": name, "av_bonus": int(av_bonus), "slots": slots,
        "engine_tags": engine_tags_from_prose(prose_tags),
        "tags": prose_tags,
    }

_KNOWN_ENGINE_KEYS = set(_TAG_ENGINE_KEY.values())

def validate_armour(obj) -> list:
    """Return a list of human-readable problems ([] == valid)."""
    errs = []
    av_bonus = obj.get("av_bonus")
    if not isinstance(av_bonus, int):
        errs.append(f"av_bonus must be an int, got {type(av_bonus).__name__!r}")
    elif av_bonus < 0:
        errs.append(f"av_bonus must be >= 0, got {av_bonus}")
    for k in obj.get("engine_tags", []):
        if k not in _KNOWN_ENGINE_KEYS:
            errs.append(f"unknown engine_tag {k!r}")
    return errs

def validate_weapon(obj) -> list:
    """Return a list of human-readable problems ([] == valid)."""
    errs = []
    dt = obj.get("damage_type")
    if not is_valid_damage_type(dt):
        errs.append(f"invalid damage_type {dt!r}")
    sub = obj.get("kinetic_subtype")
    if sub is not None and sub not in KINETIC_SUBTYPES:
        errs.append(f"invalid kinetic_subtype {sub!r}")
    if sub is not None and dt != "kinetic":
        errs.append(f"kinetic_subtype set on non-kinetic damage_type {dt!r}")
    if obj.get("range") not in VALID_RANGES:
        errs.append(f"invalid range {obj.get('range')!r} (must be 'ranged' or 'melee')")
    ammo = obj.get("ammo")
    if ammo:
        amax = obj.get("ammo_max")
        if not amax:
            errs.append("ammo set without ammo_max")
        elif _ammo_faces(amax) < _ammo_faces(ammo):
            errs.append(f"ammo_max {amax!r} smaller than ammo {ammo!r}")
    for k in obj.get("engine_tags", []):
        if k not in _KNOWN_ENGINE_KEYS:
            errs.append(f"unknown engine_tag {k!r}")
    return errs
