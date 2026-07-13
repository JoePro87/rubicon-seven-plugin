"""Bestiary & Encounter — decomposition slice 4 (2026-06-17).

Extracted VERBATIM from server.py: bestiary lookups, the encounter table roll, and
the reaction roll/modifier helpers. The `lookup`/`test_dice` tools and the
content_forge registration stay in server.py and import-and-alias these back.

Cross-module persistence/faction functions the movers call STAY in server.py and are
reached via call-time DELEGATING SHIMS (_DELEGATES) bound to the live server module by
register_bestiary_encounter — patch-transparent. rulebook_system (the instance whose
_cache tests mutate) is injected by reference. dice is the engine_core singleton
(tests attribute-patch it, so a plain import is safe); gift/faction/ancestry data come
from their already-extracted modules.
"""
import json
import random

from pydantic import Field
from engine_core import dice
import ancestries as _ancestries
import factions as _factions


# The running server module, supplied by register_bestiary_encounter() at startup.
# We do NOT `import server`: under `python server.py` the server runs as `__main__`,
# so a fresh `import server` would re-execute it as a second module and deadlock the
# alias-back (the slice-2 boot bug). Registration hands us the live running module.
_server = None

# Injected by reference at registration (server's rulebook_system instance; never
# rebound, so the binding can't go stale and tests' _cache mutations stay visible).
rulebook_system = None


def _make_delegate(_name):
    """Build a call-time delegate to the running server.<_name> (keeps monkeypatches live)."""
    def _delegate(*args, **kwargs):
        return getattr(_server, _name)(*args, **kwargs)
    _delegate.__name__ = _name
    _delegate.__qualname__ = _name
    return _delegate


_DELEGATES = (
    "_load_characters",
    "_find_character",
    "_faction_clamp",
    "_load_factions",
    "_resolve_resistance_profile",
)
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n


def _get_bestiary_entry(name: str):
    """Find a bestiary entry by keyword/id (case-insensitive, parenthetical-tolerant). Returns the entry dict or None."""
    def norm(s):
        return str(s).lower().replace("(", "").replace(")", "").strip()
    target = norm(name)
    entries = (rulebook_system._cache or {}).get("bestiary", [])
    # exact keyword match first
    for e in entries:
        for kw in e.get("keywords", []):
            if norm(kw) == target:
                return e
    # id match
    for e in entries:
        if norm(e.get("id", "")).replace("creature-", "") == target.replace(" ", "-"):
            return e
    # partial keyword match
    for e in entries:
        for kw in e.get("keywords", []):
            if target in norm(kw) or norm(kw) in target:
                return e
    return None

def _lookup_creature_stats(
    creature_name: str = Field(description="Creature name from bestiary")
) -> str:
    """Get creature stat block from the canonical bestiary (rulebook/bestiary.json)."""
    entry = _get_bestiary_entry(creature_name)
    if not entry:
        return f"Creature '{creature_name}' not found in bestiary.json"
    s = entry.get("stats", {})
    name = (entry.get("keywords") or [creature_name])[0]
    lvl = s.get("level", s.get("hd", "?"))
    hp = s.get("hp", "?")
    av = s.get("av", s.get("av_natural", "?"))
    ml = s.get("morale", "?")
    ctype = s.get("type", s.get("types", "?"))
    attacks = "; ".join(
        f"{a.get('name','?')} ({a.get('damage','?')})" for a in s.get("attacks", [])
    ) or "-"
    prof = _resolve_resistance_profile(s)
    resist_bits = []
    if prof["immune"]:
        resist_bits.append("immune: " + ", ".join(prof["immune"]))
    if prof.get("minimum"):
        resist_bits.append("minimum (->1): " + ", ".join(prof["minimum"]))
    if prof["double"]:
        resist_bits.append("double: " + ", ".join(prof["double"]))
    if prof["half"]:
        resist_bits.append("half: " + ", ".join(prof["half"]))
    if prof["varies"]:
        resist_bits.append("resistances vary - referee's call")
    resist_line = " | ".join(resist_bits) or "none / type-default"
    # Structured combat flags surfaced for the DM
    extra = []
    if s.get("mystic_gift_immune"):
        extra.append("MYSTIC GIFTS DO NOT FUNCTION against this creature (psyche-suppressant).")
    if s.get("ranged_immune"):
        extra.append("RANGED-IMMUNE: forcefield negates ALL ranged attacks; melee only (DM-applied; engine can't see ranged vs melee).")
    if s.get("mimic"):
        extra.append("MIMIC: adopts the full stat block of the creature it copies.")
    if s.get("combat_note"):
        extra.append(s["combat_note"])
    extra_block = ("Combat flags:\n" + "\n".join(f"  * {x}" for x in extra) + "\n") if extra else ""
    specials = "\n".join(f"  - {x}" for x in s.get("special", [])) or "  - none"
    sep = "=" * 60
    return (
        f"{sep}\nCREATURE STATS - {str(name).upper()}\n{sep}\n"
        f"Type: {ctype}\n"
        f"LVL {lvl} ({hp}HP) / AV {av} / ML {ml}\n"
        f"ATK: {attacks}\n"
        f"Resistances: {resist_line}\n"
        f"{extra_block}"
        f"Special:\n{specials}\n"
        f"{sep}\nFOR CLAUDE'S REFERENCE ONLY - present narratively to player\n{sep}"
    )

