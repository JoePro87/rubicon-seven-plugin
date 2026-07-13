# wounds.py
"""Pure Vaarn wound primitives: book tables (structured), record building,
derived-effects aggregation, forced-drop math. No game state, no I/O — shared
by server.py and the hooks. Counterpart to item_slots.py / dice_chain.py.

Storage rule (the spec's core): 'until fixed' / state effects are DERIVED from
the active records by derived_effects() and never written to the sheet; rolled
ability/max-HP/level damage is MUTATED once by server-side appliers.

Table authority: extraction batch_03_combat_weapons.md p.38 (Biological) and
p.39 (Synthetic). The old server.py SYNTHETIC_WOUNDS was fabricated — this
module's Synthetic table is the book-real one.
"""
import random

BIOLOGICAL_WOUNDS = {
    0:  {"name": "Knocked Out", "slots": 0, "special": "knocked_out",
         "effect": "CON save vs unconscious d6 rounds; while unconscious all attacks auto-hit"},
    -1: {"name": "Damaged Item", "slots": 0, "special": "damaged_item",
         "effect": "An item is damaged and unusable until fixed (d20 for the slot affected)"},
    -2: {"name": "Bloody Mouth", "slots": 1, "effect": "Your mouth drools blood and your speech slurs"},
    -3: {"name": "Teeth Knocked Out", "slots": 1, "dis_saves": ["EGO"], "effect": "DIS on EGO saves"},
    -4: {"name": "Scrambled Nerves", "slots": 1, "dis_saves": ["PSY"], "effect": "DIS on PSY saves"},
    -5: {"name": "Addling Wound", "slots": 1, "dis_saves": ["INT"], "effect": "DIS on INT saves"},
    -6: {"name": "Stomach Wound", "slots": 1, "dis_saves": ["CON"], "effect": "DIS on CON saves"},
    -7: {"name": "Crippling Wound", "slots": 1, "dis_saves": ["DEX"], "effect": "DIS on DEX saves"},
    -8: {"name": "Weakening Wound", "slots": 1, "dis_saves": ["STR"], "effect": "DIS on STR saves"},
    -9: {"name": "Bloody Gash", "slots": 1, "max_hp_damage": "d8", "effect": "-d8 max HP"},
    -10: {"name": "Major Fracture", "slots": 2, "effect": "-d6 STR and -d6 DEX",
          "ability_damage": {"STR": "d6", "DEX": "d6"}},
    -11: {"name": "Lost an Eye", "slots": 2, "effect": "-d6 DEX and -d6 EGO",
          "ability_damage": {"DEX": "d6", "EGO": "d6"}},
    -12: {"name": "Cracked Skull", "slots": 2, "effect": "-d8 INT and -d8 PSY. Pass out.",
          "ability_damage": {"INT": "d8", "PSY": "d8"}, "unconscious": True},
    -13: {"name": "Mangled Guts", "slots": 2, "effect": "-d8 CON and -d10 max HP. Pass out.",
          "ability_damage": {"CON": "d8"}, "max_hp_damage": "d10", "unconscious": True},
    -14: {"name": "Severed Hand", "slots": 2, "effect": "-d8 STR, -d8 DEX. Pass out.",
          "ability_damage": {"STR": "d8", "DEX": "d8"}, "unconscious": True},
    -15: {"name": "Severed Arm", "slots": 3, "effect": "-10 STR, -10 DEX. Pass out.",
          "ability_damage": {"STR": 10, "DEX": 10}, "unconscious": True},
    -16: {"name": "Severed Leg", "slots": 3, "effect": "-10 STR, -10 DEX. Pass out.",
          "ability_damage": {"STR": 10, "DEX": 10}, "unconscious": True},
    -17: {"name": "Braindead", "slots": 3, "effect": "-10 INT, -10 PSY, -10 EGO. Pass out.",
          "ability_damage": {"INT": 10, "PSY": 10, "EGO": 10}, "unconscious": True},
    -18: {"name": "Bloody Mess", "slots": 0, "special": "bloody_mess", "unconscious": True,
          "effect": "Roll 3 random Wounds using 3d6 (slots come from the rolled wounds). Pass out."},
    -19: {"name": "Death's Door", "slots": 5, "deaths_door": True, "unconscious": True,
          "effect": "Any further damage is LETHAL until this wound is healed. Pass out."},
    -20: {"name": "FATALITY", "slots": 0, "dead": True, "effect": "CHARACTER IS DEAD"},
}

