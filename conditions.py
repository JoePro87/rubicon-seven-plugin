# conditions.py
"""Pure persistent-condition primitives (E1): record validation and derived
condition effects. Sibling of wounds.py/survival.py -- records persist on the
sheet, effects derive on read, server-side appliers own mutations. No game
state, no I/O.

Spec: docs/superpowers/specs/2026-06-11-status-framework-design.md
(rulings R-E1a..h). Book authority: extraction batch_03 p.37 (Deprivation),
batch_08 p.228 (Virulence saves = 10 + rating), batch_08 p.229 (Resurrection
and Death -- the five paths), batch_02 p.15 (photosynthesis, Flammable).
"""
import re

ABILITIES = ("STR", "DEX", "CON", "INT", "PSY", "EGO")
CADENCES = ("round", "day", "week")
_DICE_RX = re.compile(r"^\d*[dD]\d+([+-]\d+)?$")


def _is_dice(v) -> bool:
    return isinstance(v, str) and bool(_DICE_RX.match(v.strip()))


def _is_amount(v) -> bool:
    """A plain positive integer (1, "1", "3") - accepted anywhere dice notation
    is, for flat per-tick drains. Zero and negatives are rejected."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v > 0
    if isinstance(v, str):
        s = v.strip()
        return s.isdigit() and int(s) > 0
    return False


def _norm_drain(v):
    """Normalize a dice string or flat int into a stored str, or None if neither."""
    if _is_dice(v):
        return v.strip().lower()
    if _is_amount(v):
        return str(int(v)) if isinstance(v, (int, float)) else str(int(v.strip()))
    return None


def normalize_record(req: dict, day: int) -> tuple:
    """Validate an apply request into a stored condition record.
    Returns (record, "") or (None, error). Unknown top-level keys are
    dropped silently (forward-compatible reads, strict writes)."""
    if not isinstance(req, dict) or not str(req.get("name") or "").strip():
        return None, "A condition needs at least a name."
    rec = {"name": str(req["name"]).strip(), "since_day": day}
    if str(req.get("cause") or "").strip():
        rec["cause"] = str(req["cause"]).strip()
    if str(req.get("note") or "").strip():
        rec["note"] = str(req["note"]).strip()
    if req.get("death_day") is not None:
        try:
            rec["death_day"] = int(req["death_day"])
        except (TypeError, ValueError):
            return None, "death_day must be an integer campaign day."
    if req.get("until_day") is not None:
        # B2: day-limited conditions ("Blindness for d8 days") auto-expire
        # once the campaign day passes until_day (advance_day sweep).
        try:
            rec["until_day"] = int(req["until_day"])
        except (TypeError, ValueError):
            return None, "until_day must be an integer campaign day."
    eff_in = req.get("effects")
    if eff_in is None:
        eff_in = {}
    elif not isinstance(eff_in, dict):
        return None, "effects must be an object/dict."
    eff = {}
    if eff_in.get("no_hp_regain"):
        eff["no_hp_regain"] = True
    if eff_in.get("hp_regain_half"):
        eff["hp_regain_half"] = True
    if eff_in.get("double_rations"):
        eff["double_rations"] = True
    if eff_in.get("dis_saves"):
        if not isinstance(eff_in["dis_saves"], (list, tuple)):
            return None, "effects.dis_saves must be a list of abilities."
        saves = [str(s).strip().upper() for s in eff_in["dis_saves"] if str(s).strip()]
        bad = [s for s in saves if s not in ABILITIES]
        if bad:
            return None, f"dis_saves must be abilities {ABILITIES}; got {bad}."
        eff["dis_saves"] = saves
    tw = eff_in.get("twinned")
    if tw is None:
        tw = {}
    elif not isinstance(tw, dict):
        return None, "effects.twinned must be an object/dict."
    if tw.get("partner"):
        eff["twinned"] = {"partner": str(tw["partner"]).strip()}
    if eff:
        rec["effects"] = eff
    tick = req.get("tick")
    if tick is None:
        tick = {}
    elif not isinstance(tick, dict):
        return None, "tick must be an object/dict."
    if tick:
        cadence = str(tick.get("cadence") or "").strip().lower()
        if cadence not in CADENCES:
            return None, f"tick.cadence must be one of {CADENCES}."
        t = {"cadence": cadence}
        if tick.get("hp") is not None:
            norm_hp = _norm_drain(tick["hp"])
            if norm_hp is None:
                return None, f"tick.hp must be dice notation or a positive integer: got {tick['hp']!r}."
            t["hp"] = norm_hp
        if tick.get("max_hp") is not None:
            norm_mhp = _norm_drain(tick["max_hp"])
            if norm_mhp is None:
                return None, f"tick.max_hp must be dice notation or a positive integer: got {tick['max_hp']!r}."
            t["max_hp"] = norm_mhp
        ab = tick.get("abilities") or {}
        if ab:
            if not isinstance(ab, dict):
                return None, 'tick.abilities must be an object like {"STR": "d4"}.'
            norm = {}
            for k, v in ab.items():
                ku = str(k).strip().upper()
                if ku not in ABILITIES:
                    return None, f"tick.abilities key {k!r} is not an ability."
                norm_ab = _norm_drain(v)
                if norm_ab is None:
                    return None, f"tick.abilities[{ku}] must be dice notation or a positive integer: got {v!r}."
                norm[ku] = norm_ab
            t["abilities"] = norm
        if "hp" not in t and "abilities" not in t and "max_hp" not in t:
            return None, "tick needs hp, abilities, or max_hp drain dice/amount."
        if cadence == "round" and "hp" not in t:
            return None, ("round-cadence ticks require tick.hp (use day/week "
                          "cadence for ability-drain or max-HP conditions).")
        sv = tick.get("save")
        if sv is not None:
            if not isinstance(sv, dict):
                return None, "tick.save must be an object/dict {ability, dc}."
            s_ab = str(sv.get("ability") or "").strip().upper()
            if s_ab not in ABILITIES:
                return None, f"tick.save.ability must be one of {ABILITIES}."
            try:
                s_dc = int(sv.get("dc"))
            except (TypeError, ValueError):
                return None, "tick.save.dc must be an integer."
            t["save"] = {"ability": s_ab, "dc": s_dc}
        if tick.get("label"):
            t["label"] = str(tick["label"]).strip()
        rec["tick"] = t
    ste = req.get("save_to_end")
    if ste is None:
        ste = {}
    elif not isinstance(ste, dict):
        return None, "save_to_end must be an object/dict."
    if ste:
        ability = str(ste.get("ability") or "").strip().upper()
        if ability not in ABILITIES:
            return None, f"save_to_end.ability must be one of {ABILITIES}."
        try:
            dc = int(ste.get("dc"))
        except (TypeError, ValueError):
            return None, "save_to_end.dc must be an integer."
        rec["save_to_end"] = {"ability": ability, "dc": dc}
    omz = req.get("on_max_hp_zero")
    if omz is not None:
        if not isinstance(omz, dict):
            return None, "on_max_hp_zero must be an object/dict {death_in_days}."
        try:
            d_in = int(omz.get("death_in_days"))
        except (TypeError, ValueError):
            return None, "on_max_hp_zero.death_in_days must be an integer."
        if d_in <= 0:
            return None, "on_max_hp_zero.death_in_days must be a positive integer."
        if "max_hp" not in (rec.get("tick") or {}):
            return None, ("on_max_hp_zero requires tick.max_hp "
                          "(the clock fires when max HP reaches 0).")
        rec["on_max_hp_zero"] = {"death_in_days": d_in}
    if req.get("until_turn") is not None:
        # B3: Exploration-Turn elixir durations expire on the vault map's
        # current_turn (map_system.advance_turns sweep). turn_map names the
        # map whose counter governs.
        try:
            rec["until_turn"] = int(req["until_turn"])
        except (TypeError, ValueError):
            return None, "until_turn must be an integer vault turn."
        if str(req.get("turn_map") or "").strip():
            rec["turn_map"] = str(req["turn_map"]).strip()
    if req.get("hp_floor") is not None:
        # B3 R-B3d: Immortality Injector floor (damage cannot reduce below -19).
        try:
            rec["hp_floor"] = int(req["hp_floor"])
        except (TypeError, ValueError):
            return None, "hp_floor must be an integer."
    if isinstance(req.get("revert"), dict):
        # B3: snapshot for clean expiry of ability_mod/hp_floor elixirs.
        rec["revert"] = req["revert"]
    if isinstance(req.get("derived_effects"), dict):
        # B3: condition-side AV bonus, read by server._defender_av.
        deff = {}
        if req["derived_effects"].get("av_bonus") is not None:
            try:
                deff["av_bonus"] = int(req["derived_effects"]["av_bonus"])
            except (TypeError, ValueError):
                return None, "derived_effects.av_bonus must be an integer."
        if deff:
            rec["derived_effects"] = deff
    return rec, ""


def _apply_revert(char: dict, rec: dict) -> None:
    """B3: undo an elixir's stamped snapshot. HP is a dict
    {"current": N, "max": N}; restored current = min(live, snapshot)
    -- expiry must never HEAL. Also disarms any trigger the elixir armed
    (Spineskin)."""
    # B3 R-B3d (adversarial HIGH): when a Deathless record expires, a sub-floor
    # HP written while immortal (e.g. update_hp to -25) must be raised UP to the
    # floor, or it auto-kills on the very next death check. Raise-only (a heal
    # is impossible here -- the floor is always <= 0 and we only ever lift a
    # value that sits BELOW it).
    if rec.get("hp_floor") is not None:
        hp = char.get("hp")
        if isinstance(hp, dict):
            try:
                floor = int(rec["hp_floor"])
                hp["current"] = max(int(hp.get("current", floor)), floor)
            except (TypeError, ValueError):
                pass
    rev = rec.get("revert")
    if not isinstance(rev, dict):
        return
    if isinstance(rev.get("abilities"), dict):
        char.setdefault("abilities", {}).update(rev["abilities"])
    hp = char.get("hp")
    if isinstance(hp, dict):
        if rev.get("hp_max") is not None:
            hp["max"] = rev["hp_max"]
        if rev.get("hp_current") is not None:
            hp["current"] = min(hp.get("current", rev["hp_current"]),
                                rev["hp_current"])
    if rev.get("remove_trigger"):
        trigs = (char.get("special_traits") or {}).get("triggers") or []
        char["special_traits"]["triggers"] = [
            t for t in trigs if t.get("label") != rev["remove_trigger"]]


def expire_turn_conditions(char: dict, map_name: str, current_turn: int) -> list:
    """B3: clear conditions whose until_turn has passed on THIS map.

    Mutates char in place (caller persists). Applies any `revert` snapshot
    so ability_mod/trigger elixirs end cleanly. Returns the cleared records
    (for wear-off lines)."""
    conds = char.get("conditions") or []
    expired = [c for c in conds
               if isinstance(c.get("until_turn"), int)
               and c.get("turn_map") == map_name
               and current_turn >= c["until_turn"]]
    if not expired:
        return []
    char["conditions"] = [c for c in conds if c not in expired]
    for c in expired:
        _apply_revert(char, c)
    return expired


def expire_day_conditions(char: dict, new_day: int) -> list:
    """B2/B3: clear conditions whose until_day has passed; apply reverts so a
    turn-duration elixir that outlives its vault still restores stats at the
    day failsafe (same _apply_revert the turn sweep uses)."""
    conds = char.get("conditions") or []
    expired = [c for c in conds
               if isinstance(c.get("until_day"), int)
               and new_day > c["until_day"]]
    if expired:
        char["conditions"] = [c for c in conds if c not in expired]
        for c in expired:
            _apply_revert(char, c)
    return expired


def condition_effects(conditions) -> dict:
    """Aggregate derived effects from condition records. Tolerant of garbage,
    read-only. Superset of the S1 scaffold's keys -- existing Deprived records
    (name match, no effects dict) keep their exact S1 behavior; `dying` stays
    Deprived-only (its consumers render 'DEPRIVED:' labels); generic clocks
    land in `death_clocks`. week-cadence ticks land in day_ticks; consumers
    MUST check entry['cadence'] to fire at the right frequency (the
    advance_day tick does)."""
    eff = {"deprived": False, "no_hp_regain": False,
           "hp_regain_half": False, "double_rations": False,
           "deprived_causes": [], "dying": [],
           "dis_saves": [], "twinned_partner": None,
           "round_ticks": [], "day_ticks": [],
           "save_to_end": [], "death_clocks": [], "active": 0}
    dis = set()
    for c in conditions or []:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            continue
        eff["active"] += 1
        name = c["name"]
        if name == "Deprived":
            eff["deprived"] = True
            eff["no_hp_regain"] = True
            eff["deprived_causes"].append(c.get("cause", "?"))
            eff["dying"].append((c.get("cause", "?"), c.get("death_day")))
        elif isinstance(c.get("death_day"), int):
            label = name + (f" ({c['cause']})" if c.get("cause") else "")
            eff["death_clocks"].append((label, c["death_day"]))
        e = c.get("effects") or {}
        if isinstance(e, dict):
            if e.get("no_hp_regain"):
                eff["no_hp_regain"] = True
            if e.get("hp_regain_half"):
                eff["hp_regain_half"] = True
            if e.get("double_rations"):
                eff["double_rations"] = True
            for s in e.get("dis_saves") or []:
                if str(s).strip().upper() in ABILITIES:
                    dis.add(str(s).strip().upper())
            tw = e.get("twinned") or {}
            if isinstance(tw, dict) and tw.get("partner"):
                eff["twinned_partner"] = str(tw["partner"])
        t = c.get("tick") or {}
        if isinstance(t, dict) and t.get("cadence") in CADENCES:
            entry = {"name": name, "cadence": t["cadence"],
                     "hp": t.get("hp"), "abilities": t.get("abilities") or {},
                     "max_hp": t.get("max_hp"), "save": t.get("save"),
                     "label": t.get("label") or name,
                     "since_day": c.get("since_day", 0),
                     "on_max_hp_zero": c.get("on_max_hp_zero")}
            (eff["round_ticks"] if t["cadence"] == "round"
             else eff["day_ticks"]).append(entry)
        ste = c.get("save_to_end") or {}
        if isinstance(ste, dict) and ste.get("ability") and ste.get("dc") is not None:
            try:
                eff["save_to_end"].append((name, str(ste["ability"]).upper(), int(ste["dc"])))
            except (TypeError, ValueError):
                pass
    eff["dis_saves"] = sorted(dis)
    return eff


# --- Resurrection and Death (book p.229, R-E1e): pushed on every real PC death ---

RESURRECTION_PATHS = [
    'RESURRECTION & DEATH (book p.229) - the five paths back; quote, never invent:',
    '  1. Mycomorph Spores: a Mycomorph seeds the corpse; reborn as a Mycomorph in d4 days; INT save - pass keeps memories/Level/Gifts/abilities, fail = effectively a new Level 1 Mycomorph carrying the same items.',
    '  2. Necrotech: implant/nanomachine resurrection; always a severe downside (DM rules it); a biological brought back now ALSO counts as Synthetic-type.',
    '  3. Pseudo-Womb: clone from a flesh scrap; 7 days incubation; CON save - pass = exact copy, fail = roll two new mutations.',
    '  4. Spirit: roll d20 + Level >= 16 to return as an unquiet spirit (incorporeal; spend d6 HP to touch the world, d6 + target Level HP to possess for one exploration turn; at 0 HP fades until next sunrise).',
    '  5. Ego-Engine Transplant (Synths): core into a new synthetic body; restart Level 1, reroll STR/DEX/CON, keep INT/PSY/EGO.',
    'After a successful path: affliction(kind="condition", action="clear", character="<name>", all_conditions=True), then set HP per the means used.',
]


def resurrection_push() -> list:
    """A fresh copy (callers may indent in place)."""
    return list(RESURRECTION_PATHS)


D6_ABILITY = {1: "STR", 2: "DEX", 3: "CON", 4: "INT", 5: "PSY", 6: "EGO"}

# Engine-owned per-path resurrection data (book p.242). Timer: "d4"/"+7"/None.
# Save: {"ability": .., "dc": 16} or None. The prose is what the begin/resolve
# outputs PUSH; the surgery is applied in _character_resurrect_resolve.
RESURRECTION_CATALOG = {
    "mycomorph": {
        "label": "Mycomorph Spores",
        "timer": "d4",
        "save": {"ability": "INT", "dc": 16},
        "needs": "a Mycomorph PC/NPC to seed the corpse (DM confirms)",
        "reminder": ("reborn as a Mycomorph in d4 days; on an INT save the rebirth "
                     "keeps memories/Level/Gifts/abilities, otherwise it is a new "
                     "Level 1 Mycomorph carrying the same items (DM+player rebuild)."),
    },
    "necrotech": {
        "label": "Necrotech",
        "timer": None,
        "save": None,
        "needs": "an implant/nanomachine resurrection rig (DM confirms)",
        "reminder": ("revival is immediate but always carries a severe downside the "
                     "DM rules (mind-or-flesh decay); the revived body now ALSO counts "
                     "as Synthetic-type."),
    },
    "pseudo_womb": {
        "label": "Pseudo-Womb",
        "timer": "+7",
        "save": {"ability": "CON", "dc": 16},
        "needs": "a flesh scrap or blood sample (DM confirms)",
        "reminder": ("a clone incubates 7 days in the vat; on a CON save it decants as "
                     "an exact copy, otherwise it decants carrying two new mutations."),
    },
    "spirit": {
        "label": "Spirit",
        "timer": None,
        "save": {"ability": "LEVEL", "dc": 16},
        "needs": "nothing - the bid happens at the moment of death",
        "reminder": ("roll d20 + Level; 16+ returns as an unquiet spirit (incorporeal; "
                     "spend d6 essence to touch the world, d6 + target Level to possess "
                     "for one exploration turn; at 0 essence fades until next sunrise). "
                     "The body stays a corpse."),
    },
    "ego_engine": {
        "label": "Ego-Engine Transplant",
        "timer": None,
        "save": None,
        "needs": "a Synthetic corpse with an intact core plus a new synthetic body (DM confirms)",
        "reminder": ("the core is installed in a new body: restart at Level 1, reroll "
                     "STR/DEX/CON (3d6 take the LOWEST die, p.13), keep INT/PSY/EGO."),
    },
    "lazarus_tonic": {
        "label": "Lazarus Tonic",
        "timer": None,
        "save": None,
        "needs": "a Lazarus Tonic dose (elixir d100 78-79) and a biological corpse",
        "reminder": ("revival is immediate at the cost of one Level "
                     "(B3 R-B3c; CH elixirs p.54 printed). Biological "
                     "creatures only -- the tonic does nothing for "
                     "Synthetic or Mineral corpses."),
    },
}


def validate_resurrection_record(req: dict, day: int) -> tuple:
    """Validate a begin request into a stored in-progress resurrection record.
    Returns (record, "") or (None, error). The record rides the corpse's sheet
    under a top-level 'resurrection' key (NOT in conditions -- the condition
    tick skips corpses; the resurrection tick is corpse-exempt)."""
    if not isinstance(req, dict):
        return None, "A resurrection record needs a path."
    path = str(req.get("path") or "").strip().lower()
    if path not in RESURRECTION_CATALOG:
        return None, (f"path must be one of {sorted(RESURRECTION_CATALOG)}; "
                      f"got {req.get('path')!r}.")
    try:
        began = int(req.get("began_day", day))
    except (TypeError, ValueError):
        return None, "began_day must be an integer campaign day."
    due = req.get("due_day")
    if due is not None:
        try:
            due = int(due)
        except (TypeError, ValueError):
            return None, "due_day must be an integer campaign day or null."
    return {"path": path, "began_day": began, "due_day": due,
            "resolved": False}, ""