def _roll_encounter_table(
    table_name: str = Field(description="Encounter table: 'Featureless Sands', 'Desert Canyon', 'Ruined City', 'Psychic Creatures', 'Alone and Dangerous', etc."),
    difficulty: str = Field(default="standard", description="Dice size: 'easy' (d6), 'standard' (d12), or 'hard' (d20)"),
    party_ego: int = Field(default=0, description="Highest party EGO bonus for reaction modifier")
) -> str:
    """Roll random encounter. Use during exploration, travel, or when party makes noise in dangerous area."""
    # Encounter tables - extracted from the Vaarn 2e bestiary pp.189-192
    TABLES = {
        "Featureless Sands": [
            "d10 Faa Nomads", "Trade Caravan", "d8 Greenguard", "d6 Lizard Lions",
            "Lithling Scholar", "d6 Iridium Vultures", "d6 Troika", "d8 Tumblesnares",
            "3d6 Pthalo-Jackals", "d6 Windweirds", "d8 Cacklemaw", "d20 Bandits",
            "Sandworm (Juvenile)", "Argent Shepherd", "d4 Leopard Worms", "d8 Anthrophagi",
            "d4 Giant Azure Scorpions", "Amaranthine Death-Worm", "Chrome-Feathered Sailback",
            "Sandworm (Adult)"
        ],
        "Desert Canyon": [
            "d10 Faa Nomads", "Harlequin Serpent", "3d6 Blue Baboons", "d6 Lizard Lions",
            "Lost NPC", "d10 Xeric Triffids", "d6 Tiger Flies", "d6 Cliff Ghuls",
            "3d6 Pthalo-Jackals", "d8 Nerve Crawlers", "d8 Cacklemaw", "d20 Bandits",
            "Sandworm (Juvenile)", "d4 Glass Tigers", "d4 Leopard Worms", "d6 Regenerators",
            "2d6 Eyeless Dogs", "Amaranthine Death-Worm", "Brood Mother", "Alzabo"
        ],
        "Garbage Waste": [
            "2d6 Yurlings", "d10 Xeric Triffids", "2d6 Unicorns", "d6 Voltworms",
            "d6 Gene Thieves", "d6 Mycomorphs", "d6 Tiger Flies", "d6 Cliff Ghuls",
            "d6 Quill-Spiders", "d8 Stumbling Drones", "Daggertrunk", "Xanthous Mycomorph",
            "Doppelgeller", "Bacterial Gestalt Colony", "d4 Walking Wombs", "d6 Regenerators",
            "d4 Pseudo-Giants", "Rustacean", "Brood Mother", "d3 Blightbeasts"
        ],
        "Ruined City": [
            "d10 Faa Nomads", "2d6 Yurlings", "2d6 Unicorns", "3d6 Blue Baboons",
            "d8 Stumbling Drones", "d8 Indigo Servitors", "2d6 Nomes", "d8 Greenguard",
            "d6 Battleboars", "d10 Zoanthropes", "d10 Grimpets", "2d6 Eyeless Dogs",
            "Subtle Stalker", "d4 Giant Azure Scorpions", "d4 Leopard Worms", "d6 Memory Eaters",
            "d4 Pseudo-Giants", "Chromavore", "Juggernaut", "Thunderstrike Bird"
        ],
        "Psychic Creatures": [
            "Bacterial Gestalt Colony", "d4 Doomsingers", "Extradimensional Mystic Hunter",
            "d4 Moonbeast Imagos", "Mystic", "Oblivion Obelisk", "Psyche Leech",
            "d6 Psy-Owls", "d4 Seekers of Eyeless Wisdom", "d6 Spambots", "Sphinx",
            "d6 Windweirds"
        ],
        "Small and Annoying": [
            "d8 Anthrophagi", "d4 Babble Birds", "3d6 Blue Baboons", "d6 Copy Cats",
            "Daggertrunk", "d8 Grey Crickets", "d8 Luxfoe Beetles", "2d6 Nomes",
            "3d6 Phthalo-Jackals", "2d8 Piranha Moles", "2d6 Unicorns", "2d6 Yurlings"
        ],
        "Alone and Dangerous": [
            "Alzabo", "Argent Shepherd", "Brood Mother", "Chernobog", "Chromavore",
            "Gravity Tyrant", "Kronophage", "Juggernaut", "Occulith", 
            "Quicksilver Exterminator", "Thermasaur", "Thunderstrike Bird"
        ],
        "Paradoxical Outsiders": [
            "d6 Deathblight Husks", "Entropy Wight", "d4 Faminebearers", "Fractalisk",
            "d4 Hollow Maidens", "Jollyhoss", "d8 Negativfolk", "2d6 Nomes",
            "Phase Panther", "d6 Planeyfolk", "d4 Scytheslivers", "Star Vampire"
        ],
        # New themed tables from pp.198-199
        "Ability Damage and Debuffs": [
            "Chromavore", "d3 Dessicators", "d6 Flabmongers", "d3 Grimweavers",
            "d4 Hollow Maidens", "d8 Memory Eaters", "Metamorphic Sludge", "d4 Moonbeast Imagos",
            "d6 Planeyfolk", "Psyche Leech", "d3 Spectres of Indifference", "Viridian Ooze"
        ],
        "Poison and Diseases": [
            "Amaranthine Death-Worm", "d3 Blightbeasts", "d3 Chimera", "d8 Cliff Ghuls",
            "d10 Grimpets", "Harlequin Serpent", "d3 Face Dancers", "d6 Gitchghasts",
            "d4 Maladaptors", "d8 Mycomorphs", "Pontiff Scorpion", "Tarantella"
        ],
        "Feral Pets": [
            "d6 Bonsai Triffids", "d6 Citrine-Coated Volt Rats", "Companion Ooze", "Exultant's Hawk",
            "d8 Glue Worms", "d6 KERBER-0S", "d8 Little Torinos", "d8 Mycomastiffs",
            "Pet Rock", "d6 Ray Cats", "2d6 Skunkeys", "Utility Snake"
        ],
        "Rogue Robots": [
            "d8 Anthrophagi", "Exemplar", "d4 Gladiator Synths", "d8 Greenguard",
            "d10 Grimpets", "Juggernaut", "d6 Spambots", "d8 Stumbling Drones",
            "Subtle Stalker", "d8 Synth Skeletons", "Turretwright", "d6 Voltworms"
        ],
        "Hegemony Patrols": [
            "2d10 Conscripts + Ordinator", "d8 Legionaries", "d6 Rangers", "d8 Legionaries + Centurion",
            "d8 Legionaries + Suppressor", "d8 Legionaries + d4 War Camels", "d6 Rangers + d10 Faa Nomads",
            "d8 Legionaries + Ordinator", "d8 Legionaries + Stilt Strutter", "d4 Myrmidons",
            "d4 Myrmidons + Suppressor", "Ornithopter"
        ]
    }
    
    # Activity table (2d6)
    ACTIVITY = {
        2: "In Combat (roll again for opponent)",
        3: "Sleeping / Resting",
        4: "Hiding",
        5: "Chasing / Fleeing (roll again for quarry/pursuer)",
        6: "Hunting / Eating",
        7: "Patrolling / Travelling",
        8: "Relaxing / Basking",
        9: "Squabbling / Infighting",
        10: "Excreting / Venting",
        11: "Injured / Malfunctioning",
        12: "Trance / Religious Ritual"
    }
    
    # Reaction table (d20 + EGO)
    def get_reaction(roll_result):
        if roll_result <= 3:
            return "Attacks Immediately"
        elif roll_result <= 6:
            return "Hostile, Can't Be Swayed"
        elif roll_result <= 9:
            return "Hostile, Could Be Swayed"
        elif roll_result <= 13:
            return "Wary, Defensive"
        elif roll_result <= 16:
            return "Uninterested"
        elif roll_result <= 20:
            return "Curious, Approachable"
        else:
            return "Actively Helpful"
    
    # Validate table name
    if table_name not in TABLES:
        available = ", ".join(TABLES.keys())
        return f"ERROR: Unknown table '{table_name}'. Available tables: {available}"
    
    # Determine dice size based on difficulty
    dice_map = {
        "easy": 6,
        "standard": 12,
        "hard": 20
    }
    
    if difficulty not in dice_map:
        return f"ERROR: Unknown difficulty '{difficulty}'. Use: easy, standard, or hard"
    
    dice_size = dice_map[difficulty]
    table = TABLES[table_name]
    
    # Roll on encounter table
    max_roll = min(dice_size, len(table))
    encounter_roll = dice.roll(sides=max_roll, num_dice=1)['total']
    creature_entry = table[encounter_roll - 1]
    
    # Parse quantity dice if present
    quantity = 1
    creature_name = creature_entry
    
    if creature_entry[0].isdigit() or creature_entry.startswith('d'):
        # Has quantity dice like "d6 Lizard Lions" or "3d6 Blue Baboons"
        parts = creature_entry.split(' ', 1)
        dice_notation = parts[0]
        creature_name = parts[1] if len(parts) > 1 else creature_entry
        
        # Roll quantity dice using roll_notation for string parsing
        if 'd' in dice_notation:
            quantity = dice.roll_notation(dice_notation)['total']
    
    # Roll activity (2d6)
    activity_roll = dice.d6() + dice.d6()
    activity = ACTIVITY[activity_roll]
    
    # Roll reaction (d20 + party EGO)
    reaction_roll = dice.d20() + party_ego
    reaction = get_reaction(reaction_roll)
    
    # Format output for Claude's DM screen
    output = f"""{'='*60}
ENCOUNTER ROLL - {table_name.upper()} ({difficulty})
{'='*60}

TABLE ROLL: {encounter_roll} (d{dice_size})
CREATURE: {creature_name}
QUANTITY: {quantity}

ACTIVITY ROLL: {activity_roll} (2d6)
ACTIVITY: {activity}

REACTION ROLL: {reaction_roll} (d20+{party_ego} EGO)
REACTION: {reaction}

{'='*60}
NEXT STEP: Use lookup(action='creature', query="{creature_name}") for combat stats
{'='*60}"""
    
    return output

