"""Mercenary recruitment data (CH printed p.64). Image+position-verified.

Transcribed from docs/superpowers/plans/data/merc_pages/VERIFICATION_NOTES.md
(ground truth; bands computed from extract_words() y-centers) on 2026-06-13.

RECRUIT_TABLE keys are the d20+EGO TOTAL (0..30; the book's first band prints
"0-1" - identical rows stored under keys 0 AND 1). Banded columns (LEVEL/HP,
AV, ML) are stored FLAT on every row they cover. Bands DELIBERATELY misalign
across columns (e.g. total 5 = Level 3 but still AV 12 / ML +5).

Attack schema (same as followers.py): name, damage ("d6".."d12" or "2d10"),
optional damage_type ("beam"/"fire"/"electrical"), tags (["TOX"]/["blast"]/
["piercing"]/["hypergeometric"]), note (e.g. "auto-hit Synth targets").
"""

RECRUIT_TABLE = {
    0: {"name": "Ekateria", "level": 2, "hp": 8, "av": 12, "ml": 5,
        "attack": {"name": "Jewelled Dagger", "damage": "d6"},
        "description": "Cacogen with vestigial feathered wings"},
    1: {"name": "Ekateria", "level": 2, "hp": 8, "av": 12, "ml": 5,
        "attack": {"name": "Jewelled Dagger", "damage": "d6"},
        "description": "Cacogen with vestigial feathered wings"},
    2: {"name": "Whiss", "level": 2, "hp": 8, "av": 12, "ml": 5,
        "attack": {"name": "Crystal Club", "damage": "d6"},
        "description": "New-Wolf who wears a necklace of human teeth"},
    3: {"name": "Nevermont", "level": 2, "hp": 8, "av": 12, "ml": 5,
        "attack": {"name": "Holy Flail", "damage": "d6"},
        "description": "True-kin who wears a fearsome gilded mask"},
    4: {"name": "Clori", "level": 2, "hp": 8, "av": 12, "ml": 5,
        "attack": {"name": "Laspistol", "damage": "d6", "damage_type": "beam"},
        "description": "Synth with chrome pyramid-shaped body"},
    5: {"name": "Groak", "level": 3, "hp": 12, "av": 12, "ml": 5,
        "attack": {"name": "Black War-Fan", "damage": "d6"},
        "description": "Mycomorph with a glossy skull-like head"},
    6: {"name": "Ulfendrop", "level": 3, "hp": 12, "av": 13, "ml": 6,
        "attack": {"name": "Venomous Knife", "damage": "d6", "tags": ["TOX"]},
        "description": "Faa nomad with a long blue beard"},
    7: {"name": "Panaga", "level": 3, "hp": 12, "av": 13, "ml": 6,
        "attack": {"name": "Chrome Revolver", "damage": "d6"},
        "description": "Cacklemaw who wears a wedding dress"},
    8: {"name": "Sunrise", "level": 3, "hp": 12, "av": 13, "ml": 6,
        "attack": {"name": "Quicksilver Sling", "damage": "d6"},
        "description": "Handsome true-kin, claims descent from an Autarch"},
    9: {"name": "Lupe", "level": 4, "hp": 16, "av": 13, "ml": 6,
        "attack": {"name": "Nomad's Rifle", "damage": "d8"},
        "description": "Warty cacogen with infravision"},
    10: {"name": "Mud", "level": 4, "hp": 16, "av": 13, "ml": 6,
         "attack": {"name": "Nomad's Mace", "damage": "d8"},
         "description": "Synth with a transparent, serpent-like body"},
    11: {"name": "Ratch", "level": 4, "hp": 16, "av": 14, "ml": 7,
         "attack": {"name": "Biomechanical Sword", "damage": "d8"},
         "description": "New-Gibbon who wears quicksilver rings"},
    12: {"name": "Xharo", "level": 4, "hp": 16, "av": 14, "ml": 7,
         "attack": {"name": "Ornate Lasrifle", "damage": "d8", "damage_type": "beam"},
         "description": "Mycomorph with a pink veil-like head"},
    13: {"name": "Episgrasso", "level": 5, "hp": 20, "av": 14, "ml": 7,
         "attack": {"name": "Plasma Rapier", "damage": "d8"},
         "description": "Cadaverous Faa nomad, always coughing (1-in-6 dies each week)"},
    14: {"name": "Charity", "level": 5, "hp": 20, "av": 14, "ml": 7,
         "attack": {"name": "Ritual Crossbow", "damage": "d8"},
         "description": "Cacklemaw with blackened nubs for teeth"},
    15: {"name": "Aret", "level": 5, "hp": 20, "av": 14, "ml": 7,
         "attack": {"name": "Fungal Spear", "damage": "d8"},
         "description": "True-kin with heavily burned face"},
    16: {"name": "Imehnit", "level": 5, "hp": 20, "av": 15, "ml": 8,
         "attack": {"name": "Sky-Iron Greatsword", "damage": "d10"},
         "description": "Cacogen with powerful horse-like legs"},
    17: {"name": "Lementer", "level": 6, "hp": 24, "av": 15, "ml": 8,
         "attack": {"name": "Blasphemous Shotgun", "damage": "d10"},
         "description": "Synth which travels on tank-treads"},
    18: {"name": "Vasildos", "level": 6, "hp": 24, "av": 15, "ml": 8,
         "attack": {"name": "Obsidian Trident", "damage": "d10"},
         "description": "New-Wolf, committed vegetarian"},
    19: {"name": "Damatra", "level": 6, "hp": 24, "av": 15, "ml": 8,
         "attack": {"name": "Plasma Rifle", "damage": "d10"},
         "description": "Mycomorph with poisonous peach-pink flesh"},
    20: {"name": "Inthus", "level": 6, "hp": 24, "av": 15, "ml": 8,
         "attack": {"name": "Luminous War Hammer", "damage": "d10"},
         "description": "Faa nomad with implanted night-vision lenses"},
    21: {"name": "Goosehilda", "level": 7, "hp": 28, "av": 16, "ml": 9,
         "attack": {"name": "Grenade Launcher", "damage": "d10", "tags": ["blast"]},
         "description": "Cacklemaw with lustrous fur, always combing it"},
    22: {"name": "Kanak", "level": 7, "hp": 28, "av": 16, "ml": 9,
         "attack": {"name": "Inferno Cannon", "damage": "d10", "damage_type": "fire"},
         "description": "Short true-kin with golden teeth"},
    23: {"name": "Birksop", "level": 7, "hp": 28, "av": 16, "ml": 9,
         "attack": {"name": "Heavy Lasgun", "damage": "d10", "damage_type": "beam"},
         "description": "Headless cacogen, four purple eyes on chest"},
    24: {"name": "Mannoch", "level": 7, "hp": 28, "av": 16, "ml": 9,
         "attack": {"name": "Tesla Cannon", "damage": "d10",
                    "damage_type": "electrical", "note": "auto-hit Synth targets"},
         "description": "Synth with one cyclopean black eye"},
    25: {"name": "Croxley", "level": 8, "hp": 32, "av": 16, "ml": 9,
         "attack": {"name": "Railgun", "damage": "d12", "tags": ["piercing"]},
         "description": "New-Raven who wears funeral attire"},
    26: {"name": "Nussof", "level": 8, "hp": 32, "av": 17, "ml": 10,
         "attack": {"name": "Port-A-Cannon", "damage": "d12", "tags": ["blast"]},
         "description": "Mycomorph with a black, spiny body"},
    27: {"name": "Uck", "level": 8, "hp": 32, "av": 17, "ml": 10,
         "attack": {"name": "Nano-edged Greatsword", "damage": "2d10"},
         "description": "Faa nomad with a silver tongue"},
    28: {"name": "Ricola", "level": 8, "hp": 32, "av": 17, "ml": 10,
         "attack": {"name": "Doom Gauntlets", "damage": "d12"},
         "description": "Cacklemaw with a triple-row of teeth"},
    29: {"name": "Yarrange", "level": 9, "hp": 36, "av": 18, "ml": 10,
         "attack": {"name": "Annihilation Ray", "damage": "d12", "damage_type": "beam"},
         "description": "Planeywoman with luminous veins"},
    30: {"name": "Vanise", "level": 9, "hp": 36, "av": 19, "ml": 10,
         "attack": {"name": "Neon Hypersword", "damage": "d12",
                    "tags": ["hypergeometric"]},
         "description": "Tall yellow Lithling (+5 AV, cannot heal)"},
}


def roll_recruit(rng, ego_bonus):
    """d20 + EGO bonus on the mercenary table; total clamped to 0..30."""
    total = max(0, min(30, rng(1, 20) + int(ego_bonus or 0)))
    return total, RECRUIT_TABLE[total]


def mercenary_level_cap(characters, leader_key):
    """(cap, used): cap = leader's EGO bonus; used = sum of `level` over
    type=='mercenary' sheets with leader==leader_key. SEPARATE from the
    follower cap (CH p.63: mercenaries are their own group)."""
    leader = characters.get(leader_key, {})
    ego = leader.get("abilities", {}).get("EGO", {})
    cap = ego.get("current", 0) if isinstance(ego, dict) else (ego or 0)
    used = sum(int(c.get("level", 0)) for c in characters.values()
               if c.get("type") == "mercenary" and c.get("leader") == leader_key)
    return int(cap), used