SYNTHETIC_WOUNDS = {
    # Transcribed from extraction batch_03 p.39 — see the spec §2 table.
    0:  {"name": "Update Required", "slots": 0, "special": "knocked_out",
         "effect": "CON save vs unconscious d6 rounds; while unconscious all attacks auto-hit"},
    -1: {"name": "Damaged Item", "slots": 0, "special": "damaged_item",
         "effect": "An item is damaged and unusable until fixed (d20 for the slot affected)"},
    -2: {"name": "Supercoolant Leak", "slots": 1, "deprived": True,
         "effect": "Deprived; cannot regain HP until this Wound is fixed"},
    -3: {"name": "Ego-Engine Stutter", "slots": 1, "ability_damage": {"EGO": "d4"}, "effect": "-d4 EGO"},
    -4: {"name": "Quantum-Reasoning Overflow", "slots": 1, "ability_damage": {"PSY": "d4"}, "effect": "-d4 PSY"},
    -5: {"name": "Memory Crystal Fracture", "slots": 1, "ability_damage": {"INT": "d4"}, "effect": "-d4 INT"},
    -6: {"name": "Coolant Loop Overheat", "slots": 1, "ability_damage": {"CON": "d4"}, "effect": "-d4 CON"},
    -7: {"name": "Kinesthetics Drive Failure", "slots": 1, "ability_damage": {"DEX": "d4"}, "effect": "-d4 DEX"},
    -8: {"name": "Limb Hydraulics Compromised", "slots": 1, "ability_damage": {"STR": "d4"}, "effect": "-d4 STR"},
    -9: {"name": "Synthskin Damaged", "slots": 2, "av_penalty_die": "d4", "double_damage": True,
         "effect": "-d4 AV; suffer double damage"},
    -10: {"name": "Incompatible Motion Interface", "slots": 2,
          "until_fixed_ability": {"STR": "d6", "DEX": "d6"}, "effect": "-d6 STR and -d6 DEX until fixed"},
    -11: {"name": "Personality Nexus Scrambled", "slots": 2, "reroll_abilities": ["INT", "PSY", "EGO"],
          "effect": "Reroll INT, PSY and EGO; voice and personality altered"},
    -12: {"name": "Vischip Disabled", "slots": 3, "blind": True,
          "effect": "Blind: cannot make ranged attacks; melee attacks at DIS"},
    -13: {"name": "Cascading Kinesthetics Debilitation", "slots": 3, "daily_tick": {"STR": 2, "DEX": 2},
          "effect": "Lose 2 STR and 2 DEX per day"},
    -14: {"name": "Emotive Language Export Corruption", "slots": 4,
          "effect": "Emotions/speech encrypted — do not match what you intend"},
    -15: {"name": "Infinite Practical Memory Loop", "slots": 4, "duration": "d6 hours",
          "effect": "Repeat your last action step by step for the next d6 hours"},
    -16: {"name": "Motive Drive Inhibited", "slots": 5, "unconscious": True, "duration": "d6 hours",
          "ability_damage": {"STR": 10, "DEX": 10, "CON": 10}, "effect": "-10 STR/DEX/CON; shut down d6 hours"},
    -17: {"name": "Personality Nexus Damaged", "slots": 5, "unconscious": True, "duration": "d6 hours",
          "ability_damage": {"INT": 10, "PSY": 10, "EGO": 10}, "effect": "-10 INT/PSY/EGO; shut down d6 hours"},
    -18: {"name": "Terminal Memory Crystal Corruption", "slots": 6, "level_loss": True,
          "effect": "Lose one Level and all XP — permanent even when this Wound is fixed"},
    -19: {"name": "General Systems Failure", "slots": 0, "dead": True, "ego_engine_salvageable": True,
          "effect": "Dead; if the Ego Engine is removed it can be installed in a new shell"},
    -20: {"name": "Ego-Engine Destroyed", "slots": 0, "dead": True,
          "effect": "Dead permanently; the Ego Engine cannot be rebooted"},
}