def _roll_reaction(
    character_ego: int = 0,
    can_communicate: bool = True,
    advantage: bool = False,
    disadvantage: bool = False,
    modifier_note: str = "",
) -> str:
    """Roll d20 + EGO on the book's 4-band Reactions table (CH p.36).

    Bands: 1-7 Negative / 8-15 Indifferent / 16-20 Positive / 21+ Actively Helpful.
    ADV (2d20 take-higher) / DIS (take-lower) come from traits + faction standing;
    the caller passes the NET (they cancel 1:1 upstream).
    """
    def _one():
        return dice.d20()
    if advantage and not disadvantage:
        raw = max(_one(), _one())
        adv_note = " ADV"
    elif disadvantage and not advantage:
        raw = min(_one(), _one())
        adv_note = " DIS"
    else:
        raw = _one()
        adv_note = ""
    ego = character_ego if can_communicate else 0
    roll = raw + ego
    note = (f"(d20{adv_note}+{ego} EGO)" if can_communicate
            else f"(d20{adv_note}, no communication)")
    if roll <= 7:
        reaction = "Negative"
        description = "Predators and martial creatures attack; prey animals flee."
    elif roll <= 15:
        reaction = "Indifferent"
        description = "Wary but uninterested in conflict."
    elif roll <= 20:
        reaction = "Positive"
        description = "Will allow approach; intelligent creatures willing to trade."
    else:
        reaction = "Actively Helpful"
        description = "Will help the PCs; may give gifts or reveal secrets."
    mod_line = f"\nMODIFIERS: {modifier_note}" if modifier_note else ""
    return (f"{'='*60}\nREACTION ROLL - VAARN 2E (p.36)\n{'='*60}\n\n"
            f"ROLL: {roll} {note}\nREACTION: {reaction}\n\n{description}{mod_line}\n\n"
            f"{'='*60}\nDM REFERENCE - present narratively\n{'='*60}")

