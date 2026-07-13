"""Follower recruitment data (CH printed p.62). Image-verified.

Transcribed from the page image at
docs/superpowers/plans/data/spark_pages/followers-recruit-a.png (ground truth)
on 2026-06-13. Rules text: followers-rules.png (CH p.61).

RECRUIT_TABLE keys are the d20+EGO TOTAL (0..30; the book's first band prints
"0-1" - identical rows are stored under keys 0 AND 1). Banded columns
(LEVEL/HP, AV, ML) are stored FLAT on every row they cover. Band boundaries
read off the image's cell borders:
  LEVEL/HP: 0-10 -> Level 0 (1 HP) | 11-15 -> Level 1 (4 HP)
            16-25 -> Level 2 (8 HP) | 26-30 -> Level 3 (12 HP)
  AV:       0-10 -> 10 | 11-20 -> 11 | 21-30 -> 12
  ML:       0-5 -> +0 | 6-10 -> +1 | 11-15 -> +2 | 16-20 -> +3
            21-25 -> +4 | 26-30 -> +5

Attack parsing: "(d4)" -> damage only; "(d6, electrical)" -> damage +
damage_type; "(d8, blast, 50% chance won't detonate)" -> damage, tags
["blast"], chance text in "note".
"""

RECRUIT_TABLE = {
    # The book's first band prints "0-1": identical rows under 0 and 1.
    0: {"name": "Herta", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Rolling Pin", "damage": "d4"},
        "description": "Elderly New-Falcon who wears a glitching video-mask"},
    1: {"name": "Herta", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Rolling Pin", "damage": "d4"},
        "description": "Elderly New-Falcon who wears a glitching video-mask"},
    2: {"name": "Kinmoon", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Bookbinder's Awl", "damage": "d4"},
        "description": "Aged Mycomorph with a brittle, spiny body"},
    3: {"name": "Ophinus", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Sling", "damage": "d4"},
        "description": "True-kin with virulent facial rash"},
    4: {"name": "Wellet", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Heavy Stick", "damage": "d4"},
        "description": "Cacogen with long flexible limbs"},
    5: {"name": "Roscar", "level": 0, "hp": 1, "av": 10, "ml": 0,
        "attack": {"name": "Dried Cactus in Sock", "damage": "d4"},
        "description": "Synth with barrel-shaped body, leaks blue ikor"},
    6: {"name": "Antfancy", "level": 0, "hp": 1, "av": 10, "ml": 1,
        "attack": {"name": "Throws Darts", "damage": "d4"},
        "description": "Cacogen with broad yellow leaves for hair"},
    7: {"name": "Lusaki", "level": 0, "hp": 1, "av": 10, "ml": 1,
        "attack": {"name": "Gardener's Trowel", "damage": "d4"},
        "description": "Mycomorph with enormous damp black head"},
    8: {"name": "Scula", "level": 0, "hp": 1, "av": 10, "ml": 1,
        "attack": {"name": "Bag of Worthless Coins", "damage": "d4"},
        "description": "True-kin with braided hair and one missing eye"},
    9: {"name": "Caleon", "level": 0, "hp": 1, "av": 10, "ml": 1,
        "attack": {"name": "Leather Belt", "damage": "d4"},
        "description": "New-Cat who wears a mirrored mask"},
    10: {"name": "Teleo", "level": 0, "hp": 1, "av": 10, "ml": 1,
         "attack": {"name": "Screwdriver", "damage": "d4"},
         "description": "Synth with a rusting falcon-shaped body"},
    11: {"name": "Abrax", "level": 1, "hp": 4, "av": 11, "ml": 2,
         "attack": {"name": "Blunt Training Sword", "damage": "d4"},
         "description": "Cacogen with short blunt horns"},
    12: {"name": "Greyoul", "level": 1, "hp": 4, "av": 11, "ml": 2,
         "attack": {"name": "Broken Trumpet", "damage": "d4"},
         "description": "Corpulent true-kin with crimson eyes"},
    13: {"name": "Bluebliss", "level": 1, "hp": 4, "av": 11, "ml": 2,
         "attack": {"name": "Hypodermic Needle", "damage": "d4"},
         "description": "New-Toad with cheap cybernetic limbs"},
    14: {"name": "Greeze", "level": 1, "hp": 4, "av": 11, "ml": 2,
         "attack": {"name": "Rusted Dagger", "damage": "d4"},
         "description": "Boxy synth with a missing head"},
    15: {"name": "Henex", "level": 1, "hp": 4, "av": 11, "ml": 2,
         "attack": {"name": "Carpenter's Saw", "damage": "d4"},
         "description": "Mycomorph with soft, greying flesh"},
    16: {"name": "Longdream", "level": 2, "hp": 8, "av": 11, "ml": 3,
         "attack": {"name": "Old Revolver", "damage": "d6"},
         "description": "True-kin with a tiny body and hunched back"},
    17: {"name": "Chattan", "level": 2, "hp": 8, "av": 11, "ml": 3,
         "attack": {"name": "Ancestral Sword", "damage": "d6"},
         "description": "New-Anemone with a sorrowful crone mask"},
    18: {"name": "Xaphor", "level": 2, "hp": 8, "av": 11, "ml": 3,
         "attack": {"name": "Shepherd's Staff", "damage": "d6"},
         "description": "Cacogen with five legs"},
    19: {"name": "Naigallow", "level": 2, "hp": 8, "av": 11, "ml": 3,
         "attack": {"name": "Axe", "damage": "d6"},
         "description": "Synth with a silver child-like body"},
    20: {"name": "Willing", "level": 2, "hp": 8, "av": 11, "ml": 3,
         "attack": {"name": "Wooden Club", "damage": "d6"},
         "description": "Glowering true-kin who wears plastic clothes"},
    21: {"name": "Aalder", "level": 2, "hp": 8, "av": 12, "ml": 4,
         "attack": {"name": "Sharp Crystal", "damage": "d6"},
         "description": "Cacogen with a prehensile beard"},
    22: {"name": "Daeros", "level": 2, "hp": 8, "av": 12, "ml": 4,
         "attack": {"name": "Whip", "damage": "d6"},
         "description": "New-Addax with ritual scars"},
    23: {"name": "Erken", "level": 2, "hp": 8, "av": 12, "ml": 4,
         "attack": {"name": "Bow", "damage": "d6"},
         "description": "Mycomorph with an eyeless crimson head"},
    24: {"name": "Goldwin", "level": 2, "hp": 8, "av": 12, "ml": 4,
         "attack": {"name": "Volt Baton", "damage": "d6",
                    "damage_type": "electrical"},
         "description": "Synth with an ape-like body that emits smoke"},
    25: {"name": "Patina", "level": 2, "hp": 8, "av": 12, "ml": 4,
         "attack": {"name": "Pick Axe", "damage": "d6"},
         "description": "True-kin with long blonde hair and lacy attire"},
    26: {"name": "Magdan", "level": 3, "hp": 12, "av": 12, "ml": 5,
         "attack": {"name": "Shovel", "damage": "d6"},
         "description": "Cacogen with AV-plated head (+1 AV)"},
    27: {"name": "Khawari", "level": 3, "hp": 12, "av": 12, "ml": 5,
         "attack": {"name": "Hammer", "damage": "d6"},
         "description": "New-Mantis with a child's face mask"},
    28: {"name": "Yarsan", "level": 3, "hp": 12, "av": 12, "ml": 5,
         "attack": {"name": "Nomad's Rifle", "damage": "d8"},
         "description": "Mycomorph with a speckled, leathery head"},
    29: {"name": "Cheontra", "level": 3, "hp": 12, "av": 12, "ml": 5,
         "attack": {"name": "3 Ancient Grenades", "damage": "d8",
                    "tags": ["blast"],
                    "note": "50% chance won't detonate"},
         "description": "Synth with white priest-like body, worships bee hive"},
    30: {"name": "Audrew", "level": 3, "hp": 12, "av": 12, "ml": 5,
         "attack": {"name": "Lasrifle", "damage": "d8",
                    "damage_type": "beam"},
         "description": "True-kin with expensive ape-fur clothing"},
}


def roll_recruit(rng, ego_bonus):
    """Roll d20 + EGO bonus on the recruitment table.

    rng is a randint-style callable (rng(1, 20)). Returns (total, row)
    with total clamped to the table rails 0..30.
    """
    total = max(0, min(30, rng(1, 20) + int(ego_bonus or 0)))
    return total, RECRUIT_TABLE[total]


def follower_level_cap(characters, leader_key):
    """(cap, used): cap = leader's EGO bonus; used = summed Level of every
    POOLED companion (type in follower/pet/steed) with leader==leader_key.
    Mercenaries are a SEPARATE pool (D3). Level-0 creatures add 0 (p.65: they
    do not count toward the cap but must still be fed)."""
    leader = characters.get(leader_key, {})
    ego = leader.get("abilities", {}).get("EGO", {})
    cap = ego.get("current", 0) if isinstance(ego, dict) else (ego or 0)
    used = sum(int(c.get("level", 0)) for c in characters.values()
               if c.get("type") in ("follower", "pet", "steed")
               and c.get("leader") == leader_key)
    return int(cap), used