def wound_for_hp(hp: int, table: dict) -> dict:
    """The table entry for damage landing at hp (call only when hp <= 0); clamps at -20."""
    return table[max(int(hp), -20)]


def _roll_notation(notation, rng):
    """'d6' -> rng(1,6); ints pass through."""
    if isinstance(notation, int):
        return notation
    return rng(1, int(str(notation).lstrip("dD")))


def roll_wound_record(hp: int, entry: dict, rng=random.randint) -> dict:
    """Build the persistent wound record. Rolled-once magnitudes for DERIVED
    effects (av_penalty, until-fixed penalties, durations) are rolled here and
    stored ON the record; MUTATION rolls (ability_damage/max_hp_damage) are NOT
    rolled here — the server appliers own those."""
    rec = {"name": entry["name"], "hp_threshold": hp,
           "slots": entry.get("slots", 0) or 0, "effect": entry["effect"]}
    for flag in ("special", "deprived", "double_damage", "blind",
                 "deaths_door", "unconscious", "dead", "level_loss",
                 "ego_engine_salvageable"):
        if entry.get(flag):
            rec[flag] = entry[flag]
    if entry.get("dis_saves"):
        rec["dis_saves"] = list(entry["dis_saves"])
    if entry.get("daily_tick"):
        rec["daily_tick"] = dict(entry["daily_tick"])
    if entry.get("av_penalty_die"):
        rec["av_penalty"] = _roll_notation(entry["av_penalty_die"], rng)
    if entry.get("until_fixed_ability"):
        rec["until_fixed_penalty"] = {k: _roll_notation(v, rng)
                                      for k, v in entry["until_fixed_ability"].items()}
    if entry.get("duration"):
        die, _, unit = entry["duration"].partition(" ")
        n = _roll_notation(die, rng)
        rec["duration"] = f"{n} {unit or 'rounds'}"   # 'd6 hours' -> '4 hours'
    if entry.get("special") == "knocked_out":
        rec["pending_con_save"] = True
    return rec


def derived_effects(wound_records: list) -> dict:
    """Aggregate every derived (non-mutated) effect from active records.
    Legacy/minimal records contribute nothing structured (graceful).

    NOTE: two renderers hand-enumerate these keys -- server._wound_status_lines
    and hooks/phrase_reminder._wound_parens (+ its owed flags). Adding a key
    here means adding a line THERE, or the new effect silently never surfaces."""
    eff = {"dis_saves": [], "deprived": False, "no_hp_regain": False,
           "av_penalty": 0, "av_bonus": 0, "double_damage": False, "blind": False,
           "unconscious": False, "deaths_door": False,
           "pending_con_save": False, "daily_tick": {}, "notes": []}
    dis = set()
    for r in wound_records or []:
        if not isinstance(r, dict):
            continue
        dis.update(r.get("dis_saves") or [])
        if r.get("until_fixed_penalty"):
            eff["notes"].append(f"{r.get('name', '?')}: " + ", ".join(
                f"-{v} {k}" for k, v in r["until_fixed_penalty"].items()) + " (until fixed)")
        if r.get("deprived"):
            eff["deprived"] = True
            eff["no_hp_regain"] = True
        eff["av_penalty"] += r.get("av_penalty", 0)
        eff["av_bonus"] += r.get("av_bonus", 0)
        eff["double_damage"] = eff["double_damage"] or bool(r.get("double_damage"))
        eff["blind"] = eff["blind"] or bool(r.get("blind"))
        eff["unconscious"] = eff["unconscious"] or bool(r.get("unconscious"))
        eff["deaths_door"] = eff["deaths_door"] or bool(r.get("deaths_door"))
        eff["pending_con_save"] = eff["pending_con_save"] or bool(r.get("pending_con_save"))
        for k, v in (r.get("daily_tick") or {}).items():
            eff["daily_tick"][k] = eff["daily_tick"].get(k, 0) + v
    eff["dis_saves"] = sorted(dis)
    return eff


def forced_drop_slots(gear_load: int, cap: int, wound_slots: int) -> int:
    """Joe ruling 2026-06-09: wounds evict gear. Gear room = cap - wound_slots;
    the excess must be dropped (player chooses what). 0 = nothing owed."""
    return max(0, gear_load - max(0, cap - wound_slots))