def _faction_rep(slug: str) -> int:
    """Current integer REP for a faction slug (0 if absent/unknown)."""
    try:
        led = _load_factions()
        rec = led.get("factions", {}).get(slug, {})
        return _faction_clamp(rec.get("rep", 0))
    except Exception:
        return 0

def _reaction_modifiers(char: dict, vs_ancestry: str = None, vs_faction: str = None):
    """(adv_count, dis_count, notes[]) from ancestry rules + augmentations + faction band.

    Reads STRUCTURED `reaction` specs ({"adv"/"dis": "all" | {"vs_ancestry": "<slug>"}})
    minted on ancestry special_rules and on character augmentations. ADV/DIS counts are
    returned raw; the caller nets them (they cancel 1:1) before calling _roll_reaction.
    """
    adv = dis = 0
    notes = []
    _vsanc = vs_ancestry.lower() if vs_ancestry else None

    def _apply(spec, source):
        nonlocal adv, dis
        if not isinstance(spec, dict):
            return
        for key, is_adv in (("adv", True), ("dis", False)):
            cond = spec.get(key)
            if cond is None:
                continue
            ok = (cond == "all"
                  or (isinstance(cond, dict) and cond.get("vs_ancestry")
                      and _vsanc and cond["vs_ancestry"].lower() == _vsanc))
            if ok:
                if is_adv:
                    adv += 1
                else:
                    dis += 1
                notes.append(f"{source} ({key.upper()})")

    # Ancestry special_rules (ancestry field, falling back to species)
    anc = (char.get("ancestry") or char.get("species") or "").lower().strip()
    _adict = getattr(_ancestries, "ANCESTRIES", {})
    for rule in _adict.get(anc, {}).get("special_rules", []):
        if rule.get("reaction"):
            _apply(rule["reaction"], rule.get("name", "ancestry"))

    # Augmentations (dict keyed by ability slot; each a dict that may carry a reaction spec)
    for _slot, aug in (char.get("augmentations") or {}).items():
        if isinstance(aug, dict) and aug.get("reaction"):
            _apply(aug["reaction"], aug.get("name", "augmentation"))

    # Faction standing band
    if vs_faction:
        band = _factions.standing_for(_faction_rep(vs_faction.lower()))
        if band.get("reaction") == "ADV":
            adv += 1
            notes.append(f"{vs_faction} standing (ADV)")
        elif band.get("reaction") == "DIS":
            dis += 1
            notes.append(f"{vs_faction} standing (DIS)")

    return adv, dis, notes

def _roll_reaction_for_character(character: str, can_communicate: bool = True,
                                 vs_ancestry: str = None, vs_faction: str = None,
                                 character_ego: int = 0) -> str:
    """Resolve a named character's EGO + net ADV/DIS, then roll their reaction.

    Used by roll(action="reaction", character=...). Falls back to the passed
    character_ego if the sheet can't be loaded. Returns the _roll_reaction output.
    """
    ego = character_ego
    char = None
    data, err = _load_characters()
    if not err and data:
        _k, char = _find_character(data, character)
        if char:
            _ego = char.get("abilities", {}).get("EGO", {})
            ego = (int(_ego.get("current", character_ego)) if isinstance(_ego, dict)
                   else int(_ego or character_ego))
    if not char:
        return _roll_reaction(character_ego=ego, can_communicate=can_communicate)
    adv, dis, notes = _reaction_modifiers(char, vs_ancestry=vs_ancestry, vs_faction=vs_faction)
    return _roll_reaction(
        character_ego=ego, can_communicate=can_communicate,
        advantage=(adv > dis), disadvantage=(dis > adv),
        modifier_note="; ".join(notes),
    )



_INJECTED = ("rulebook_system",)


def register_bestiary_encounter(srv):
    """Bind the live server module + inject the rulebook_system instance."""
    global _server
    _server = srv
    g = globals()
    for _name in _INJECTED:
        g[_name] = getattr(srv, _name)
