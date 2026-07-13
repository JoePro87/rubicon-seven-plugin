"""Character management — decomposition slice 6 (2026-06-17), the final + largest.

Extracted VERBATIM from server.py: the character-management cluster behind the
`character` (and `wound`) tools — character CRUD/leveling, elixirs, companions
(followers/mercenaries/pets/steeds/vehicles), resurrection, wounds, vehicle damage.
The tool DISPATCHERS stay in server.py and import-and-alias these back.

Cross-module functions the movers call (persistence, the death/wound seam, status
helpers, the substances/generators aliases) STAY in server.py and are reached via
call-time DELEGATING SHIMS (_DELEGATES) bound to the live server module by
register_character_tools — patch-transparent. map_system is rebind-patched by tests,
so it is reached through a _LiveServerProxy that resolves _server.map_system at call
time. Server data tables (VAARNISH_ELIXIRS/BIOLOGICAL_WOUNDS/SYNTHETIC_WOUNDS) are
injected by reference. Domain modules + engine_core substrate are imported directly.
"""
import json
import random
import re
import copy

from fastmcp.exceptions import ToolError
from engine_core import CAMPAIGN_DIR, read_file, read_rules_data, dice, GAME_STATE

import weapon_schema as ws
import ancestries as _ancestries
import followers as _followers
import mercenaries as _mercenaries
import pets_steeds as _pets
import vehicles as _vehicles
import push_format as _pf
import item_slots as _isl
import wounds as _wnd
import conditions as _cnd


# The running server module, supplied by register_character_tools() at startup. We do
# NOT `import server`: under `python server.py` the server runs as `__main__`, so a fresh
# `import server` would re-execute it as a second module and deadlock the alias-back (the
# slice-2 boot bug). Registration hands us the live running module.
_server = None


class _LiveServerProxy:
    """Forwards attribute access to a named attribute on the live server module, resolved
    at access time — so tests that REBIND server.<name> (e.g. map_system) stay effective.
    A frozen import/inject would miss the rebind."""

    def __init__(self, _name):
        self.__dict__["_name"] = _name

    def __getattr__(self, item):
        return getattr(getattr(_server, self.__dict__["_name"]), item)


def _make_delegate(_name):
    """Build a call-time delegate to the running server.<_name> (keeps monkeypatches live)."""
    def _delegate(*args, **kwargs):
        return getattr(_server, _name)(*args, **kwargs)
    _delegate.__name__ = _name
    _delegate.__qualname__ = _name
    return _delegate


# Bare-name calls inside the moved helpers resolve to these module globals.
_DELEGATES = (
    "_parse_status_content",
    "_revival_cleanup",
    "read_current_status",
    "_roll_cacogen_mutation",
    "_save_game_state",
    "_apply_wound",
    "_elixir_hp_floor",
    "_elixir_row_for",
    "_is_pc_sheet",
    "_apply_hp_damage_and_wounds",
    "_calculate_slots",
    "_check_death_conditions",
    "_death_gate",
    "_refresh_slot_fields",
    "_find_character",
    "_load_characters",
    "_save_single_character",
    "_poison_enemy_save",
    "_active_vault_turn",
    "_move_sheet_to_departed",
    "_roll_3d6_lowest",
    "_roll_d4",
    "_roll_d6",
)
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n

map_system = _LiveServerProxy("map_system")

# Injected by reference at registration (server data tables; never rebound).
VAARNISH_ELIXIRS = None
BIOLOGICAL_WOUNDS = None
SYNTHETIC_WOUNDS = None


def _character_use_daily(char, daily_name, day):
    """Run a special_traits.daily_uses entry: once per campaign day (R-B2c).

    No reset sweep exists or is needed - availability is last_used_day < today.
    An optional engine_effect.mint_item drops an item into the same container
    the inventory 'add' action defaults to (carried)."""
    traits = char.get("special_traits")
    dailies = traits.get("daily_uses", []) if isinstance(traits, dict) else []
    entry = next((d for d in dailies if isinstance(d, dict)
                  and str(d.get("name", "")).lower() == str(daily_name).lower()), None)
    if entry is None:
        names = ", ".join(str(d.get("name")) for d in dailies if isinstance(d, dict))
        return (f"{char.get('name', '?')} has no daily use named '{daily_name}'."
                + (f" Available: {names}" if names else " (none on sheet)"))
    last = entry.get("last_used_day")
    if isinstance(last, int) and last >= day:
        return (f"{entry['name']} already used today (day {day}). "
                f"Available again tomorrow.")
    entry["last_used_day"] = day
    out = [f"**{entry['name']}** used (day {day})."]
    if entry.get("note"):
        out.append(f"  {entry['note']}")
    fx = entry.get("engine_effect") or {}
    mint = fx.get("mint_item")
    if isinstance(mint, dict):
        item = copy.deepcopy(mint)
        # Mirror the inventory add-item path: same structure bootstrap, same
        # default container (carried), same id/day stamping.
        if not item.get("id"):
            item["id"] = (item.get("name", "unknown").lower()
                          .replace(" ", "_").replace("(", "").replace(")", ""))
        if not item.get("day_acquired"):
            item["day_acquired"] = day
        if "inventory" not in char:
            char["inventory"] = {"carried": [], "stored": [],
                                 "installed_permanent": [], "given_away": []}
        char["inventory"].setdefault("carried", []).append(item)
        out.append(f"  Minted: {item['name']} (carried).")
        if item.get("type") == "poison":
            cname = char.get("name", "?")
            coat_call = _pf.push_call("affliction", kind="toxin", action="poison_coat",
                                      target=cname,
                                      weapon=_pf.raw('"<weapon>"'),
                                      poison=_pf.raw("<the item's poison record, as JSON>"))
            apply_call = _pf.push_call("affliction", kind="toxin", action="poison_apply",
                                       target=_pf.raw('"<victim>"'),
                                       poison=_pf.raw("<the item's poison record, as JSON>"))
            out.append("  " + _pf.next_block(coat_call, apply_call,
                                             label="use the dose"))
    return "\n".join(out)

ELIXIR_UNDRINKABLE_SPECIES = ("synth", "lithling")  # book p.51 printed:

def _active_site_briefing_line():
    """One-line session-start briefing when a site is mid-exploration. Returns
    '' when no active site. Reads last_seen_day for the 'left day' context."""
    try:
        name, turn = _active_vault_turn()
        if not name:
            return ""
        state = map_system.get_map_state(name)
        if state is None:
            return ""
        left = state.get("last_seen_day")
        left_txt = f" (left day {left})" if left is not None else ""
        return f"\U0001f9ed Mid-exploration at {name} — turn {turn}{left_txt}."
    except Exception:
        return ""

def _drink_resolve_data():
    """Tolerate both loader shapes: the production _load_characters() returns
    (data, err) with data['characters']; tests monkeypatch a flat {key: char}.
    Returns (roster_dict, full_data_or_None) where roster_dict maps key->char."""
    loaded = _load_characters()
    if isinstance(loaded, tuple):
        data, err = loaded
        if err or not data:
            return {}, None
        if isinstance(data, dict) and isinstance(data.get("characters"), dict):
            return data["characters"], data
        return (data if isinstance(data, dict) else {}), data
    if isinstance(loaded, dict):
        if isinstance(loaded.get("characters"), dict):
            return loaded["characters"], loaded
        return loaded, None
    return {}, None

def _dose_name_matches(elixir_name: str, dose_name: str) -> bool:
    """B3 (adversarial MINOR): a carried dose matches an elixir when its name
    BEGINS with the elixir name and the next char is a word boundary (or end).
    Prefix-stem, not bare substring -- so 'Death Draught' cannot consume a
    'False Death Draught dose'. Both inputs are already lowercased."""
    if not elixir_name or not dose_name:
        return False
    if not dose_name.startswith(elixir_name):
        return False
    tail = dose_name[len(elixir_name):]
    return tail == "" or not (tail[0].isalnum())

def _elixir_record(elixir):
    """Accept a d100 roll (1-100), a row index key (1-40), or an inline
    record dict/JSON -- mirrors _poison_record's flexibility."""
    if isinstance(elixir, str):
        s = elixir.strip()
        if s.isdigit():
            elixir = int(s)
        else:
            import json as _json
            try:
                elixir = _json.loads(s)
            except Exception:
                return None, f"Could not parse elixir: {s[:80]}"
    if isinstance(elixir, dict):
        if not elixir.get("name") or not isinstance(
                elixir.get("engine_effects"), dict):
            return None, "Inline elixir needs name + engine_effects."
        return elixir, ""
    if isinstance(elixir, int):
        if elixir in VAARNISH_ELIXIRS and elixir <= 40:
            return VAARNISH_ELIXIRS[elixir], ""
        idx, row = _elixir_row_for(elixir)
        if row:
            return row, ""
    return None, f"No elixir matches {elixir!r}."

def _elixir_duration_stamp(req: dict, ee: dict, day: int) -> str:
    """Stamp until_turn (in vault) / DM note (overworld) + the until_day
    failsafe onto a condition request. Returns a human line."""
    dur = ee.get("duration")
    if not dur:
        return "Duration: until cleared (see effect text)."
    if dur.get("days"):
        req["until_day"] = day + int(dur["days"])
        return f"Duration: {dur['days']} day(s) (auto-expires day {req['until_day']})."
    turns = int(dur.get("turns", 0))
    map_name, cur = _active_vault_turn()
    req["until_day"] = day + 1   # failsafe either way
    if map_name is not None:
        req["until_turn"] = cur + turns
        req["turn_map"] = map_name
        return (f"Duration: {turns} Exploration Turns -- expires at "
                f"{map_name} turn {cur + turns} (day {day + 1} failsafe).")
    req["note"] = ((req.get("note", "") + " ").strip() +
                   f"lasts {turns} Exploration Turns -- DM paces "
                   f"(no vault clock running)").strip()
    return (f"Duration: {turns} Exploration Turns -- no vault clock active; "
            f"DM paces (clear via condition tool; day {day + 1} failsafe).")

def _character_drink_elixir(char_key, elixir, day, target=None,
                            save_total=None, rng=random.randint):
    roster, full = _drink_resolve_data()
    char = roster.get(char_key)
    if not isinstance(char, dict):
        return f"Unknown character: {char_key}"
    row, err = _elixir_record(elixir)
    if err:
        return err
    ee = row["engine_effects"]
    cname = char.get("name", char_key)
    lines = [f"**{cname} uses {row['name']}** (POT {row['pot']}, "
             f"{row.get('application', 'drink')})."]

    # 1. Physiology guard (book: Synthetic and Mineral PCs cannot drink).
    if row.get("application", "drink") == "drink":
        species = str(char.get("species", "")).lower()
        if any(s in species for s in ELIXIR_UNDRINKABLE_SPECIES):
            return (f"**{cname} cannot drink elixirs** -- "
                    f"{char.get('species')} physiology (Synthetic and "
                    f"Mineral creatures cannot drink elixirs, CH p.51).")

    # 2. Consume a dose item if carried (loud note if absent, never block).
    inv = char.get("inventory")
    inv_list = inv if isinstance(inv, list) else (
        inv.get("carried") if isinstance(inv, dict) else None)
    dose = None
    if isinstance(inv_list, list):
        # Match the elixir name as a leading STEM, not a bare substring, so
        # "Death Draught" (#18) never eats a "False Death Draught dose" (#7).
        # The dose name must START with the elixir name, ending at a word
        # boundary ("Plating Potion dose" / "Plating Potion" both match;
        # "False Death Draught dose" does not start with "Death Draught").
        needle = row["name"].lower()
        dose = next((i for i in inv_list if isinstance(i, dict)
                     and _dose_name_matches(needle,
                                            str(i.get("name", "")).lower())),
                    None)
    if dose is not None:
        inv_list.remove(dose)
        lines.append(f"Dose consumed from inventory: {dose.get('name')}.")
    else:
        lines.append(f"WARNING: No matching dose in {cname}'s inventory -- "
                     f"applying anyway (found/administered dose). "
                     f"Reconcile inventory if needed.")

    # 3. Apply the effect.
    effect_lines = _elixir_apply_effect(char_key, char, full, row, ee, day,
                                        target=target, save_total=save_total,
                                        rng=rng)
    lines.extend(effect_lines)
    _save_single_character(char_key, char, full)
    lines.append(f"Effect (book): {row['effect_text']}")
    return "\n".join(lines)

def _elixir_apply_effect(char_key, char, data, row, ee, day,
                         target=None, save_total=None, rng=random.randint):
    kind = ee["kind"]
    lines = []

    def _mint_condition(extra_revert=None, extra_deff=None):
        base = dict(ee.get("condition") or
                    {"name": row["name"], "note": row["effect_text"][:120]})
        req = dict(base)
        if extra_revert:
            req["revert"] = extra_revert
        if extra_deff:
            req["derived_effects"] = extra_deff
        req["cause"] = f"elixir: {row['name']}"
        dline = _elixir_duration_stamp(req, ee, day)
        rec, nerr = _cnd.normalize_record(req, day)
        if rec is None:
            lines.append(f"WARNING: condition error: {nerr}")
            return
        char.setdefault("conditions", []).append(rec)
        lines.append(f"Condition applied: **{rec['name']}**. {dline}")

    if kind in ("prose_only", "condition"):
        if ee.get("condition") or ee.get("duration"):
            _mint_condition()
        if ee.get("push"):
            lines.append(f"NEXT: {ee['push']}")
    elif kind == "av_bonus":
        extra_rev = None
        if ee.get("trigger"):
            trg = dict(ee["trigger"]); trg["source"] = f"elixir: {row['name']}"
            char.setdefault("special_traits", {}).setdefault(
                "triggers", []).append(trg)
            extra_rev = {"remove_trigger": trg["label"]}   # auto-disarm at expiry
            lines.append(f"Temporary trigger armed: {trg['label']} "
                         f"({trg['kind']}, {trg['die']}) -- auto-disarmed "
                         f"when the condition expires.")
        _mint_condition(extra_revert=extra_rev,
                        extra_deff={"av_bonus": int(ee["av_bonus"])})
    elif kind == "ability_mod":
        ab = char.setdefault("abilities", {})
        revert = {"abilities": {}}
        if ee.get("mods"):
            for stat, delta in ee["mods"].items():
                revert["abilities"][stat] = ab.get(stat, 10)
                ab[stat] = ab.get(stat, 10) + delta
                lines.append(f"{stat} {revert['abilities'][stat]} -> {ab[stat]}.")
        if ee.get("double"):
            for field in ee["double"]:
                if field == "hp":
                    hp = char.setdefault("hp", {"current": 0, "max": 0})
                    revert["hp_max"] = hp.get("max", 0)
                    revert["hp_current"] = hp.get("current", 0)
                    hp["max"] = hp.get("max", 0) * 2
                    hp["current"] = hp.get("current", 0) * 2
                    lines.append(f"HP {revert['hp_current']} -> {hp['current']} "
                                 f"(max {revert['hp_max']} -> {hp['max']}).")
                else:
                    revert["abilities"][field] = ab.get(field, 10)
                    ab[field] = ab.get(field, 10) * 2
                    lines.append(f"{field} doubled -> {ab[field]}.")
        _mint_condition(extra_revert=revert)
    elif kind == "hp_regen":
        _mint_condition()
        lines.append(f"NEXT: In combat: roll {ee['die']} HP regained at the "
                     f"start of {char.get('name', char_key)}'s turn "
                     f"(not if damaged by fire/acid since last turn).")
    elif kind == "hp_set_zero":
        # R-B3e Death Draught: book-literal. Snap to 0 and fire the SAME
        # wound applier combat uses.
        hp = char.setdefault("hp", {"current": 0, "max": 0})
        dmg = max(0, int(hp.get("current", 0)))
        lines.append(f"**{char.get('name', char_key)} drops to 0 HP** "
                     f"({dmg} damage).")
        hp["current"] = 0
        wound_table = (BIOLOGICAL_WOUNDS
                       if char.get("wound_table", "biological") == "biological"
                       else SYNTHETIC_WOUNDS)
        lines.extend(_apply_wound(char_key, char, data, 0, wound_table))
    elif kind == "hp_floor":
        cond_req = dict(ee.get("condition") or {})
        cond_req["cause"] = f"elixir: {row['name']}"
        cond_req["hp_floor"] = ee.get("floor", -19)
        dline = _elixir_duration_stamp(cond_req, ee, day)
        rec, nerr = _cnd.normalize_record(cond_req, day)
        if rec is None:
            lines.append(f"WARNING: condition error: {nerr}")
        else:
            char.setdefault("conditions", []).append(rec)
            lines.append(f"**Deathless**: damage cannot reduce "
                         f"{char.get('name', char_key)} below -19 HP "
                         f"(R-B3d). {dline}")
    elif kind == "resurrection":
        tgt = target or char.get("name", char_key)
        tkey, tchar = _resolve_target_char(tgt, char_key, char)
        if tchar is None:
            lines.append(f"WARNING: Unknown target for Lazarus Tonic: {tgt}")
            return lines
        ok, why = _lazarus_eligible(tchar)
        if not ok:
            lines.append(why)
            return lines
        lines.append(f"NEXT: Lazarus Tonic on {tchar.get('name', tkey)}: "
                     f'begin the path -- character(action="resurrect", '
                     f'name="{tchar.get("name", tkey)}", path="lazarus_tonic"), '
                     f'then character(action="resurrect_resolve", '
                     f'name="{tchar.get("name", tkey)}", path="lazarus_tonic") -- '
                     f'the resolve applies the -1 Level cost.')
    elif kind == "save_fork":
        lines.extend(_elixir_save_fork(char_key, char, data, row, ee, day,
                                       target=target, save_total=save_total,
                                       rng=rng))
    elif kind == "gift_mint":
        for g in ee.get("gifts", []):
            lines.append(f'NEXT: Gift gained: gift(action="add", '
                         f'character_name="{char.get("name", char_key)}", '
                         f'gift_name="{g}")')
        if not ee.get("permanent") and ee.get("condition"):
            _mint_condition()
            lines.append("WARNING: TEMPORARY gifts -- remove them when the "
                         "condition expires (the wear-off line will remind).")
    elif kind == "sheet_surgery":
        lines.append(f"NEXT: PERMANENT: {ee.get('push', row['effect_text'])}")
    elif kind == "follower_mint":
        m = ee["mint"]
        n = rng(1, int(m["count_die"].lstrip("d")))
        lines.append(f"**{n} {m['name']}s are born** -- each Lvl {m['level']} "
                     f"({m['hp']} hp), AV {m['av']}, {m['attack']}; loyal "
                     f"to {char.get('name', char_key)} until killed.")
        lines.append("NEXT: Record the spawn on the sheet's notes via "
                     "npc/lorebook (these are minion swarm NPCs, not D2 "
                     "recruit-table followers).")
    else:
        lines.append(f"WARNING: engine kind '{kind}' wired in a later task -- "
                     f"apply by hand for now.")
    return lines

def _lazarus_eligible(corpse):
    """B3 R-B3c: Lazarus Tonic works only on a biological CORPSE. Mirrors the
    E5 resurrect-begin corpse predicate (hp.current <= -20)."""
    hp = corpse.get("hp")
    hp_cur = hp.get("current", 0) if isinstance(hp, dict) else corpse.get("hp", 0)
    if hp_cur > -20 and not corpse.get("resurrection"):
        return False, (f"{corpse.get('name', '?')} is not dead -- Lazarus "
                       f"Tonic only works on the dead (corpse-only path).")
    species = str(corpse.get("species", "")).lower()
    if any(s in species for s in ("synth", "lithling")):
        return False, (f"The tonic does nothing -- {corpse.get('species')} "
                       f"is not biological (R-B3c).")
    return True, ""

def _resolve_target_char(name, drinker_key, drinker_char):
    """Resolve an elixir target by name across BOTH loader shapes. Returns
    (key, char) or (None, None). The drinker is matched first so the common
    self-target case never needs a roster walk."""
    if not name:
        return drinker_key, drinker_char
    n = str(name).strip().lower()
    if n in (str(drinker_key).lower(),
             str(drinker_char.get("name", "")).lower()):
        return drinker_key, drinker_char
    roster, _full = _drink_resolve_data()
    for k, c in roster.items():
        if not isinstance(c, dict):
            continue
        if str(k).lower() == n or str(c.get("name", "")).lower() == n:
            return k, c
    return None, None

def _elixir_save_fork(char_key, char, data, row, ee, day,
                      target=None, save_total=None, rng=random.randint):
    lines = []
    tgt = target or char.get("name", char_key)
    save = ee.get("save")
    tkey, tchar = _resolve_target_char(tgt, char_key, char)

    def _apply_fail(victim_key, victim_char):
        onf = ee.get("on_fail") or {}
        if onf.get("transformation_death"):
            if victim_char is not None:    # PC: gated transformation death
                if isinstance(victim_char.get("hp"), dict):
                    victim_char["hp"]["current"] = -20   # death-gate shape
                allowed, glines = _death_gate(victim_key, victim_char, data,
                                              cause=f"Kalotoxin -- "
                                              f"{onf['transformation_death']}")
                lines.extend(glines)
                if not allowed:
                    if isinstance(victim_char.get("hp"), dict):
                        victim_char["hp"]["current"] = -19
                    lines.append("The Twinning holds -- the transformation "
                                 "is refused (DM adjudicates the half-state).")
                else:
                    lines.append(f"**{victim_char.get('name', victim_key)} is "
                                 f"{onf['transformation_death']}.**")
            else:
                lines.append(f"**{tgt} is {onf['transformation_death']}** "
                             f"(enemy: remove from combat).")
        elif onf.get("condition"):
            req = dict(onf["condition"]); req["cause"] = f"elixir: {row['name']}"
            _elixir_duration_stamp(req, ee, day)
            rec, nerr = _cnd.normalize_record(req, day)
            if rec is not None and victim_char is not None:
                victim_char.setdefault("conditions", []).append(rec)
                lines.append(f"**{victim_char.get('name', victim_key)}** "
                             f"gains {rec['name']}.")
            elif victim_char is None:
                lines.append(f"**{tgt}** suffers: {onf['condition']['name']} "
                             f"(enemy -- prose).")

    if save is None:                       # Kalotoxin: NO save
        _apply_fail(tkey, tchar)
        return lines
    if tchar is not None:                  # PC target: two-phase (B2 pattern)
        if save_total is None:
            return [f"**{tgt} must roll a {save['ability']} save** "
                    f"(d20 + {save['ability']} bonus) -- then call "
                    f'character(action="drink_elixir", name="'
                    f'{char.get("name", char_key)}", elixir={row["d100"][0]}, '
                    f'target="{tgt}", save_total=<total>).']
        tn = 15
        if save_total >= tn:
            lines.append(f"{tgt} saves ({save_total} vs TN {tn}) -- no effect.")
        else:
            lines.append(f"{tgt} fails ({save_total} vs TN {tn}).")
            _apply_fail(tkey, tchar)
    else:                                  # enemy: auto-resolve like B2
        passed, detail = _poison_enemy_save({"lvl": 1}, rng=rng)
        lines.append(detail)
        if not passed:
            _apply_fail(None, None)
    return lines

# ---------------------------------------------------------------------------
# Worn armour + AV recomputation (Bug 5, macOS playtest 1)
# ---------------------------------------------------------------------------
# av.base is the EFFECTIVE Armour Value combat reads — it is DERIVED, never the
# raw species baseline:  av.base = av.unarmoured + sum(av_bonus of every worn
# armour/helm/shield).  av.unarmoured is the no-armour baseline (species AV plus
# standing AV mutations).  Marking an inventory item worn and calling
# _recompute_av is the ONLY way armour changes AV — the DM never hand-edits the
# sheet.  One body-armour slot; helm and shield are separate slots.

_AV_SLOTS = ("body", "helm", "shield")


_HELM_WORDS = {"helm", "helmet", "cap", "casque", "coif", "mask", "visor"}
_SHIELD_WORDS = {"shield", "buckler", "aegis"}


def _infer_av_slot(item: dict) -> str:
    """Which armour slot an item occupies. Explicit item['slot'] wins; otherwise
    infer from WHOLE-WORD name tokens (so 'Capacitor Vest'/'Caparison' don't get
    mis-slotted as a helm by a bare 'cap' substring), defaulting to body."""
    slot = str(item.get("slot", "")).strip().lower()
    if slot in _AV_SLOTS:
        return slot
    words = set(re.findall(r"[a-z]+", str(item.get("name", "")).lower()))
    if words & _SHIELD_WORDS:   # shield wins over helm on a collision (e.g. "Helmsman's Shield")
        return "shield"
    if words & _HELM_WORDS:
        return "helm"
    return "body"


def _coerce_av_num(x):
    """An AV number from int/float/numeric-string (the register path may author
    av_bonus/av as strings). bool and non-numeric -> None."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        try:
            return int(float(x.strip()))
        except (ValueError, TypeError):
            return None
    return None


def _item_av_bonus(item: dict) -> int:
    """An armour item's AV contribution over unarmoured. Prefer the canonical
    av_bonus (generator items carry it); else derive from a worn-AV 'av' field
    (av - 10) for hand-authored/registered items like an Occult Cuirass
    (av:14 -> +4). Numeric strings are coerced so a registered '4' isn't silently
    dropped to 0 (which would leave the PC unarmoured in combat). Never negative."""
    b = _coerce_av_num(item.get("av_bonus"))
    if b is not None:
        return max(0, b)
    a = _coerce_av_num(item.get("av"))
    if a is not None:
        return max(0, a - 10)
    return 0


def _worn_armour(char: dict) -> list:
    """Every carried item currently marked worn."""
    carried = (char.get("inventory") or {}).get("carried") or []
    return [it for it in carried if isinstance(it, dict) and it.get("worn")]


def _recompute_av(char: dict) -> int:
    """Recompute av.base from the no-armour baseline + all worn armour. Returns
    the new effective AV. Backfills av.unarmoured from the current base on legacy
    sheets (where base WAS the baseline because armour was never applied)."""
    av = char.get("av")
    if not isinstance(av, dict):
        av = {"base": int(av) if isinstance(av, (int, float)) else 10, "conditional": []}
        char["av"] = av
    worn = _worn_armour(char)
    bonus = sum(_item_av_bonus(it) for it in worn)
    if not isinstance(av.get("unarmoured"), int):
        # Backfill the no-armour baseline on a legacy sheet. If armour was already
        # baked into base AND is still marked worn (e.g. a hand-edited av.base),
        # subtract it back out first so the recompute below can't double-count it.
        av["unarmoured"] = int(av.get("base", 10)) - bonus
    unarmoured = av["unarmoured"]
    av["base"] = unarmoured + bonus
    if worn:
        parts = ", ".join(f"{it.get('name', 'armour')} +{_item_av_bonus(it)}" for it in worn)
        av["source"] = f"{parts} (over unarmoured {unarmoured})"
    else:
        av["source"] = "unarmoured"
    return av["base"]


def _character_equip(character_name: str, item: str, slot=None, av_bonus=None) -> str:
    """Mark a carried armour/helm/shield as worn and recompute AV. Unequips
    whatever was worn in the same slot first (one item per slot). `av_bonus`
    sets/overrides the item's AV contribution (use for a registered piece whose
    worn AV the DM knows, e.g. an Occult Cuirass at AV 14 -> av_bonus 4)."""
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    carried = (char.get("inventory") or {}).get("carried") or []
    needle = str(item).strip().lower()
    matches = [it for it in carried if isinstance(it, dict)
               and (str(it.get("id", "")).lower() == needle
                    or str(it.get("name", "")).lower() == needle)]
    if not matches:  # fall back to substring on name
        matches = [it for it in carried if isinstance(it, dict)
                   and needle in str(it.get("name", "")).lower()]
    if not matches:
        names = ", ".join(it.get("name", it.get("id", "?")) for it in carried
                          if isinstance(it, dict)) or "(empty)"
        return (f"No carried item matching '{item}' for {char['name']}. "
                f"Carried: {names}")
    if len(matches) > 1:
        names = ", ".join(it.get("name", "?") for it in matches)
        return (f"Ambiguous — '{item}' matches several carried items ({names}). "
                f"Use the exact name or id.")
    target = matches[0]

    # Guard the optional levers by type: only act on real values (a direct call
    # may pass through unset Field defaults rather than None).
    if isinstance(av_bonus, (int, float)) and not isinstance(av_bonus, bool):
        target["av_bonus"] = max(0, int(av_bonus))
    target_slot = (slot.strip().lower() if isinstance(slot, str) and slot.strip()
                   else _infer_av_slot(target))
    if target_slot not in _AV_SLOTS:
        target_slot = "body"

    displaced = []
    for it in carried:
        if it is not target and it.get("worn") and _infer_av_slot(it) == target_slot:
            it["worn"] = False
            displaced.append(it.get("name", "?"))
    target["worn"] = True
    target["slot"] = target_slot

    old_av = int(char["av"].get("base", 10)) if isinstance(char.get("av"), dict) else 10
    new_av = _recompute_av(char)
    _save_single_character(key, char, data)

    out = [f"**{char['name']}** equips **{target.get('name', '?')}** "
           f"({target_slot}, +{_item_av_bonus(target)} AV)."]
    if displaced:
        out.append(f"  Unequipped from {target_slot}: {', '.join(displaced)}.")
    out.append(f"  AV: {old_av} -> {new_av}  ({char['av'].get('source')})")
    return "\n".join(out)


def _character_unequip(character_name: str, item: str) -> str:
    """Take off a worn armour/helm/shield and recompute AV."""
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")
    needle = str(item).strip().lower()
    matches = [it for it in _worn_armour(char)
               if str(it.get("id", "")).lower() == needle
               or needle in str(it.get("name", "")).lower()]
    if not matches:
        worn = ", ".join(it.get("name", "?") for it in _worn_armour(char)) or "(nothing worn)"
        return f"No WORN item matching '{item}' for {char['name']}. Worn: {worn}"
    if len(matches) > 1:
        names = ", ".join(it.get("name", "?") for it in matches)
        return f"Ambiguous — '{item}' matches several worn items ({names})."
    target = matches[0]
    old_av = int(char["av"].get("base", 10)) if isinstance(char.get("av"), dict) else 10
    target["worn"] = False
    new_av = _recompute_av(char)
    _save_single_character(key, char, data)
    return (f"**{char['name']}** removes **{target.get('name', '?')}**.\n"
            f"  AV: {old_av} -> {new_av}  ({char['av'].get('source')})")


def _character_get(character_name: str) -> str:
    """Get full character stat block."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        available = ", ".join(data.get('characters', {}).keys())
        return f"Character '{character_name}' not found. Available: {available}"

    slots = _calculate_slots(char)

    output = []
    output.append(f"{'='*60}")
    output.append(f"{char.get('name', key).upper()} - Level {char.get('level', 1)} {char.get('species', 'Unknown')}")
    output.append(f"{'='*60}")
    output.append(f"**Role:** {char.get('role', 'Unknown')} | **Pronouns:** {char.get('pronouns', 'Unknown')}")
    output.append("")

    # Combat stats
    output.append("**COMBAT STATS**")
    hp = char.get('hp', {})
    output.append(f"- HP: {hp.get('current', 0)}/{hp.get('max', 0)}")
    av = char.get('av', {})
    av_str = f"AV: {av.get('base', 10)}"
    if av.get('conditional'):
        cond = av['conditional'][0]
        av_str += f" ({cond.get('total', av.get('base', 10) + cond.get('bonus', 0))} {cond.get('condition', '')})"
    output.append(f"- {av_str}")
    xp = char.get('xp', {})
    output.append(f"- XP: {xp.get('current', 0)}/{xp.get('needed', char.get('level', 1))}")
    output.append("")

    # Abilities
    output.append("**ABILITIES**")
    for stat in ['STR', 'DEX', 'CON', 'INT', 'PSY', 'EGO']:
        stat_data = char.get('abilities', {}).get(stat, {})
        current = stat_data.get('current', 0) if isinstance(stat_data, dict) else stat_data
        notes = stat_data.get('notes', '') if isinstance(stat_data, dict) else ''
        sign = '+' if current >= 0 else ''
        note_str = f" ({notes})" if notes else ""
        output.append(f"- {stat}: {sign}{current}{note_str}")
    output.append("")

    # Slots
    output.append("**SLOT CAPACITY**")
    output.append(f"- Carried: {slots['carried']} slots")
    if slots['gifts'] > 0:
        output.append(f"- Mystic Gifts: {slots['gifts']} slots")
    if slots['codices'] > 0:
        output.append(f"- Codices: {slots['codices']} slots")
    if slots['wounds'] > 0:
        output.append(f"- Wounds: {slots['wounds']} slots")
    output.append(f"- **Total: {slots['total_used']}/{slots['capacity']} ({slots['free']} free)**")
    if slots['wounds'] > 0:
        output.append(f"- Effective free (after wounds): {slots['effective_free']}")
    output.append("")

    # Inventory. Items vary wildly in what they can do (2026-07-07 owner ask),
    # so the sheet render is where the DM learns an item's powers — every
    # effect field is surfaced, indented under its item line.
    def _item_lines(item):
        head = f"- {item.get('name', 'Unknown')}"
        qty = item.get('quantity')
        if qty not in (None, 1):
            head += f" ×{qty}"
        head += f" ({item.get('slots', 1)} slots)"
        if item.get('damage'):
            head += f" [{item.get('damage')}]"
        if item.get('av') or item.get('av_bonus'):
            head += f" [+{_item_av_bonus(item)} AV]"
        if item.get('worn'):
            head += f" **(WORN: {item.get('slot', _infer_av_slot(item))})**"
        lines = [head]
        for fld, label in (('effect', ''), ('effect_special', 'special: '),
                           ('effect_daily', 'daily: '), ('notes', 'notes: ')):
            if item.get(fld):
                lines.append(f"  · {label}{item[fld]}")
        if item.get('uses_max'):
            lines.append(f"  · uses: {item['uses_max']}/{item.get('uses_per', 'day')}")
        if item.get('power_cell_required'):
            lines.append(f"  · power cell: {item.get('power_cell_status', 'required')}")
        tags = list(item.get('tags') or [])
        powered = item.get('tags_when_powered')
        if powered:
            tags.append(f"when powered: {', '.join(powered)}")
        if tags:
            lines.append(f"  · tags: {', '.join(tags)}")
        return lines

    carried = char.get('inventory', {}).get('carried', [])
    if carried:
        output.append("**CARRIED INVENTORY (equipment)**")
        for item in carried:
            output.extend(_item_lines(item))
        output.append("")

    stored = char.get('inventory', {}).get('stored', [])
    if stored:
        output.append("**STORED (not on person)**")
        for item in stored:
            lines = _item_lines(item)
            if item.get('location'):
                lines[0] += f" — at {item['location']}"
            output.extend(lines)
        output.append("")

    installed_perm = char.get('inventory', {}).get('installed_permanent', [])
    if installed_perm:
        output.append("**INSTALLED (permanent, no slots)**")
        for item in installed_perm:
            head = f"- {item.get('name', 'Unknown')}"
            if item.get('location'):
                head += f" [{item['location']}]"
            output.append(head)
            if item.get('effect'):
                output.append(f"  · {item['effect']}")
        output.append("")

    # Augmentations
    augs = char.get('augmentations', {})
    installed = [(slot, aug) for slot, aug in augs.items() if aug is not None]
    if installed:
        output.append("**AUGMENTATIONS (cybernetics, do not use slots)**")
        for slot, aug in installed:
            if isinstance(aug, list):
                for a in aug:
                    output.append(f"- [{slot}] {a.get('name', 'Unknown')}: {a.get('effect', '')}")
            else:
                output.append(f"- [{slot}] {aug.get('name', 'Unknown')}: {aug.get('effect', '')}")
        output.append("")

    # Mystic gifts
    gifts = char.get('mystic_gifts', [])
    if gifts:
        output.append("**MYSTIC GIFTS (1 slot each)**")
        for gift in gifts:
            output.append(f"- {gift.get('name', 'Unknown')}: {gift.get('effect', '')}")
        output.append(f"- Gleam: {char.get('gleam', 0)}")
        output.append("")

    # Attacks
    attacks = char.get('attacks', [])
    if attacks:
        output.append("**ATTACKS**")
        for atk in attacks:
            atk_str = f"- {atk.get('name', 'Unknown')}: {atk.get('damage', 'd4')}"
            if atk.get('type'):
                atk_str += f" ({atk.get('type')})"
            if atk.get('range'):
                atk_str += f", {atk.get('range')} range"
            output.append(atk_str)
        output.append("")

    # Death check
    is_dead, reason = _check_death_conditions(char)
    if is_dead:
        output.append(f"**!!! {reason} !!!**")
    else:
        twin_partner = _cnd.condition_effects(
            char.get('conditions') or []).get('twinned_partner')
        if twin_partner:
            output.append(
                f"(Twinned with {twin_partner} - cannot die unless both fall "
                f"in one window)")

    return "\n".join(output)

def _character_list() -> str:
    """List all characters with summary stats."""
    data, err = _load_characters()
    if err:
        return err

    output = []
    output.append(f"{'='*70}")
    output.append("PARTY ROSTER")
    output.append(f"{'='*70}")
    output.append(f"{'Name':<20} {'Level':>5} {'HP':>10} {'AV':>4} {'Slots':>12} {'Location':<15}")
    output.append("-" * 70)

    for key, char in data.get('characters', {}).items():
        name = char.get('name', key)
        level = char.get('level', 1)
        hp = char.get('hp', {})
        hp_str = f"{hp.get('current', 0)}/{hp.get('max', 0)}"
        av = char.get('av', {}).get('base', 10)
        slots = _calculate_slots(char)
        slots_str = f"{slots['total_used']}/{slots['capacity']}"
        location = char.get('location', 'Ceruline')

        output.append(f"{name:<20} {level:>5} {hp_str:>10} {av:>4} {slots_str:>12} {location:<15}")

    output.append("-" * 70)
    output.append(f"Campaign Day: {data.get('meta', {}).get('campaign_day', '?')}")

    return "\n".join(output)

def _character_update_hp(character_name: str, current: int, max_hp: int = None) -> str:
    """Update character HP."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    old_current = char.get('hp', {}).get('current', 0)
    old_max = char.get('hp', {}).get('max', 0)

    # B3 R-B3d (adversarial HIGH belt-and-braces): a Deathless PC cannot be set
    # below the Immortality floor -- otherwise the sub-floor value persists and
    # auto-kills the moment Deathless wears off. Clamp the manual set up to the
    # floor when one is active.
    floor = _elixir_hp_floor(char)
    floor_note = ""
    if floor is not None and current < floor:
        floor_note = (f"\n\n**DEATHLESS:** set clamped at {floor} HP "
                      f"(was {current}; Immortality Injector).")
        current = floor

    char['hp']['current'] = current
    if max_hp is not None:
        char['hp']['max'] = max_hp

    _save_single_character(key, char, data)

    is_dead, reason = _check_death_conditions(char)

    result = f"**{char['name']}** HP updated: {old_current}/{old_max} -> {current}/{char['hp']['max']}"
    if floor_note:
        result += floor_note
    if is_dead:
        result += f"\n\n**!!! WARNING: {reason} !!!**"
        twin_partner = _cnd.condition_effects(
            char.get('conditions') or []).get('twinned_partner')
        if twin_partner:
            result += (f"\n(NOTE: {char['name']} is Twinned - manual HP sets "
                       f"bypass the death gate; use combat/damage paths or "
                       f"rule it deliberately.)")
    elif current <= 0:
        result += (
            f"\n\n**WARNING:** HP at or below 0. Check wound table for HP threshold {current}.\n"
            + _pf.next_block(
                _pf.push_call("affliction", kind="wound", action="status", character=char["name"]),
                label="check wound",
            )
        )

    return result

def _character_update_stat(character_name: str, stat: str, value: int) -> str:
    """Update an ability score."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    stat = stat.upper()
    if stat not in ['STR', 'DEX', 'CON', 'INT', 'PSY', 'EGO']:
        return f"Invalid stat '{stat}'. Use: STR, DEX, CON, INT, PSY, EGO"

    abilities = char.get('abilities', {})
    if stat not in abilities:
        abilities[stat] = {'current': 0, 'base': 0}

    old_value = abilities[stat].get('current', 0) if isinstance(abilities[stat], dict) else abilities[stat]

    if isinstance(abilities[stat], dict):
        abilities[stat]['current'] = value
    else:
        abilities[stat] = {'current': value, 'base': value}

    result = f"**{char['name']}** {stat}: {old_value:+d} -> {value:+d}"

    if stat == 'CON':
        old_capacity = char.get('slot_capacity_total', 10)
        char['slot_capacity_bonus'] = value
        char['slot_capacity_total'] = 10 + value
        result += f"\nSlot capacity: {old_capacity} -> {char['slot_capacity_total']}"

    _save_single_character(key, char, data)

    if value < -10:
        result += f"\n\n**!!! DEATH: {stat} dropped below -10 !!!**"

    return result

def _character_gain_xp(character_name: str, amount: int, reason: str) -> str:
    """Award XP to a character."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    xp = char.setdefault('xp', {'current': 0, 'needed': char.get('level', 1)})
    old_xp = xp.get('current', 0)
    new_xp = old_xp + amount
    xp['current'] = new_xp

    _save_single_character(key, char, data)

    result = f"**{char['name']}** gained {amount} XP ({reason})\nXP: {old_xp} -> {new_xp}/{xp['needed']}"

    if new_xp >= xp['needed']:
        result += f"\n\n**LEVEL UP AVAILABLE!** {char['name']} can advance to Level {char.get('level', 1) + 1}."
        std_call = _pf.push_call(
            "character", action="level_up", character_name=char['name'],
            stat_increases=_pf.raw("<e.g. STR,CON>"), hp_roll=_pf.raw("<d8 roll>"))
        if 'neobloom' in char.get('species', '').lower():
            # Book (CH p.049): a Neobloom MAY roll a Bloomboon INSTEAD of the
            # standard HP + ability-score advancement. Surface BOTH paths at the
            # decision point so the player's book-given choice is never silently
            # skipped — they pick one. The bloomboon roll (with the "next Boon
            # down" repeat rule) lives in level_up_bloomboon.
            result += ("\nNeobloom: you may take standard advancement OR roll a "
                       "Bloomboon instead (one boon, in place of the HP + ability gains).")
            bloom_call = _pf.push_call(
                "character", action="level_up_bloomboon", character_name=char['name'])
            result += "\n" + _pf.next_block(
                std_call, bloom_call, label="Neobloom level-up — choose one")
        else:
            result += "\n" + _pf.next_block(std_call)

    return result

def _character_level_up(character_name: str, stat_increases: str, hp_roll: int) -> str:
    """Apply level up to a character."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    xp = char.get('xp', {'current': 0, 'needed': char.get('level', 1)})
    if xp.get('current', 0) < xp.get('needed', 1):
        return f"Not enough XP. Current: {xp.get('current', 0)}, Needed: {xp.get('needed', 1)}"

    stats = [s.strip().upper() for s in stat_increases.split(',')]
    if len(stats) != 3:
        return f"Must increase exactly 3 stats. Got: {len(stats)}"

    for stat in stats:
        if stat not in ['STR', 'DEX', 'CON', 'INT', 'PSY', 'EGO']:
            return f"Invalid stat '{stat}'. Use: STR, DEX, CON, INT, PSY, EGO"

    if hp_roll < 1 or hp_roll > 8:
        return f"HP roll must be 1-8 (d8). Got: {hp_roll}"

    abilities = char.get('abilities', {})
    for stat in stats:
        current = abilities.get(stat, {}).get('current', 0) if isinstance(abilities.get(stat), dict) else abilities.get(stat, 0)
        if current >= 10:
            raise ToolError(f"REJECTED: {stat} is already at maximum (+10)")

    old_level = char.get('level', 1)
    new_level = old_level + 1
    char['level'] = new_level
    char['xp'] = {'current': 0, 'needed': new_level}

    old_max_hp = char.get('hp', {}).get('max', 0)
    char['hp']['max'] = old_max_hp + hp_roll
    char['hp']['current'] = char['hp']['max']

    stat_changes = []
    for stat in stats:
        if stat not in abilities:
            abilities[stat] = {'current': 0, 'base': 0}
        if isinstance(abilities[stat], dict):
            old_val = abilities[stat].get('current', 0)
            abilities[stat]['current'] = old_val + 1
            abilities[stat]['base'] = abilities[stat].get('base', old_val) + 1
        else:
            old_val = abilities[stat]
            abilities[stat] = {'current': old_val + 1, 'base': old_val + 1}
        stat_changes.append(f"{stat}: {old_val:+d} -> {old_val + 1:+d}")

    if 'CON' in stats:
        new_con = abilities['CON'].get('current', 0) if isinstance(abilities['CON'], dict) else abilities['CON']
        char['slot_capacity_bonus'] = new_con
        char['slot_capacity_total'] = 10 + new_con

    # Lithling Crystalline Flesh: base AV is 10 + Level, max 20 (CH p.25).
    av_line = None
    if 'lithling' in char.get('species', '').lower() and isinstance(char.get('av'), dict):
        new_av = min(20, 10 + new_level)
        char['av']['base'] = new_av
        char['av']['source'] = "Crystalline Flesh (AV 10 + Level, max 20)"
        av_line = f"AV (Crystalline Flesh): {min(20, 10 + old_level)} -> {new_av}"

    _save_single_character(key, char, data)

    output = [
        f"**{char['name']} LEVELED UP!**",
        f"Level: {old_level} -> {new_level}",
        f"Max HP: {old_max_hp} + {hp_roll} = {char['hp']['max']}",
        f"Stats increased:",
    ] + [f"  {sc}" for sc in stat_changes]
    if av_line:
        output.append(av_line)

    if 'CON' in stats:
        output.append(f"Slot capacity: {10 + abilities['CON'].get('current', 0) - 1} -> {char['slot_capacity_total']}")

    output.append(f"\nXP reset to 0/{new_level}")

    return "\n".join(output)

def _character_level_up_proteus(character_name: str) -> str:
    """Apply Proteus option for Cacogen (gain mutation instead of standard advancement)."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    if 'cacogen' not in char.get('species', '').lower():
        return f"{char['name']} is not a Cacogen (only Cacogens can use Proteus)"

    xp = char.get('xp', {'current': 0, 'needed': char.get('level', 1)})
    if xp.get('current', 0) < xp.get('needed', 1):
        return f"Not enough XP. Current: {xp.get('current', 0)}, Needed: {xp.get('needed', 1)}"

    mutation = _roll_cacogen_mutation()
    old_level = char.get('level', 1)
    new_level = old_level + 1
    char['level'] = new_level
    char['xp'] = {'current': 0, 'needed': new_level}

    # Add mutation to special traits
    traits = char.setdefault('special_traits', {})
    mutations_list = traits.setdefault('mutations', [])
    mutations_list.append(mutation)

    _save_single_character(key, char, data)

    return "\n".join([
        f"**{char['name']} used PROTEUS!**",
        f"",
        f"Leveled to **Level {new_level}**",
        f"Rolled {mutation['source']}",
        f"",
        f"**New Mutation Gained:**",
        f"**{mutation['name']}**",
        f"{mutation['effect']}",
        f"",
        f"**No HP roll or ability increases** (traded for mutation)",
        f"XP reset to 0/{new_level}"
    ])

PC_ABILITY_ORDER = ["STR", "DEX", "CON", "INT", "PSY", "EGO"]

PC_STARTING_BOONS = {
    1: "Advanced Weapon", 2: "Alchemist's Crucible + Elixir",
    3: "Cybernetic Implant", 4: "Exotica",
    5: "Hypergeometric Codex", 6: "Mystic Gift",
}

def _pc_gear_item(g):
    """Convert a rolled ancestries gear row into a sheet inventory item in the
    ENGINE'S depletion schema (item_slots.py): integer `uses` counters and
    `usage_die` notation, both read by the usage engine."""
    item = {"name": g["name"], "slots": 1, "type": "gear"}
    if g.get("uses"):
        item["uses"] = int(g["uses"])
    if g.get("usage_die"):
        item["usage_die"] = g["usage_die"]
    if g.get("ref"):
        item["notes"] = "Detailed in the book ({})".format(g["ref"])
    item["id"] = re.sub(r"[^a-z0-9]+", "_", g["name"].lower()).strip("_")
    return item

def _character_create(name=None):
    """PC creation step 1 (CH p.5-6): six abilities IN ORDER (3d6, bonus =
    LOWEST die) + a d10 ancestry SUGGESTION. Writes NOTHING to the roster -
    the swap and ancestry are the player's choices. The rolled bonuses are
    stashed in GAME_STATE world_tick so create_finalize can't be replayed
    with edited scores."""
    if not isinstance(name, str) or not name.strip():
        name = None  # direct calls bypass pydantic: FieldInfo is not a name
    else:
        name = name.strip()
    bonuses = {}
    lines = ["**PC CREATION - STEP 1 (CH p.5-6)**",
             "3d6 per ability IN ORDER; the bonus is the LOWEST die:"]
    for ab in PC_ABILITY_ORDER:
        bonus, rolled = _ancestries.ability_roll(random.randint)
        bonuses[ab] = bonus
        lines.append("  {}: [{}, {}, {}] -> +{}".format(
            ab, rolled[0], rolled[1], rolled[2], bonus))
    suggestion = _ancestries.roll_ancestry(random.randint)
    day = 0
    data, err = _load_characters()
    if data and not err:
        day = data.get("meta", {}).get("campaign_day") or 0
    try:
        GAME_STATE.setdefault("world_tick", {})["pc_create_pending"] = {
            "abilities": bonuses, "day": day}
        _save_game_state()
    except Exception as e:
        lines.append("WARNING: pending-roll stash persist failed ({})".format(e))
    lines.append("")
    lines.append("Ancestry suggestion (d10): **{}** - the player may keep it "
                 "or choose any of: {}".format(
                     suggestion,
                     ", ".join(_ancestries.ANCESTRY_D10[i] for i in range(1, 11))))
    lines.append("Swap rule: the player may swap the scores of TWO abilities "
                 "(one swap, or none).")
    lines.append(_pf.next_block(
        _pf.push_call("character", action="create_finalize",
                      name=(name if name else _pf.raw('"<name>"')),
                      ancestry=suggestion,
                      swap=_pf.raw('"<ABILITY,ABILITY or none>"'),
                      take5=_pf.raw("False")),
        label="player chooses swap/ancestry, then finalize (writes the sheet)"))
    return "\n".join(lines)

def _character_create_finalize(name, ancestry=None, swap="none", take5=False):
    """PC creation step 2 (CH p.5-6): validate the pending step-1 rolls, apply
    the player's swap, roll HP (1d8 / take-5 / ancestry hp_override_dice),
    sparks, gear and the starting boon, then WRITE the split sheet. Guard
    failures keep the pending stash so the player can retry."""
    take5 = (take5 is True)  # direct calls bypass pydantic: guard FieldInfo
    if not isinstance(swap, str):
        swap = "none"
    if not isinstance(ancestry, str):
        ancestry = None
    pending = GAME_STATE.get("world_tick", {}).get("pc_create_pending")
    if not isinstance(pending, dict) or not isinstance(pending.get("abilities"), dict):
        return ("No pending creation rolls found - run step 1 first.\n"
                + _pf.next_block(_pf.push_call("character", action="create"),
                                 label="roll the six abilities"))
    anc = _ancestries.get_ancestry(ancestry)
    if not anc:
        return "Unknown ancestry {!r}. Valid: {}.".format(
            ancestry, ", ".join(sorted(_ancestries.ANCESTRIES)))
    if not isinstance(name, str) or not name.strip():
        return "create_finalize requires a non-empty 'name'."
    name = name.strip()
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        return "Name {!r} produces an empty file key - use letters/digits.".format(name)
    data, err = _load_characters()
    if err:
        return err
    day = data.get("meta", {}).get("campaign_day") or 0
    stash_day = pending.get("day")
    if isinstance(stash_day, int) and stash_day != day:
        try:
            GAME_STATE.get("world_tick", {}).pop("pc_create_pending", None)
            _save_game_state()
        except Exception:
            pass
        return ("REJECTED: stale creation rolls from Day {} (today is Day {}) "
                "- run character(action=\"create\") again.\n".format(stash_day, day)
                + _pf.next_block(_pf.push_call("character", action="create"),
                                 label="reroll the six abilities"))
    dup_key = slug if slug in data.get("characters", {}) else None
    if not dup_key:
        dup_key = _find_character(data, name)[0] or _find_character(data, slug)[0]
    if dup_key:
        return ("REJECTED: '{}' is already on the roster (key '{}'). "
                "Pick a different name.".format(name, dup_key))

    bonuses = dict(pending["abilities"])
    swap_note = "none"
    sw = swap.strip().upper()
    if sw and sw != "NONE":
        parts = [p.strip() for p in sw.split(",")]
        if (len(parts) != 2 or parts[0] == parts[1]
                or any(p not in PC_ABILITY_ORDER for p in parts)):
            return ("swap must name two different abilities like 'STR,PSY' "
                    "(or 'none'). Got {!r}.".format(swap))
        a, b = parts
        bonuses[a], bonuses[b] = bonuses[b], bonuses[a]
        swap_note = "{} <-> {}".format(a, b)

    hooks = anc.get("creation_hooks") or {}

    # All dice up front, fail-fast before any sheet write.
    override = hooks.get("hp_override_dice")
    if override:
        n, _, faces = override.partition("d")
        hp = sum(random.randint(1, int(faces)) for _ in range(int(n)))
        hp_note = "{} = {} (Inevitable - never healable)".format(override, hp)
    elif take5:
        hp = 5
        hp_note = "took 5 (level-1 option)"
    else:
        hp = random.randint(1, 8)
        hp_note = "d8 = {}".format(hp)
    sparks = _ancestries.roll_sparks(ancestry, random.randint)
    mutations = [_roll_cacogen_mutation()
                 for _ in range(int(hooks.get("mutations_at_creation") or 0))]
    gear = _ancestries.roll_gear(random.randint)
    boon_roll = random.randint(1, 6)

    con = bonuses.get("CON", 0)
    capacity = 10 + con
    # Ration items in the SUPPLY ENGINE'S schema (survival.py consume_day reads
    # ration_type + integer rations; live ground truth: the character sheet json).
    carried = [
        {"id": "water_rations", "name": "Water Rations", "slots": 1,
         "type": "supply", "ration_type": "water", "rations": 3},
        {"id": "food_rations", "name": "Food Rations", "slots": 1,
         "type": "supply", "ration_type": "food", "rations": 3},
    ]
    # Per-ancestry physiology stamps - the fields the survival/photosynthesis
    # engines actually read (survival.py survival_block: explicit fields win).
    anc_key = ancestry.lower().strip()
    survival_blk = {}
    physio_extra = []
    av_base, av_source = 10, "unarmoured"
    if anc_key == "neobloom":
        survival_blk = {"needs_food": False,
                        "photosynthesis_window_days": 3,
                        "photosynthesis_last_fed_day": day}
        physio_extra.append(
            "Photosynthesises instead of eating (book 3-day window; "
            "E1 death-window tracker armed at creation, Day {}).".format(day))
    elif anc_key == "lithling":
        survival_blk = {"needs_water": False, "needs_food": False}
        av_base, av_source = 11, "Crystalline Flesh (AV 10 + Level, max 20)"
        physio_extra.append(
            "Does not eat or drink (Crystalline Flesh - survival needs off "
            "on the sheet).")
        physio_extra.append(
            "Mineral kind: no mineral wound table exists in the engine - "
            "biological used deliberately.")
    elif anc_key == "faa-nomad":
        survival_blk = {"death_days_thirst": 21}
        physio_extra.append(
            "Desert Metabolism: Deprived from thirst only after three days "
            "without drinking; death after three weeks (death_days_thirst 21 "
            "stamped on the sheet - the engine starts the Deprived record on "
            "the first unmet day; the DM owns the 3-day onset nuance).")
    elif anc_key == "synth":
        carried.append({"id": "synth_parts", "name": "Synth Parts", "slots": 1,
                        "type": "gear", "uses": 3,
                        "notes": ("Repairs (Synth rule): 1 hour + 1 part heals "
                                  "d8 + CON HP; at full HP heals one Wound. "
                                  "Parts stack in one item slot.")})
        physio_extra.append(
            "Synthetic: does not eat or breathe (wound_table 'synthetic' "
            "switches survival needs off); heals via Synth Parts repairs only.")
    if boon_roll == 2:  # B3 placeholder stamped into carried BEFORE saving
        carried.append({"id": "alchemists_crucible",
                        "name": "Alchemist's Crucible + Elixir (B3 pending)",
                        "slots": 1, "type": "gear", "day_acquired": day})

    appearance_bits = []
    for t in anc["spark_tables"]:
        rolled = sparks.get(t["title"])
        if not isinstance(rolled, dict):
            continue
        if t.get("band_table"):
            appearance_bits.append("{}: {}".format(t["title"], rolled.get("value")))
        else:
            appearance_bits.append("; ".join(
                "{}: {}".format(col, rolled.get(col)) for col in t["columns"]))
    rule_names = ", ".join(r["name"] for r in anc.get("special_rules", []))
    physiology = "{}. Special rules: {}.".format(anc["kind"], rule_names)
    if override:
        physiology += " HP is fixed at the creation roll - never healable (Inevitable)."
    if physio_extra:
        physiology += " " + " ".join(physio_extra)

    slots_used = sum(i.get("slots", 0) for i in carried)
    sheet = {
        "name": name,
        "player": True,  # the human player's PC -> Iron Law 3 (combat: must supply own rolls)
        "species": anc["name"],
        "pronouns": "",
        "role": "",
        "motivation": "",
        "level": 1,
        "xp": {"current": 0, "needed": 1},
        "hp": {"current": hp, "max": hp},
        "av": {"base": av_base, "unarmoured": av_base, "source": av_source, "conditional": []},
        "abilities": {ab: {"current": bonuses[ab], "base": bonuses[ab]}
                      for ab in PC_ABILITY_ORDER},
        "slot_capacity_bonus": con,
        "slot_capacity_total": capacity,
        "wound_table": ("synthetic" if "synthetic" in anc["kind"].lower()
                        else "biological"),
        "wounds": [],
        "wounds_slots_used": 0,
        "augmentations": {},
        "mystic_gifts": [],
        "gleam": 0,
        "bloomboons": [],
        "codices": [],
        "inventory": {"carried": carried, "stored": [],
                      "installed_permanent": [], "given_away": []},
        "slots_used": slots_used,
        "slots_remaining": capacity - slots_used,
        "appearance": " | ".join(appearance_bits),
        "physiology": physiology,
        "notes": {"sparks": sparks,
                  "creation": "Rolled Day {} (CH p.5-6)".format(day)},
        "special_traits": {},
        "ancestry_special_rules": copy.deepcopy(anc.get("special_rules", [])),
    }
    if mutations:
        sheet["special_traits"]["mutations"] = mutations
    if survival_blk:
        sheet["survival"] = survival_blk

    # Neobloom begins play with one Bloomboon (CH p.049: "You begin play with one
    # Bloomboon, rolled using a d20"). Roll + stamp it now so every Neobloom sheet
    # is book-correct at creation regardless of which DM runs it — the engine had
    # no creation-time Bloomboon path before. No dedup needed (the character's
    # first). Resolved through the SAME helper as level-up so effects match.
    bloomboon_creation = None
    if anc_key == "neobloom":
        _bb_all = json.loads(read_rules_data("NEOBLOOM_BLOOMBOONS.json"))
        _bb_roll = random.randint(1, 20)
        _bb = _bb_all.get(str(_bb_roll),
                          {"name": "Unknown", "effect": "Error loading bloomboon"})
        _bb_fx, _bb_levers = _apply_bloomboon_to_sheet(
            sheet, _bb, f"d20={_bb_roll} (creation)")
        bloomboon_creation = (_bb_roll, _bb, _bb_fx, _bb_levers)

    data.setdefault("characters", {})[slug] = sheet
    _save_single_character(slug, sheet, data)
    lines = []
    try:
        GAME_STATE.get("world_tick", {}).pop("pc_create_pending", None)
        _save_game_state()
    except Exception as e:
        lines.append("WARNING: pending-stash clear persist failed ({})".format(e))

    lines = [
        "**{} CREATED** - Level 1 {} (sheet written: characters/{}.json)".format(
            name.upper(), anc["name"], slug),
        "Abilities (swap: {}): ".format(swap_note) + ", ".join(
            "{} +{}".format(ab, bonuses[ab]) for ab in PC_ABILITY_ORDER),
        "HP: {}/{} ({}) | AV {} ({}) | Slots: {}/{} used".format(
            hp, hp, hp_note, av_base, av_source, slots_used, capacity),
        "Carried: " + ", ".join(i["name"] for i in carried),
        "",
        "**Sparks** ({}):".format(anc["name"]),
    ] + lines
    for bit in appearance_bits:
        lines.append("  " + bit)
    for rule in anc.get("special_rules", []):
        lines.append("  Special rule: **{}** - {}".format(rule["name"], rule["text"]))
    if mutations:
        lines.append("")
        lines.append("**Corrupted Blood** (cacogen creation hook - 3 mutations, "
                     "stamped on the sheet):")
        for m in mutations:
            lines.append("  {}: **{}** - {}".format(
                m.get("source", "?"), m["name"], m["effect"]))

    # Gear: two rolls on the explorer's gear table, recorded by the DM.
    item_a = _pc_gear_item(gear["gear_a"])
    item_b = _pc_gear_item(gear["gear_b"])
    lines.append("")
    lines.append("**Explorer's gear** (d20={}, d20={}): {} + {}".format(
        gear["rolls"][0], gear["rolls"][1],
        _isl.depletable_label(item_a) or item_a["name"],
        _isl.depletable_label(item_b) or item_b["name"]))
    inv_changes = json.dumps([
        {"character": name, "action": "add", "item": item_a},
        {"character": name, "action": "add", "item": item_b},
    ])
    lines.append(_pf.next_block(
        _pf.push_call("save_state",
                      session_summary="{} creation gear".format(name),
                      day=_pf.raw(str(day)),
                      inventory_changes=_pf.raw(inv_changes)),
        label="record the two gear items on the sheet"))

    # Starting boon (d6; the player may choose instead - DM lever).
    lines.append("")
    lines.append("**Starting boon** (d6={}): {}".format(
        boon_roll, PC_STARTING_BOONS[boon_roll]))
    if boon_roll == 1:
        boon_push = _pf.push_call("generate", action="weapon", tier="advanced")
    elif boon_roll == 2:
        boon_push = None
        lines.append("  'Alchemist's Crucible + Elixir (B3 pending)' stamped "
                     "into carried; elixir contents pending the B3 build.")
    elif boon_roll == 3:
        boon_push = _pf.push_call(
            "cybernetic", action="install", character_name=name,
            implant_name=_pf.raw('"<implant>"'),
            ability_slot=_pf.raw('"<STR|DEX|CON|INT|PSY|EGO>"'),
            effect=_pf.raw('"<effect>"'), day_installed=_pf.raw(str(day)))
    elif boon_roll == 4:
        boon_push = _pf.push_call("generate", action="exotica")
    elif boon_roll == 5:
        boon_push = _pf.push_call(
            "codex", action="add", character_name=name,
            codex_name=_pf.raw('"<codex>"'),
            equation_name=_pf.raw('"<equation>"'),
            effect=_pf.raw('"<effect>"'))
    else:
        boon_push = _pf.push_call("generate", action="gift")
    if boon_push:
        lines.append(_pf.next_block(boon_push, label="resolve the boon"))

    if bloomboon_creation:
        _bb_roll, _bb, _bb_fx, _bb_levers = bloomboon_creation
        lines.append("")
        lines.append("**Starting Bloomboon** (Neobloom begins play with one, "
                     "d20={}): **{}**".format(_bb_roll, _bb["name"]))
        lines.append("  {}".format(_bb["effect"]))
        for ln in _bb_fx:
            lines.append("  {}".format(ln))
        if _bb_levers:
            lines.append("  DM levers (not auto-applied - DM adjudicates):")
            lines.extend(_bb_levers)

    lines.append("")
    # Combat kit via chargen — the SINGLE source for it. chargen(weapon) offers
    # the book melee/ranged choice; chargen(armour) returns body armour + helm +
    # shield. Do NOT also roll chargen(full) or generate(weapon/armour) here: full
    # re-rolls the gear+boon create_finalize already persisted, and a second
    # weapon/armour roll diverges from what was shown (the kit-mismatch bug).
    lines.append(_pf.next_block(
        _pf.push_call("roll", action="chargen", table="weapon"),
        _pf.push_call("roll", action="chargen", table="armour"),
        label="roll the starting weapon (keep ONE: melee or ranged) + body armour "
              "+ helm + shield; record each via save_state inventory_changes "
              "(AV updates when armour is worn)"))
    return "\n".join(lines)

FOLLOWER_RANGED_ATTACKS = {
    "Old Revolver", "Bow", "Nomad's Rifle", "Lasrifle", "3 Ancient Grenades",
}

# ── Authored-sheet registration (the "crystallize any character" lever) ──────────
# The DM (inference layer) authors a full character sheet; the engine guarantees the
# STRUCTURE so combat/wounds/slots read it without silent breakage. Validates only the
# load-bearing fields the engine consumes; the DM owns the values.
_PC_ABILITY_KEYS = ("STR", "DEX", "CON", "INT", "PSY", "EGO")
_VALID_WOUND_TABLES = ("biological", "synthetic")


def _validate_character_sheet(sheet: dict) -> list:
    """Return human-readable problems with an authored sheet (empty list = valid)."""
    errs = []
    if not isinstance(sheet.get("level"), int):
        errs.append("'level' must be an integer")
    hp = sheet.get("hp")
    if not (isinstance(hp, dict) and isinstance(hp.get("current"), int)
            and isinstance(hp.get("max"), int)):
        errs.append("'hp' must be an object {current:int, max:int}")
    av = sheet.get("av")
    if not (isinstance(av, dict) and isinstance(av.get("base"), int)):
        errs.append("'av' must be an object {base:int, ...}")
    ab = sheet.get("abilities")
    if not isinstance(ab, dict):
        errs.append("'abilities' must be an object with the six ability scores")
    else:
        for k in _PC_ABILITY_KEYS:
            v = ab.get(k)
            if not (isinstance(v, dict) and isinstance(v.get("current"), int)):
                errs.append(f"abilities['{k}'] must be {{current:int, base:int}}")
    if sheet.get("wound_table") not in _VALID_WOUND_TABLES:
        errs.append(f"'wound_table' must be one of {list(_VALID_WOUND_TABLES)}")
    if not sheet.get("species"):
        errs.append("'species' is required (e.g. 'True-Kin', 'Cacogen', 'Newbeast')")
    return errs


def _normalize_character_sheet(sheet: dict) -> None:
    """Fill the optional containers the engine expects (so downstream reads never
    KeyError) and compute carry capacity from CON if the author omitted it. In place."""
    sheet.setdefault("pronouns", "")
    sheet.setdefault("role", "")
    sheet.setdefault("xp", {"current": 0, "needed": 1})
    sheet.setdefault("augmentations", {})
    sheet.setdefault("mystic_gifts", [])
    sheet.setdefault("gleam", 0)
    sheet.setdefault("bloomboons", [])
    sheet.setdefault("codices", [])
    sheet.setdefault("wounds", [])
    sheet.setdefault("wounds_slots_used", 0)
    sheet.setdefault("special_traits", {})
    inv = sheet.setdefault("inventory",
                           {"carried": [], "stored": [], "installed_permanent": [], "given_away": []})
    if isinstance(inv, dict):
        for k in ("carried", "stored", "installed_permanent", "given_away"):
            inv.setdefault(k, [])
    if "slot_capacity_total" not in sheet:
        con = sheet.get("abilities", {}).get("CON", {}).get("current", 0)
        sheet["slot_capacity_bonus"] = con
        sheet["slot_capacity_total"] = 10 + con  # CH carry rule: 10 + CON


def _character_register(name, sheet_json):
    """Persist an inference-authored character sheet — the single 'crystallize any
    character' path (recruited NPC, settlement resident, any improvised character that
    needs real stats). The DM authors the values; the engine validates the structure,
    recomputes the derived slot fields, and saves."""
    if not name:
        return "register requires the character name."
    if not sheet_json:
        return ("register requires 'sheet' — the full character sheet as JSON. Author the "
                "stat block: level, hp{current,max}, av{base}, "
                "abilities{STR..EGO:{current,base}}, wound_table (biological|synthetic), "
                "species — plus any flavor; the engine fills the rest.")
    try:
        sheet = json.loads(sheet_json) if isinstance(sheet_json, str) else sheet_json
    except (json.JSONDecodeError, TypeError) as e:
        return f"'sheet' is not valid JSON: {e}"
    if not isinstance(sheet, dict):
        return "'sheet' must be a JSON object (the full character sheet)."

    errs = _validate_character_sheet(sheet)
    if errs:
        return "Sheet rejected — fix and resubmit:\n" + "\n".join(f"  • {e}" for e in errs)

    sheet["name"] = name
    _normalize_character_sheet(sheet)
    _refresh_slot_fields(sheet)

    data, _ = _load_characters()
    slug = name.strip().lower().replace(" ", "_").replace("-", "_")
    _save_single_character(slug, sheet, data)

    hp, av = sheet["hp"], sheet["av"]
    return (f"✓ Registered **{name}** — Lv {sheet['level']} {sheet.get('species', '')}, "
            f"{hp['current']}/{hp['max']} HP, AV {av['base']}, "
            f"{sheet['slots_used']}/{sheet['slot_capacity_total']} slots used. "
            f"Validated + persisted.\n"
            + _pf.next_block(_pf.push_call("character", action="get", name=name),
                             label="verify the sheet"))


def _follower_species(description):
    """Pull the ancestry word out of a recruitment-table description when it is
    obvious; otherwise return the raw description."""
    m = re.search(r"\b(True-kin|Cacogen|Synth|Mycomorph|Neobloom|Lithling|"
                  r"Planeyfolk|Cacklemaw Exile|Faa Nomad|Newbeast|New-\w+)\b",
                  description, re.IGNORECASE)
    return m.group(0) if m else description

def _character_recruit_follower(leader_name, follower_name=None, recruit_roll=None):
    """Recruit a follower (CH p.61-62): d20 + the leader's EGO bonus on the
    recruitment table. ENFORCES the cap (combined follower Levels <= leader EGO
    bonus) BEFORE any sheet write. The roll is an OFFER, not a hire."""
    if not isinstance(follower_name, str) or not follower_name.strip():
        follower_name = None  # direct calls bypass pydantic: FieldInfo is not a name
    if not isinstance(recruit_roll, (int, str)) or isinstance(recruit_roll, bool):
        recruit_roll = None  # direct calls bypass pydantic: FieldInfo is not a roll
    data, err = _load_characters()
    if err:
        return err
    if not leader_name or not isinstance(leader_name, str):
        return "recruit_follower requires 'name' (the recruiting LEADER)."
    leader_key, leader = _find_character(data, leader_name)
    if not leader:
        return f"Leader '{leader_name}' not found."
    if leader.get("type") == "follower":
        return ("{} is a follower - followers cannot recruit followers "
                "(the cap hangs off a PC's EGO bonus, CH p.61).".format(
                    leader.get("name", leader_name)))
    cap, used = _followers.follower_level_cap(data["characters"], leader_key)
    day = data.get("meta", {}).get("campaign_day") or 0

    if recruit_roll is not None:
        total = int(recruit_roll)
        if not 0 <= total <= 30:
            return f"recruit_roll must be a total 0-30, got {total}."
        row = _followers.RECRUIT_TABLE[total]
        roll_note = "forced total {}".format(total)
    else:
        total, row = _followers.roll_recruit(random.randint, cap)
        roll_note = "d20 + EGO {} = {}".format(cap, total)

    level = row["level"]
    if used + level > cap:
        return ("**RECRUIT REJECTED** - over the command cap (CH p.61).\n"
                "  {} (total {}): {} is Level {}.\n"
                "  {}'s EGO bonus {} - levels already in service {} = room for "
                "{}.\n"
                "  Dismiss a follower first if you want this one: "
                "character(action=\"dismiss_follower\", name=\"<follower>\")."
                .format(roll_note, total, row["name"], level,
                        leader.get("name", leader_name), cap, used,
                        max(0, cap - used)))

    fname = follower_name or row["name"]
    slug = re.sub(r"[^a-z0-9]+", "_", fname.lower()).strip("_")
    if not slug:
        return "Name {!r} produces an empty file key - use letters/digits.".format(fname)
    dup_key = slug if slug in data.get("characters", {}) else None
    if not dup_key:
        dup_key = _find_character(data, fname)[0] or _find_character(data, slug)[0]
    if dup_key:
        return ("REJECTED: '{}' is already on the roster (key '{}'). "
                "Pass follower_name to rename the recruit.".format(fname, dup_key))

    atk = row["attack"]
    atk_range = "ranged" if atk["name"] in FOLLOWER_RANGED_ATTACKS else "melee"
    atk_dt = atk.get("damage_type") or (
        "blast" if "blast" in atk.get("tags", []) else None)
    weapon = ws.build_weapon(atk["name"], atk["damage"], 1,
                             prose_tags=atk.get("tags"),
                             range=atk_range, damage_type=atk_dt)
    if atk.get("note"):
        weapon["notes"] = atk["note"]

    capacity = 10 + level
    sheet = {
        "name": fname,
        "type": "follower",
        "leader": leader_key,
        "species": _follower_species(row["description"]),
        "pronouns": "",
        "role": "follower",
        "level": level,
        "xp": {"current": 0, "needed": max(1, level)},
        "hp": {"current": row["hp"], "max": row["hp"]},
        "av": {"base": row["av"], "source": "follower", "conditional": []},
        "ml": row["ml"],
        # Followers have no ability array in the book; zero is the engine-safe
        # identity for every save/slot consumer.
        "abilities": {ab: {"current": 0, "base": 0} for ab in PC_ABILITY_ORDER},
        "slot_capacity_bonus": 0,
        "slot_capacity_total": capacity,
        "wound_table": ("synthetic" if "synth" in row["description"].lower()
                        else "biological"),
        "wounds": [],
        "wounds_slots_used": 0,
        "augmentations": {},
        "mystic_gifts": [],
        "gleam": 0,
        "bloomboons": [],
        "codices": [],
        # 0 carried rations - followers eat from the party pool; survival
        # needs stay ON via the wound_table default.
        "inventory": {"carried": [weapon], "stored": [],
                      "installed_permanent": [], "given_away": []},
        "slots_used": weapon["slots"],
        "slots_remaining": capacity - weapon["slots"],
        "appearance": row["description"],
        "notes": {"recruited": {"day": day, "total": total,
                                "leader": leader_key}},
        "special_traits": {},
    }
    data.setdefault("characters", {})[slug] = sheet
    _save_single_character(slug, sheet, data)

    lines = [
        "**FOLLOWER RECRUITED** (CH p.62, {})".format(roll_note),
        "  **{}** - Level {} | HP {}/{} | AV {} | ML +{} | {} ({}, {})".format(
            fname, level, row["hp"], row["hp"], row["av"], row["ml"],
            atk["name"], atk["damage"], atk_range),
        "  {}".format(row["description"]),
        "  Sheet written: characters/{}.json (leader: {})".format(
            slug, leader.get("name", leader_key)),
        "  Command cap: EGO bonus {} - levels in service now {}/{}.".format(
            cap, used + level, cap),
        "",
        "The table roll is an OFFER, not a hire - record only if hired "
        "in-fiction; otherwise delete the sheet via "
        "character(action=\"dismiss_follower\", name=\"{}\").".format(fname),
        _pf.next_block(
            _pf.push_call("relationship", action="set",
                          entity1=leader.get("name", leader_key),
                          entity2=fname, status="follower",
                          notes="Sworn follower (CH p.61)",
                          last_interaction_day=_pf.raw(str(day))),
            _pf.push_call("supply", action="status"),
            label="record the bond + the party gained a mouth"),
    ]
    return "\n".join(lines)

def _character_follower_level_up(name):
    """Follower advancement (CH p.61): at the XP threshold, +d8 max HP ONLY -
    followers have no ability array. Over-cap after the level is WARNED, not
    rejected (the book caps command, not growth)."""
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "follower_level_up requires 'name' (the follower)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    if char.get("type") != "follower":
        return ("{} is not a follower - use level_up for PCs.".format(
            char.get("name", name)))
    level = int(char.get("level", 0))
    xp = char.get("xp") or {}
    cur = int(xp.get("current", 0))
    needed = int(xp.get("needed", max(1, level)))
    if cur < needed:
        return ("{} has {}/{} XP - not enough to level up "
                "(followers advance at the PC rate, CH p.61).".format(
                    char.get("name", name), cur, needed))
    gain = random.randint(1, 8)
    new_level = level + 1
    hp = char.get("hp") or {}
    hp["max"] = int(hp.get("max", 0)) + gain
    hp["current"] = int(hp.get("current", 0)) + gain
    char["hp"] = hp
    char["level"] = new_level
    char["xp"] = {"current": 0, "needed": new_level}
    capacity = 10 + new_level
    char["slot_capacity_total"] = capacity
    char["slots_remaining"] = capacity - int(char.get("slots_used", 0))
    _save_single_character(key, char, data)

    lines = [
        "**{} LEVELS UP** - Level {} -> {} (follower, CH p.61)".format(
            char.get("name", name).upper(), level, new_level),
        "  +d8 max HP: rolled {} -> HP {}/{} (abilities untouched - "
        "followers have none)".format(gain, hp["current"], hp["max"]),
        "  XP reset: 0/{} | Item slots: {}".format(new_level, capacity),
    ]
    leader_key = char.get("leader")
    if leader_key:
        cap, used = _followers.follower_level_cap(data["characters"], leader_key)
        if used > cap:
            leader_name = data["characters"].get(leader_key, {}).get(
                "name", leader_key)
            lines.append(
                "  WARNING: {}'s followers now total Level {} vs EGO bonus {} "
                "- OVER the command cap (CH p.61). The book caps command, not "
                "growth; someone must go.".format(leader_name, used, cap))
            lines.append(_pf.next_block(
                _pf.push_call("character", action="dismiss_follower",
                              name=_pf.raw('"<follower>"'),
                              reason=_pf.raw('"<why they left>"')),
                label="resolve the over-cap command"))
    return "\n".join(lines)

def _character_dismiss_follower(name, reason=None):
    """Dismiss a follower: stamp notes.departed, save once more, then move the
    sheet to characters/departed/ (the roster loader globs only
    characters/*.json, so the move IS the removal - file preserved for return
    arcs)."""
    if not isinstance(reason, str) or not reason.strip():
        reason = None  # direct calls bypass pydantic: FieldInfo is not a reason
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "dismiss_follower requires 'name' (the follower)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    if char.get("type") != "follower":
        return ("{} is not a follower - dismiss_follower only retires "
                "follower sheets.".format(char.get("name", name)))
    day = data.get("meta", {}).get("campaign_day") or 0
    notes = char.get("notes")
    if not isinstance(notes, dict):
        notes = {"prior": notes} if notes else {}
        char["notes"] = notes
    notes["departed"] = {"day": day, "reason": reason or "unspecified"}
    _save_single_character(key, char, data)

    moved = _move_sheet_to_departed(key)
    data.get("characters", {}).pop(key, None)

    lines = [
        "**{} DEPARTS** (Day {}) - {}".format(
            char.get("name", name).upper(), day, reason or "unspecified"),
    ]
    if moved:
        lines.append("  Sheet moved to characters/departed/{}.json - off the "
                     "roster, preserved for return arcs.".format(key))
    else:
        lines.append("  WARNING: characters/{}.json not found on disk - "
                     "departure stamped but no file moved.".format(key))
    return "\n".join(lines)

MERCENARY_RANGED_ATTACKS = {
    "Laspistol", "Chrome Revolver", "Quicksilver Sling", "Nomad's Rifle",
    "Ornate Lasrifle", "Plasma Rifle", "Blasphemous Shotgun", "Ritual Crossbow",
    "Grenade Launcher", "Inferno Cannon", "Heavy Lasgun", "Tesla Cannon",
    "Railgun", "Port-A-Cannon", "Annihilation Ray",
}

def _character_recruit_mercenary(leader_name, merc_name=None, recruit_roll=None):
    """Recruit a mercenary (CH p.63-64): d20 + the leader's EGO bonus on the
    mercenary table. ENFORCES a SEPARATE cap (combined mercenary Levels <=
    leader EGO bonus; distinct from the follower pool) BEFORE any sheet write.
    Mercs have FIXED sheets - no leveling. The roll is an OFFER, not a hire."""
    if not isinstance(merc_name, str) or not merc_name.strip():
        merc_name = None  # direct calls bypass pydantic: FieldInfo is not a name
    if not isinstance(recruit_roll, (int, str)) or isinstance(recruit_roll, bool):
        recruit_roll = None  # direct calls bypass pydantic: FieldInfo is not a roll
    data, err = _load_characters()
    if err:
        return err
    if not leader_name or not isinstance(leader_name, str):
        return "recruit_mercenary requires 'name' (the recruiting LEADER)."
    leader_key, leader = _find_character(data, leader_name)
    if not leader:
        return f"Leader '{leader_name}' not found."
    if leader.get("type") in ("follower", "mercenary"):
        return ("{} is a hireling - hirelings cannot recruit mercenaries "
                "(the cap hangs off a PC's EGO bonus, CH p.63).".format(
                    leader.get("name", leader_name)))
    cap, used = _mercenaries.mercenary_level_cap(data["characters"], leader_key)
    day = data.get("meta", {}).get("campaign_day") or 0

    if recruit_roll is not None:
        total = int(recruit_roll)
        if not 0 <= total <= 30:
            return f"recruit_roll must be a total 0-30, got {total}."
        row = _mercenaries.RECRUIT_TABLE[total]
        roll_note = "forced total {}".format(total)
    else:
        total, row = _mercenaries.roll_recruit(random.randint, cap)
        roll_note = "d20 + EGO {} = {}".format(cap, total)

    level = row["level"]
    if used + level > cap:
        return ("**RECRUIT REJECTED** - over the command cap (CH p.63).\n"
                "  {} (total {}): {} is Level {}.\n"
                "  {}'s EGO bonus {} - mercenary levels already in service {} = "
                "room for {}.\n"
                "  Dismiss a mercenary first if you want this one: "
                "character(action=\"dismiss_mercenary\", name=\"<mercenary>\")."
                .format(roll_note, total, row["name"], level,
                        leader.get("name", leader_name), cap, used,
                        max(0, cap - used)))

    fname = merc_name or row["name"]
    slug = re.sub(r"[^a-z0-9]+", "_", fname.lower()).strip("_")
    if not slug:
        return "Name {!r} produces an empty file key - use letters/digits.".format(fname)
    dup_key = slug if slug in data.get("characters", {}) else None
    if not dup_key:
        dup_key = _find_character(data, fname)[0] or _find_character(data, slug)[0]
    if dup_key:
        return ("REJECTED: '{}' is already on the roster (key '{}'). "
                "Pass merc_name to rename the recruit.".format(fname, dup_key))

    atk = row["attack"]
    atk_range = "ranged" if atk["name"] in MERCENARY_RANGED_ATTACKS else "melee"
    atk_dt = atk.get("damage_type") or (
        "blast" if "blast" in atk.get("tags", []) else None)
    # build_weapon stores `damage` as a raw string - "2d10" (Uck) passes through
    # intact; the second die is NOT dropped.
    weapon = ws.build_weapon(atk["name"], atk["damage"], 1,
                             prose_tags=atk.get("tags"),
                             range=atk_range, damage_type=atk_dt)
    if atk.get("note"):
        weapon["notes"] = atk["note"]

    capacity = 10 + level
    sheet = {
        "name": fname,
        "type": "mercenary",
        "leader": leader_key,
        "species": _follower_species(row["description"]),
        "pronouns": "",
        "role": "mercenary",
        "level": level,
        # Mercs NEVER level - no xp/level-up path (CH p.63).
        "hp": {"current": row["hp"], "max": row["hp"]},
        "av": {"base": row["av"], "source": "mercenary", "conditional": []},
        "ml": row["ml"],
        "pay_owed": False,
        "carries_baggage": False,
        # Mercs have no ability array in the book; zero is the engine-safe
        # identity for every save/slot consumer.
        "abilities": {ab: {"current": 0, "base": 0} for ab in PC_ABILITY_ORDER},
        "slot_capacity_bonus": 0,
        "slot_capacity_total": capacity,
        "wound_table": ("synthetic" if "synth" in row["description"].lower()
                        else "biological"),
        "wounds": [],
        "wounds_slots_used": 0,
        "augmentations": {},
        "mystic_gifts": [],
        "gleam": 0,
        "bloomboons": [],
        "codices": [],
        # 0 carried rations - mercs eat from the party pool; survival needs
        # stay ON via the wound_table default.
        "inventory": {"carried": [weapon], "stored": [],
                      "installed_permanent": [], "given_away": []},
        "slots_used": weapon["slots"],
        "slots_remaining": capacity - weapon["slots"],
        "appearance": row["description"],
        "notes": {"recruited": {"day": day, "total": total,
                                "leader": leader_key}},
        "special_traits": {},
    }
    data.setdefault("characters", {})[slug] = sheet
    _save_single_character(slug, sheet, data)

    lines = [
        "**MERCENARY RECRUITED** (CH p.64, {})".format(roll_note),
        "  **{}** - Level {} | HP {}/{} | AV {} | ML +{} | {} ({}, {})".format(
            fname, level, row["hp"], row["hp"], row["av"], row["ml"],
            atk["name"], atk["damage"], atk_range),
        "  {}".format(row["description"]),
        "  Sheet written: characters/{}.json (leader: {})".format(
            slug, leader.get("name", leader_key)),
        "  Command cap: EGO bonus {} - mercenary levels in service now {}/{} "
        "(SEPARATE from the follower pool).".format(cap, used + level, cap),
        "  Pay: 1 Exotica per expedition. Mark expeditions with "
        "character(action=\"mercenary_expedition_end\"). Unpaid = they leave "
        "AND become a sworn foe (CH p.63).",
        "  Mercenary: takes orders but refuses obviously suicidal ones, and "
        "will NOT carry baggage (CH p.63).",
        "",
        "The table roll is an OFFER, not a hire - record only if hired "
        "in-fiction; otherwise delete the sheet via "
        "character(action=\"dismiss_mercenary\", name=\"{}\").".format(fname),
        _pf.next_block(
            _pf.push_call("relationship", action="set",
                          entity1=leader.get("name", leader_key),
                          entity2=fname, status="mercenary",
                          notes="Hired mercenary (CH p.63)",
                          last_interaction_day=_pf.raw(str(day))),
            _pf.push_call("supply", action="status"),
            label="record the contract + the party gained a mouth"),
    ]
    return "\n".join(lines)

def _character_dismiss_mercenary(name, reason=None):
    """Dismiss a mercenary: stamp notes.departed, save once more, then move the
    sheet to characters/departed/. If the merc is owed pay (pay_owed True),
    they leave as a SWORN FOE (CH p.63) - seed the antagonist board + a
    World-Tick revenge clock BEFORE the move."""
    if not isinstance(reason, str) or not reason.strip():
        reason = None  # direct calls bypass pydantic: FieldInfo is not a reason
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "dismiss_mercenary requires 'name' (the mercenary)."
    key, merc = _find_character(data, name)
    if not merc:
        return f"Character '{name}' not found."
    if merc.get("type") != "mercenary":
        return ("{} is not a mercenary - dismiss_mercenary only retires "
                "mercenary sheets.".format(merc.get("name", name)))
    day = data.get("meta", {}).get("campaign_day") or 0
    notes = merc.get("notes")
    if not isinstance(notes, dict):
        notes = {"prior": notes} if notes else {}
        merc["notes"] = notes
    notes["departed"] = {"day": day, "reason": reason or "unspecified"}
    _save_single_character(key, merc, data)

    mname = merc.get("name", name)
    lines = [
        "**{} DEPARTS** (Day {}) - {}".format(
            mname.upper(), day, reason or "unspecified"),
    ]
    if merc.get("pay_owed"):
        lines.append("**{} leaves as a SWORN FOE** - unpaid wages (CH p.63). "
                     "The Referee plans the revenge.".format(mname))
        lines.append(_pf.next_block(
            _pf.push_call("antagonist", action="add_seed",
                          threat_name=mname,
                          details=_pf.raw('"ex-mercenary; revenge for unpaid '
                                          'wages"'),
                          day=_pf.raw(str(day))),
            _pf.push_call("thread", action="add",
                          thread_id=_pf.raw('"%s_revenge"' % key),
                          title=_pf.raw('"%s\'s revenge"' % mname),
                          description=_pf.raw('"Sworn-foe ex-mercenary nursing '
                                             'a grudge over unpaid wages."'),
                          introduced_day=_pf.raw(str(day)),
                          clock_due_day=_pf.raw("<day the grudge ripens, e.g. %d>"
                                                % (day + 14)),
                          clock_label=_pf.raw('"%s comes for revenge"' % mname)),
            label="seed the sworn foe + a World-Tick revenge clock"))

    moved = _move_sheet_to_departed(key)
    data.get("characters", {}).pop(key, None)
    if moved:
        lines.append("  Sheet moved to characters/departed/{}.json - off the "
                     "roster, preserved for return arcs.".format(key))
    else:
        lines.append("  WARNING: characters/{}.json not found on disk - "
                     "departure stamped but no file moved.".format(key))
    return "\n".join(lines)

def _write_companion_sheet(data, leader, leader_key, row, slug_hint,
                           custom_name, kind, rider_key=None):
    """Write a pet/steed sheet from a catalog row. kind is 'pet' or 'steed'.
    Returns the push string. HP = row['hp'] if given (Level-0 hawk = 1) else
    a Level-derived default (level*4, min 1) - pets/steeds have no HP die in
    the book, so we use a stable Level-scaled HP."""
    day = data.get("meta", {}).get("campaign_day") or 0
    fname = custom_name or row["name"]
    # Roster key: a custom name is slugged from its display text; otherwise the
    # stable catalog slug (slug_hint) IS the key (so 'exultants_hawk' stays
    # 'exultants_hawk', not 'exultant_s_hawk' from the apostrophe in the name).
    slug_src = custom_name or slug_hint or fname
    slug = re.sub(r"[^a-z0-9]+", "_", slug_src.lower()).strip("_")
    if not slug:
        return "Name {!r} produces an empty file key - use letters/digits.".format(fname)
    dup = slug if slug in data.get("characters", {}) else (
        _find_character(data, fname)[0] or _find_character(data, slug)[0])
    if dup:
        return ("REJECTED: '{}' is already on the roster (key '{}'). Pass "
                "custom_name to rename.".format(fname, dup))
    hp_val = int(row.get("hp", max(1, int(row["level"]) * 4)))
    atk = row["attack"]
    atk_dt = ("blast" if "blast" in atk.get("tags", []) else
              ("electrical" if "electrical" in atk.get("tags", []) else None))
    weapon = ws.build_weapon(atk["name"], atk["damage"], 1,
                             prose_tags=atk.get("tags"), range="melee",
                             damage_type=atk_dt)
    if atk.get("note"):
        weapon["notes"] = atk["note"]
    # Item slots: steeds always carry one (int or the Thin Mare "Special"=100);
    # pets only some. Default 0 for slotless pets.
    raw_slots = row.get("item_slots", 0)
    capacity = 100 if raw_slots == "Special" else int(raw_slots or 0)
    wound_table = {"Biological": "biological", "Synthetic": "synthetic",
                   "Mechanical": "mechanical"}.get(row["kind"], "biological")
    sheet = {
        "name": fname, "type": kind, "leader": leader_key,
        "species": row["kind"], "pronouns": "", "role": kind,
        "level": int(row["level"]),
        "hp": {"current": hp_val, "max": hp_val},
        "av": {"base": int(row["av"]), "source": kind, "conditional": []},
        "ml": int(row["morale"]),
        "abilities": {ab: {"current": 0, "base": 0} for ab in PC_ABILITY_ORDER},
        "slot_capacity_bonus": 0, "slot_capacity_total": capacity,
        "wound_table": wound_table, "wounds": [], "wounds_slots_used": 0,
        "augmentations": {}, "mystic_gifts": [], "gleam": 0,
        "bloomboons": [], "codices": [],
        "survival": dict(row["survival"]),
        "inventory": {"carried": [weapon], "stored": [],
                      "installed_permanent": [], "given_away": []},
        "slots_used": weapon["slots"],
        "slots_remaining": capacity - weapon["slots"],
        "appearance": row.get("special", ""),
        "notes": {"acquired": {"day": day, "leader": leader_key}},
        "special_traits": {},
    }
    if kind == "steed":
        sheet["mounted_by"] = rider_key  # None until ridden
        sheet["item_slots_label"] = ("Special (hypergeometric, d100 retrieval)"
                                     if raw_slots == "Special" else str(capacity))
    data.setdefault("characters", {})[slug] = sheet
    _save_single_character(slug, sheet, data)
    cap, used = _followers.follower_level_cap(data["characters"], leader_key)
    label = "PET ACQUIRED" if kind == "pet" else "STEED ACQUIRED"
    feed = ("eats 1 ration/day" if sheet["survival"].get("needs_food")
            else "does not need feeding")
    lines = [
        "**{}** (CH p.65) - {}".format(label, fname),
        "  Level {} | HP {}/{} | AV {} | ML +{} | {} ({})".format(
            sheet["level"], hp_val, hp_val, row["av"], row["morale"],
            atk["name"], atk["damage"]),
        "  {}".format(row.get("special") or "(no special trait)"),
        "  Sheet: characters/{}.json (owner: {}) - {}.".format(
            slug, leader.get("name", leader_key), feed),
        "  Pooled command cap: EGO bonus {} - companion levels now {}/{} "
        "(shared with followers; mercenaries separate).".format(cap, used, cap),
    ]
    if kind == "steed":
        lines.append("  Cargo: {} item slots. Ride with "
                     "character(action=\"ride_steed\", name=\"{}\", rider=\"<PC>\")."
                     .format(sheet["item_slots_label"], fname))
    lines.append(_pf.next_block(
        _pf.push_call("relationship", action="set",
                      entity1=leader.get("name", leader_key), entity2=fname,
                      status=kind, notes="Acquired {} (CH p.65)".format(kind),
                      last_interaction_day=_pf.raw(str(day))),
        _pf.push_call("supply", action="status"),
        label="record the bond + the party gained a mouth"))
    return "\n".join(lines)

def _character_acquire_pet(leader_name, companion_type=None, custom_name=None):
    """Acquire a pet (CH p.65-68): instantiate a fixed catalog stat block as a
    type='pet' sheet under a PC leader. Pets are bought/found/tamed (NO recruit
    roll). Pooled command cap (followers+pets+steeds <= leader EGO bonus, p.65)
    is enforced BEFORE the write; Level-0 creatures are always allowed (they do
    not count toward the cap but must still be fed)."""
    if not isinstance(companion_type, str) or not companion_type.strip():
        return ("acquire_pet requires 'companion_type' (a catalog slug, e.g. "
                "'ray_cat'). Known pets: " + ", ".join(sorted(_pets.PETS)))
    if not isinstance(custom_name, str) or not custom_name.strip():
        custom_name = None
    data, err = _load_characters()
    if err:
        return err
    if not leader_name or not isinstance(leader_name, str):
        return "acquire_pet requires 'name' (the owning PC leader)."
    leader_key, leader = _find_character(data, leader_name)
    if not leader:
        return f"Leader '{leader_name}' not found."
    if leader.get("type") in ("follower", "mercenary", "pet", "steed"):
        return ("{} is a hireling - only a PC can own pets (the cap hangs off a "
                "PC's EGO bonus, CH p.65).".format(leader.get("name", leader_name)))
    row = _pets.pet_block(companion_type)
    if not row:
        return ("Unknown pet '{}'. Known pets: {}".format(
            companion_type, ", ".join(sorted(_pets.PETS))))
    cap, used = _followers.follower_level_cap(data["characters"], leader_key)
    level = int(row["level"])
    if level > 0 and used + level > cap:
        return ("**REJECTED** - over the pooled command cap (CH p.65).\n"
                "  {} is Level {}; {}'s EGO bonus {} - companion levels in "
                "service {} = room for {}.\n"
                "  Level-0 creatures are exempt. Dismiss a companion first: "
                "character(action=\"dismiss_companion\", name=\"<name>\")."
                .format(row["name"], level, leader.get("name", leader_name),
                        cap, used, max(0, cap - used)))
    return _write_companion_sheet(data, leader, leader_key, row,
                                  companion_type, custom_name, kind="pet")

def _steed_ridden_by(data, rider_key):
    """Name of the steed currently ridden by rider_key, or None."""
    for k, c in (data or {}).get("characters", {}).items():
        if c.get("type") == "steed" and c.get("mounted_by") == rider_key:
            return c.get("name", k)
    return None

def _character_acquire_steed(leader_name, companion_type=None,
                             custom_name=None, rider=None):
    """Acquire a steed (CH p.69-72): a type='steed' sheet with a full item_slots
    cargo container sized to its slot stat. Pooled command cap enforced (p.65).
    Optionally set the rider now (one steed per PC); validated via the same path
    as ride_steed."""
    if not isinstance(companion_type, str) or not companion_type.strip():
        return ("acquire_steed requires 'companion_type' (a catalog slug, e.g. "
                "'zorse'). Known steeds: " + ", ".join(sorted(_pets.STEEDS)))
    if not isinstance(custom_name, str) or not custom_name.strip():
        custom_name = None
    if not isinstance(rider, str) or not rider.strip() or rider.lower() == "none":
        rider = None
    data, err = _load_characters()
    if err:
        return err
    if not leader_name or not isinstance(leader_name, str):
        return "acquire_steed requires 'name' (the owning PC leader)."
    leader_key, leader = _find_character(data, leader_name)
    if not leader:
        return f"Leader '{leader_name}' not found."
    if leader.get("type") in ("follower", "mercenary", "pet", "steed"):
        return ("{} is a hireling - only a PC can own steeds (CH p.65).".format(
            leader.get("name", leader_name)))
    row = _pets.steed_block(companion_type)
    if not row:
        return ("Unknown steed '{}'. Known steeds: {}".format(
            companion_type, ", ".join(sorted(_pets.STEEDS))))
    cap, used = _followers.follower_level_cap(data["characters"], leader_key)
    level = int(row["level"])
    if level > 0 and used + level > cap:
        return ("**REJECTED** - over the pooled command cap (CH p.65).\n"
                "  {} is Level {}; {}'s EGO bonus {} - companion levels in "
                "service {} = room for {}.\n"
                "  Dismiss a companion first: character(action="
                "\"dismiss_companion\", name=\"<name>\").".format(
                    row["name"], level, leader.get("name", leader_name),
                    cap, used, max(0, cap - used)))
    rider_key = None
    if rider is not None:
        rider_key, rider_char = _find_character(data, rider)
        if not rider_char:
            return f"Rider '{rider}' not found - acquire without a rider or fix the name."
        if not _is_pc_sheet(rider_char):
            return f"{rider} is not a PC - only PCs ride steeds (CH p.69)."
        existing = _steed_ridden_by(data, rider_key)
        if existing:
            return ("{} already rides {} - each PC may ride only ONE steed "
                    "(CH p.69). Dismount first with ride_steed rider=none.".format(
                        rider, existing))
    return _write_companion_sheet(data, leader, leader_key, row,
                                  companion_type, custom_name, kind="steed",
                                  rider_key=rider_key)

def _character_level_up_pet(name, hp_roll=None):
    """Pet advancement (CH p.65): a PC may give XP to a pet -> +d8 HP AND +1 item
    slot; AV/morale/damage unchanged. Pets only (steeds do not advance, R-D4e).
    Over the pooled cap after the level is WARNED, not rejected (the book caps
    command, not growth - mirrors follower_level_up)."""
    if not isinstance(hp_roll, int) or isinstance(hp_roll, bool):
        hp_roll = None
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "level_up_pet requires 'name' (the pet)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    if char.get("type") != "pet":
        return ("{} is not a pet - steeds do not advance (CH p.69), and PCs use "
                "level_up.".format(char.get("name", name)))
    level = int(char.get("level", 0))
    xp = char.get("xp") or {}
    cur = int(xp.get("current", 0))
    needed = int(xp.get("needed", max(1, level)))
    if cur < needed:
        return ("{} has {}/{} XP - not enough to level up (gift more XP first)."
                .format(char.get("name", name), cur, needed))
    gain = hp_roll if (hp_roll and 1 <= hp_roll <= 8) else random.randint(1, 8)
    new_level = level + 1
    hp = char.get("hp") or {}
    hp["max"] = int(hp.get("max", 0)) + gain
    hp["current"] = int(hp.get("current", 0)) + gain
    char["hp"] = hp
    char["level"] = new_level
    char["xp"] = {"current": 0, "needed": new_level}
    new_cap = int(char.get("slot_capacity_total", 0)) + 1
    char["slot_capacity_total"] = new_cap
    char["slots_remaining"] = new_cap - int(char.get("slots_used", 0))
    _save_single_character(key, char, data)
    lines = [
        "**{} LEVELS UP** - Level {} -> {} (pet, CH p.65)".format(
            char.get("name", name).upper(), level, new_level),
        "  +d8 HP: rolled {} -> HP {}/{}; +1 item slot -> {} slots "
        "(AV/morale/damage unchanged).".format(
            gain, hp["current"], hp["max"], new_cap),
    ]
    leader_key = char.get("leader")
    if leader_key:
        cap, used = _followers.follower_level_cap(data["characters"], leader_key)
        if used > cap:
            lines.append("  WARNING: {}'s companions now total Level {} vs EGO "
                         "bonus {} - OVER the pooled cap (p.65). The book caps "
                         "command, not growth; someone must go.".format(
                             data["characters"].get(leader_key, {}).get(
                                 "name", leader_key), used, cap))
    return "\n".join(lines)

def _character_ride_steed(name, rider=None):
    """Set or clear a steed's rider (CH p.69: each PC may ride ONE steed).
    rider='' or 'none' dismounts. Enforces one steed per PC."""
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "ride_steed requires 'name' (the steed)."
    key, steed = _find_character(data, name)
    if not steed:
        return f"Character '{name}' not found."
    if steed.get("type") != "steed":
        return f"{steed.get('name', name)} is not a steed."
    dismount = (not isinstance(rider, str) or not rider.strip()
                or rider.lower() == "none")
    if dismount:
        steed["mounted_by"] = None
        _save_single_character(key, steed, data)
        return "{} dismounts - the steed is now unridden.".format(
            steed.get("name", name))
    rider_key, rider_char = _find_character(data, rider)
    if not rider_char:
        return f"Rider '{rider}' not found."
    if not _is_pc_sheet(rider_char):
        return f"{rider} is not a PC - only PCs ride steeds (CH p.69)."
    existing = _steed_ridden_by(data, rider_key)
    if existing and existing != steed.get("name", name):
        return ("{} already rides {} - each PC may ride only ONE steed (CH "
                "p.69). Dismount that one first (ride_steed rider=none).".format(
                    rider, existing))
    steed["mounted_by"] = rider_key
    _save_single_character(key, steed, data)
    cargo = steed.get("item_slots_label", str(steed.get("slot_capacity_total", 0)))
    return ("**{} MOUNTS {}** (CH p.69). Cargo available: {} item slots - stash "
            "gear on the steed via save_state inventory_changes targeting "
            "\"{}\".".format(rider, steed.get("name", name), cargo,
                             steed.get("name", name)))

def _character_dismiss_companion(name, reason=None):
    """Retire a pet or steed (sell/release/death-in-fiction): stamp departure,
    save, then move the sheet to characters/departed/. PCs/followers/mercenaries
    use their own paths."""
    if not isinstance(reason, str) or not reason.strip():
        reason = None
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "dismiss_companion requires 'name' (the pet or steed)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    if char.get("type") not in ("pet", "steed"):
        return ("{} is not a pet or steed - use dismiss_follower / "
                "dismiss_mercenary for hirelings.".format(char.get("name", name)))
    day = data.get("meta", {}).get("campaign_day") or 0
    notes = char.get("notes")
    if not isinstance(notes, dict):
        notes = {"prior": notes} if notes else {}
        char["notes"] = notes
    notes["departed"] = {"day": day, "reason": reason or "unspecified"}
    _save_single_character(key, char, data)
    moved = _move_sheet_to_departed(key)
    data.get("characters", {}).pop(key, None)
    lines = ["**{} DEPARTS** (Day {}) - {}".format(
        char.get("name", name).upper(), day, reason or "unspecified")]
    if moved:
        lines.append("  Sheet moved to characters/departed/{}.json.".format(key))
    else:
        lines.append("  WARNING: characters/{}.json not found on disk.".format(key))
    return "\n".join(lines)

def _character_acquire_vehicle(owner_name, vehicle_type=None, custom_name=None):
    """Acquire a vehicle (CH pp.73-76 + homebrew): instantiate a catalog stat
    block as a type='vehicle' sheet (lands in the vehicles/ dir). Vehicles are
    property - NO command cap. Hull is a {current,max} dict (mirrors hp so the
    combat/repair paths share the shape)."""
    if not isinstance(vehicle_type, str) or not vehicle_type.strip():
        return ("acquire_vehicle requires 'vehicle_type' (a catalog slug, e.g. "
                "'dune_skuggy'). Known: " + ", ".join(sorted(_vehicles.VEHICLES)))
    if not isinstance(custom_name, str) or not custom_name.strip():
        custom_name = None
    data, err = _load_characters()
    if err:
        return err
    if not owner_name or not isinstance(owner_name, str):
        return "acquire_vehicle requires 'name' (the owning PC)."
    owner_key, owner = _find_character(data, owner_name)
    if not owner:
        return f"Owner '{owner_name}' not found."
    row = _vehicles.vehicle_block(vehicle_type)
    if not row:
        return ("Unknown vehicle '{}'. Known: {}".format(
            vehicle_type, ", ".join(sorted(_vehicles.VEHICLES))))
    day = data.get("meta", {}).get("campaign_day") or 0
    fname = custom_name or row["name"]
    slug = vehicle_type if not custom_name else re.sub(
        r"[^a-z0-9]+", "_", fname.lower()).strip("_")
    if not slug:
        return "Name {!r} produces an empty file key.".format(fname)
    if slug in data.get("characters", {}) or _find_character(data, fname)[0]:
        return "REJECTED: '{}' already on the roster.".format(fname)
    carried = []
    atk = row.get("attack")
    if atk:
        dt = "blast" if "blast" in atk.get("tags", []) else (
            "beam" if "beam" in atk.get("tags", []) else None)
        carried.append(ws.build_weapon(atk["name"], atk["damage"], 1,
                                       prose_tags=atk.get("tags"), range="ranged",
                                       damage_type=dt))
    hull = int(row["hull"])
    cap = int(row["item_slots"])
    sheet = {
        "name": fname, "type": "vehicle", "owner": owner_key,
        "species": row["kind"], "role": "vehicle",
        "hull": {"current": hull, "max": hull},
        "av": {"base": int(row["av"]), "source": "vehicle", "conditional": []},
        "speed": row["speed"], "crew": row["crew"],
        "damage_immune": bool(row.get("damage_immune")),
        "wound_table": "mechanical",
        "slot_capacity_bonus": 0, "slot_capacity_total": cap,
        "inventory": {"carried": carried, "stored": [],
                      "installed_permanent": [], "given_away": []},
        "slots_used": sum(int(i.get("slots", 0)) for i in carried),
        "appearance": row.get("special", ""),
        "operational": True,
        "notes": {"acquired": {"day": day, "owner": owner_key}},
        "special_traits": {},
    }
    if row.get("travel"):
        sheet["travel"] = row["travel"]
    sheet["slots_remaining"] = cap - sheet["slots_used"]
    data.setdefault("characters", {})[slug] = sheet
    _save_single_character(slug, sheet, data)
    atk_line = ("{} ({})".format(atk["name"], atk["damage"]) if atk else "unarmed")
    lines = [
        "**VEHICLE ACQUIRED** ({})".format("homebrew" if row["homebrew"] else "CH pp.73-76"),
        "  **{}** [{}] - Hull {} | AV {} | Speed {} | {} slots | {}".format(
            fname, row["kind"], hull, row["av"], row["speed"], cap, atk_line),
        "  Crew: {}".format(row["crew"]),
        "  {}".format(row.get("special") or ""),
        "  Sheet: vehicles/{}.json (owner: {}).".format(
            slug, owner.get("name", owner_key)),
        "  Hull-Points combat: damage counts 1:10 (a hit <10 does nothing); "
        "repair = 1 day/Hull via character(action=\"repair_vehicle\").",
        _pf.next_block(
            _pf.push_call("character", action="move_vehicle", name=fname,
                          new_location=_pf.raw('"<where it is>"'), operational=True),
            label="register the vehicle's location for travel checks"),
    ]
    return "\n".join(lines)

def _character_repair_vehicle(name, hull_points=None):
    """Repair a vehicle (CH p.73): restore Hull up to max at 1 day of work per
    Hull point. Engine records the day-cost and pushes an advance_day reminder;
    the DM spends the days in-fiction."""
    if not isinstance(hull_points, int) or isinstance(hull_points, bool) or hull_points < 1:
        hull_points = 1
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "repair_vehicle requires 'name' (the vehicle)."
    key, v = _find_character(data, name)
    if not v:
        return f"Character '{name}' not found."
    if v.get("type") != "vehicle":
        return f"{v.get('name', name)} is not a vehicle."
    hull = v.get("hull")
    hull = hull if isinstance(hull, dict) else {}
    cur, mx = int(hull.get("current", 0)), int(hull.get("max", 0))
    if cur >= mx:
        return "{} is already at full Hull ({}/{}).".format(v.get("name", name), cur, mx)
    gained = min(hull_points, mx - cur)
    hull["current"] = cur + gained
    v["hull"] = hull
    if hull["current"] > 0:
        v["operational"] = True
    _save_single_character(key, v, data)
    return ("**{} REPAIRED** - Hull {} -> {}/{} (+{}). Cost: {} day(s) of work with "
            "spare parts (CH p.73). Spend the days via advance_day.".format(
                v.get("name", name).upper(), cur, hull["current"], mx, gained, gained))

def _character_mercenary_expedition_end(name):
    """Close out an expedition (CH p.63): mark pay owed. `name` may be a LEADER
    (-> all that leader's mercs) or a single mercenary. Unpaid mercs leave and
    become sworn foes - clear the debt with character(action='pay_mercenary')."""
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "mercenary_expedition_end requires 'name' (a leader or merc)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    chars = data.get("characters", {})
    if char.get("type") == "mercenary":
        targets = [(key, char)]
    else:
        targets = [(k, c) for k, c in chars.items()
                   if c.get("type") == "mercenary" and c.get("leader") == key]
    if not targets:
        return ("{} has no mercenaries to settle up with.".format(
            char.get("name", name)))
    owed_names = []
    for k, c in targets:
        c["pay_owed"] = True
        _save_single_character(k, c, data)
        owed_names.append(c.get("name", k))
    lines = [
        "**EXPEDITION SETTLED** (CH p.63) - {} now owed 1 Exotica each:".format(
            len(owed_names)),
        "  " + ", ".join(owed_names),
        "  Pay them with character(action=\"pay_mercenary\", name=\"<merc>\"). "
        "Unpaid = they leave AND become a sworn foe.",
    ]
    return "\n".join(lines)

def _character_pay_mercenary(name):
    """Pay a mercenary their 1 Exotica (CH p.63): clears pay_owed. No-op with a
    note if nothing is owed."""
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "pay_mercenary requires 'name' (the mercenary)."
    key, merc = _find_character(data, name)
    if not merc:
        return f"Character '{name}' not found."
    if merc.get("type") != "mercenary":
        return ("{} is not a mercenary - pay_mercenary only settles mercenary "
                "wages.".format(merc.get("name", name)))
    mname = merc.get("name", name)
    if not merc.get("pay_owed"):
        return "{}: nothing owed (no expedition to settle).".format(mname)
    merc["pay_owed"] = False
    _save_single_character(key, merc, data)
    return ("Paid 1 Exotica to {} (expedition settled). Remember to deduct the "
            "water-token wealth in party.json (the live ledger — owner ruling "
            "2026-07-02).".format(mname))

def _mercenary_pay_nag_lines(data):
    """One reminder line per type=='mercenary' sheet with pay_owed True. Wired
    into advance_day; nags every day while owed (like the desertion risk line) -
    the pay_owed flag on the sheet IS the state, no world_tick stamp needed."""
    lines = []
    for k, c in (data or {}).get("characters", {}).items():
        if not isinstance(c, dict) or c.get("type") != "mercenary":
            continue
        if c.get("pay_owed"):
            lines.append(
                "⏳ {} is owed 1 Exotica - unpaid mercenaries leave and "
                "become sworn foes (CH p.63).".format(c.get("name", k)))
    return lines

def _character_merc_morale_check(name):
    """Manual merc-morale lever: `name` may be one mercenary (-> that merc's
    line) or a leader (-> all that leader's living mercs). Returns the
    d20 + ML vs 15 instruction line(s)."""
    data, err = _load_characters()
    if err:
        return err
    if not name or not isinstance(name, str):
        return "merc_morale_check requires 'name' (a mercenary or leader)."
    key, char = _find_character(data, name)
    if not char:
        return f"Character '{name}' not found."
    chars = data.get("characters", {})
    if char.get("type") == "mercenary":
        targets = [(key, char)]
    else:
        targets = [(k, c) for k, c in chars.items()
                   if c.get("type") == "mercenary" and c.get("leader") == key]
    if not targets:
        return "{} has no mercenaries to check.".format(char.get("name", name))
    lines = []
    for k, c in targets:
        hp = c.get("hp")
        cur = hp.get("current", 0) if isinstance(hp, dict) else 0
        if cur <= 0:
            continue
        ml = int(c.get("ml", 0) or 0)
        lines.append(
            "MERC MORALE: {} - d20 + {} vs 15; fail = withdraws/flees "
            "(CH p.63).".format(c.get("name", k), ml))
    if not lines:
        return "{}: no living mercenaries to check.".format(
            char.get("name", name))
    return "\n".join(lines)

def _character_resurrect(character_name, path=None, replace=False):
    """Begin a resurrection path on a corpse (book p.242). Corpse-only; one path
    per corpse unless replace=True. Mycomorph engine-rolls a d4 sprout timer;
    Pseudo-Womb stamps a 7-day decant; Spirit/Necrotech/Ego-Engine carry no timer
    and push the resolve call directly. The save is the player's -- this pushes
    the literal resurrect_resolve call."""
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")
    if char.get("type") == "vehicle":
        return f"{char.get('name', character_name)} is a vehicle - it cannot be resurrected."
    cname = char.get("name", character_name)
    hp = char.get("hp")
    if not (isinstance(hp, dict) and hp.get("current", 0) <= -20):
        return (f"{cname} is not a corpse (resurrection requires hp <= -20). "
                f"Resurrection paths only apply to the dead.")
    # prefix-match the path against the catalog
    raw_path = str(path or "").strip().lower()
    matches = [p for p in _cnd.RESURRECTION_CATALOG if p.startswith(raw_path)] if raw_path else []
    if len(matches) != 1:
        opts = ", ".join(sorted(_cnd.RESURRECTION_CATALOG))
        return f"path must uniquely match one of: {opts}. Got {path!r}."
    path = matches[0]
    spec = _cnd.RESURRECTION_CATALOG[path]
    existing = char.get("resurrection")
    if isinstance(existing, dict) and not existing.get("resolved") and not replace:
        return (f"{cname} already has an in-progress {existing.get('path')} "
                f"resurrection. Pass replace=True to override (two wombs, one soul).")
    day = data.get("meta", {}).get("campaign_day") or 0
    # Spirit: no in-progress record -- the bid is immediate, push it now.
    if path == "spirit":
        lvl = char.get("level", 1)
        bid = _pf.push_call("character", action="resurrect_resolve",
                            name=character_name, path="spirit",
                            save_total=_pf.raw(f"<d20+{lvl}>"),
                            natural_die=_pf.raw("<the d20 face>"))
        return ("\n".join([
            f"**{cname}: SPIRIT bid** -- {spec['reminder']}",
            f"Roll d20 + Level ({lvl}); 16+ returns as a spirit.",
            _pf.next_block(bid, label="report the bid"),
        ]))
    # Timer paths
    due = None
    timer_line = ""
    if spec["timer"] == "d4":
        d4 = _roll_d4()
        due = day + d4
        timer_line = f"Sprout in {d4} day(s) -- INT save at Day {due}."
    elif spec["timer"] == "+7":
        due = day + 7
        timer_line = f"Decant on Day {due} (7-day incubation) -- CON save then."
    rec, verr = _cnd.validate_resurrection_record(
        {"path": path, "began_day": day, "due_day": due}, day=day)
    if verr:
        return f"Could not begin resurrection: {verr}"
    char["resurrection"] = rec
    _save_single_character(key, char, data)
    # Build the resolve push (timer paths fire at due_day; no-timer paths now)
    sv = spec["save"]
    if sv and sv["ability"] != "LEVEL":
        resolve = _pf.push_call("character", action="resurrect_resolve",
                                name=character_name, path=path,
                                save_total=_pf.raw(f"<d20+{sv['ability']} bonus>"),
                                natural_die=_pf.raw("<the d20 face>"))
        push_label = "when the timer lands, report the save"
    else:
        resolve = _pf.push_call("character", action="resurrect_resolve",
                                name=character_name, path=path)
        push_label = "DM confirms the fiction, then resolve"
    lines = [f"**{cname}: {spec['label']} begun** -- needs {spec['needs']}.",
             spec["reminder"]]
    if timer_line:
        lines.append(timer_line)
    lines.append(_pf.next_block(resolve, label=push_label))
    return "\n".join(lines)

def _character_resurrect_resolve(character_name, path=None, save_total=None,
                                 natural_die=None, intact_core=False):
    """Apply a resurrection outcome (book p.242). Standard save: total >= 16
    passes; natural 20 forces pass, natural 1 forces fail. All resolves run the
    revival lever and stamp the resurrection record resolved-with-outcome."""
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")
    cname = char.get("name", character_name)
    raw_path = str(path or "").strip().lower()
    matches = [p for p in _cnd.RESURRECTION_CATALOG if p.startswith(raw_path)] if raw_path else []
    if len(matches) != 1:
        return f"path must uniquely match one of: {', '.join(sorted(_cnd.RESURRECTION_CATALOG))}."
    path = matches[0]
    day = data.get("meta", {}).get("campaign_day") or 0

    # resolved-guard: a resolved death cannot be re-resolved (re-running the
    # surgery on a now-living PC would re-clean, re-mutate, or re-reset them).
    # EXCEPTION: a failed spirit bid blocks only path="spirit" (one bid per
    # death) - the other four paths remain legal on that corpse.
    rec = char.get("resurrection")
    if isinstance(rec, dict) and rec.get("resolved"):
        if rec.get("outcome") == "spirit_failed":
            if path == "spirit":
                return (f"{cname} has already spent their one spirit bid this death "
                        "(the souls scattered). The other paths remain.")
        else:
            return (f"{cname}'s resurrection is already resolved "
                    f"({rec.get('outcome')}, Day {rec.get('resolved_day')}) - "
                    "begin a fresh path on a fresh corpse.")

    def _passed():
        if natural_die == 20:
            return True
        if natural_die == 1:
            return False
        if save_total is None:
            return None  # caller must supply for save paths
        return int(save_total) >= 16

    def _stamp(outcome):
        char["resurrection"] = {"path": path,
                                 "began_day": (rec or {}).get("began_day", day),
                                 "due_day": (rec or {}).get("due_day"),
                                 "resolved": True, "outcome": outcome,
                                 "resolved_day": day}

    lines = []

    def _wounds_survive_line():
        # non-clone revivals reuse the old body: wounds stay on the sheet,
        # the DM rules which remain (Joe-facing rule)
        n = sum(1 for w in (char.get("wounds") or []) if isinstance(w, dict))
        if n:
            lines.append(f"{n} wound(s) survived death - DM rules which "
                         "remain on this body.")

    if path == "pseudo_womb":
        ok = _passed()
        if ok is None:
            return "pseudo_womb resolve needs save_total (d20 + CON bonus)."
        # fail-fast: roll the fallible mutations BEFORE any sheet mutation -
        # a mid-resolve exception must never leave a restored PC with an
        # unresolved record (the tick would nudge a living PC forever)
        m1 = m2 = None
        if not ok:
            m1, m2 = _roll_cacogen_mutation(), _roll_cacogen_mutation()
        _revival_cleanup(char)
        hp_box = char.get("hp")
        hp_warn = False
        if isinstance(hp_box, dict) and "max" in hp_box:
            hp_box["current"] = hp_box["max"]
        else:
            hp_warn = True
        # brand-new body: old wounds (incl. Gitch-crystal AV bonuses) never
        # carry into a clone - pass AND fail
        had_wounds = bool(char.get("wounds"))
        char["wounds"] = []
        char["wounds_slots_used"] = 0
        if ok:
            _stamp("pass")
            lines.append(f"**{cname}: PSEUDO-WOMB decant -- exact copy** (Day {day}).")
        else:
            traits = char.setdefault("special_traits", {})
            traits.setdefault("mutations", []).extend([m1, m2])
            _stamp("fail")
            lines.append(f"**{cname}: PSEUDO-WOMB decant -- flawed clone** (Day {day}).")
            lines.append(f"Two new mutations: {m1['name']} ({m1['effect']}); "
                         f"{m2['name']} ({m2['effect']}).")
        if hp_warn:
            lines.append("WARNING: hp field malformed - set HP manually.")
        if had_wounds:
            lines.append("Brand-new body: the old wounds were cleared (a clone "
                         "carries no scars - Gitch crystals included).")

    elif path == "mycomorph":
        ok = _passed()
        if ok is None:
            return "mycomorph resolve needs save_total (d20 + INT bonus)."
        old_species = char.get("species", "?")
        char["species"] = "Mycomorph"
        _revival_cleanup(char)
        if ok:
            _stamp("pass")
            lines.append(f"**{cname}: reborn as a Mycomorph** (Level/Gifts/abilities kept).")
        else:
            char["level"] = 1
            char["xp"] = {"current": 0, "needed": 1}
            _stamp("fail")
            lines.append(f"**{cname}: reborn as a NEW Level 1 Mycomorph** (carries the "
                         "same items; DM+player rebuild the sheet).")
        lines.append(f"ANCESTRY SWAP: {old_species} traits are now dead -- apply Mycomorph "
                     "special rules (see the Mycomorph ancestry entry).")
        lines.append("HP: set per the rebirth (DM lever).")
        _wounds_survive_line()

    elif path == "spirit":
        ok = _passed()
        if ok is None:
            return "spirit bid needs save_total (d20 + Level)."
        if ok:
            old_max = char.get("hp", {}).get("max", 0)
            char["spirit"] = {"essence": old_max, "max_essence": old_max,
                               "faded_until": None}
            conds = char.setdefault("conditions", [])
            conds.append({"name": "Spirit", "since_day": day,
                          "note": (f"unquiet spirit -- essence {old_max}/{old_max}; "
                                   "spend d6 to touch, d6 + target Level to possess; "
                                   "at 0 fades until next sunrise.")})
            _stamp("spirit")
            lines.append(f"**{cname} returns as a SPIRIT** -- essence {old_max}. The body "
                         "stays a corpse.")
            lines.append(_pf.next_block(
                _pf.push_call("character", action="spirit_spend", name=character_name,
                               kind="touch"),
                _pf.push_call("character", action="spirit_spend", name=character_name,
                               kind="possess", target_level=_pf.raw("<N>")),
                label="spirit economy"))
        else:
            _stamp("spirit_failed")
            lines.append(f"**{cname}: the souls scatter** -- the spirit bid failed (one "
                         "bid per death; it cannot be re-attempted).")
            lines.extend("  " + ln for ln in _cnd.resurrection_push())

    elif path == "necrotech":
        _revival_cleanup(char)
        char["synthetic_type"] = True
        _stamp("pass")
        lines.append(f"**{cname}: NECROTECH revival** -- now ALSO Synthetic-type "
                     "(nanomachine DIS resist applies).")
        lines.append("DOWNSIDE: a severe mind-or-flesh decay (DM rules it) -- record it "
                     "as a permanent sheet note.")
        lines.append("HP: set per the rig (DM lever).")
        _wounds_survive_line()

    elif path == "ego_engine":
        if not intact_core:
            return (f"Ego-Engine needs intact_core=True (a Synthetic corpse with a "
                    "surviving core) plus a new body. DM confirms before resolving.")
        char["level"] = 1
        char["xp"] = {"current": 0, "needed": 1}
        rolled = {}
        for ab in ("STR", "DEX", "CON"):
            v, r_dice = _roll_3d6_lowest()
            abilities = char.setdefault("abilities", {})
            slot = abilities.get(ab)
            if not isinstance(slot, dict):
                # a bare-int ability slot (legacy/NPC shape) - replace it whole
                abilities[ab] = {"current": v, "base": v}
            else:
                slot["current"] = v
                slot["base"] = v
                slot.pop("notes", None)
            rolled[ab] = f"{v} (3d6: {r_dice[0]},{r_dice[1]},{r_dice[2]} take lowest)"
        _revival_cleanup(char)
        _stamp("pass")
        lines.append(f"**{cname}: EGO-ENGINE TRANSPLANT** -- Level 1; INT/PSY/EGO kept; "
                     f"rerolled STR {rolled['STR']} / DEX {rolled['DEX']} / CON {rolled['CON']} "
                     "(3d6 take lowest, p.13).")
        lines.append("HP: set per the new body (DM lever).")
        _wounds_survive_line()

    elif path == "lazarus_tonic":
        # B3 R-B3c: a biological corpse restored to life at the cost of one
        # Level. Same body (wounds survive); no save, no ancestry swap.
        ok, why = _lazarus_eligible(char)
        if not ok:
            return why
        old_level = int(char.get("level", 1))
        char["level"] = max(1, old_level - 1)
        _revival_cleanup(char)
        hp_box = char.get("hp")
        if isinstance(hp_box, dict) and "max" in hp_box:
            hp_box["current"] = hp_box["max"]
        else:
            lines.append("WARNING: hp field malformed - set HP manually.")
        _stamp("pass")
        lines.append(f"**{cname}: LAZARUS TONIC -- restored to life** (Day {day}).")
        lines.append(f"Lazarus cost: Level {old_level} -> {char['level']}.")
        _wounds_survive_line()

    _save_single_character(key, char, data)
    lines.append(_pf.next_block(
        _pf.push_call("affliction", kind="condition", action="status", character=character_name),
        label="verify the revived sheet"))
    return "\n".join(lines)

def _character_spirit_spend(character_name, kind=None, target_level=None):
    """The Spirit economy (book p.242): touch spends d6 essence, possess spends
    d6 + target Level. At 0 the spirit fades until next sunrise (the advance_day
    RESURRECTION TICK restores full essence). Refuses while faded or without a
    spirit block."""
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")
    cname = char.get("name", character_name)
    sp = char.get("spirit")
    if not isinstance(sp, dict):
        return f"{cname} is not a spirit (no spirit block on the sheet)."
    day = data.get("meta", {}).get("campaign_day") or 0
    if isinstance(sp.get("faded_until"), int):
        return (f"{cname}'s spirit is faded -- it re-forms at sunrise "
                f"(Day {sp['faded_until']}). No essence can be spent until then.")
    k = str(kind or "").strip().lower()
    if k not in ("touch", "possess"):
        return "spirit_spend requires kind='touch' or kind='possess'."
    roll = _roll_d6()
    if k == "possess":
        if target_level is None:
            return "possess requires target_level (the target's Level)."
        cost = roll + int(target_level)
        what = f"possess (d6={roll} + target Level {int(target_level)})"
    else:
        cost = roll
        what = f"touch the world (d6={roll})"
    sp["essence"] = sp.get("essence", 0) - cost
    lines = [f"**{cname} spends {cost} essence to {what}.**"]
    if sp["essence"] <= 0:
        sp["essence"] = 0
        sp["faded_until"] = day + 1
        for c in char.get("conditions") or []:
            if isinstance(c, dict) and c.get("name") == "Spirit":
                c["note"] = (f"unquiet spirit -- FADED (returns sunrise Day {day + 1})")
        lines.append(f"Essence hits 0 -- {cname} fades into the aether and returns at "
                     f"sunrise (Day {day + 1}).")
    else:
        m = sp.get("max_essence", sp["essence"])
        for c in char.get("conditions") or []:
            if isinstance(c, dict) and c.get("name") == "Spirit":
                c["note"] = f"unquiet spirit -- essence {sp['essence']}/{m}"
        lines.append(f"Essence remaining: {sp['essence']}/{m}.")
    _save_single_character(key, char, data)
    return "\n".join(lines)

def _apply_bloomboon_to_sheet(sheet, bloomboon, source):
    """Append a Bloomboon record to `sheet['bloomboons']` and auto-apply its
    engine_effects (av_base_bonus, combat trigger, attack, daily_use) onto the
    sheet, deduping each by name. Mutates `sheet` in place; returns
    (fx_lines, lever_lines) for display.

    Does NOT touch level/XP — advancement semantics belong to the caller. Shared
    by `_character_level_up_bloomboon` (a level-up Bloomboon) and
    `_character_create_finalize` (the Neobloom's one starting Bloomboon at
    creation, CH p.049) so both paths resolve a Bloomboon identically."""
    sheet.setdefault('bloomboons', []).append({
        'name': bloomboon['name'],
        'effect': bloomboon['effect'],
        'source': source,
    })

    # --- C2: consume engine_effects (R-C2a - auto-apply what the engine can
    # prove; DM levers render as pre-filled prose). Dedup by name everywhere:
    # a re-granted record never doubles a trigger/attack/daily_use.
    fx = bloomboon.get('engine_effects') or {}
    fx_lines = []
    if fx.get('av_base_bonus'):
        inc = int(fx['av_base_bonus'])
        av = sheet.get('av', 10)
        if isinstance(av, dict):
            old_av = int(av.get('base', 10))
            # Standing AV bonuses lift the no-armour BASELINE so they compose
            # with worn armour (_recompute_av sums armour on top of unarmoured).
            if not isinstance(av.get('unarmoured'), int):
                av['unarmoured'] = old_av
            av['unarmoured'] += inc
            sheet['av'] = av
            new_av = _recompute_av(sheet)
            fx_lines.append(f"AV: {old_av} -> {new_av} "
                            f"(+{inc} standing, {bloomboon['name']})")
        else:
            old_av = int(av)
            sheet['av'] = {"base": old_av + inc, "unarmoured": old_av + inc,
                           "source": bloomboon['name'], "conditional": []}
            fx_lines.append(f"AV base: {old_av} -> {old_av + inc} "
                            f"(+{inc}, {bloomboon['name']})")
    traits = sheet.get('special_traits')
    if not isinstance(traits, dict):
        if traits is not None:
            fx_lines.append("WARNING: special_traits on the sheet is not an "
                            "object - trigger/daily_use stamping skipped; "
                            "fix the sheet.")
            traits = None
        else:
            traits = sheet.setdefault('special_traits', {})
    if fx.get('trigger') and traits is not None:
        trig = copy.deepcopy(fx['trigger'])
        trigs = traits.setdefault('triggers', [])
        if not any(isinstance(t, dict)
                   and str(t.get('name', '')).lower() == str(trig.get('name', '')).lower()
                   for t in trigs):
            trigs.append(trig)
            fx_lines.append(f"Combat trigger stamped: {trig.get('name')} "
                            f"(when {trig.get('when')}) - fires "
                            f"automatically in combat.")
        else:
            fx_lines.append(f"Combat trigger {trig.get('name')} already on "
                            f"the sheet - not duplicated.")
    if fx.get('attack'):
        atk = copy.deepcopy(fx['attack'])
        attacks = sheet.setdefault('attacks', [])
        if isinstance(attacks, list):
            if not any(isinstance(a, dict)
                       and str(a.get('name', '')).lower() == str(atk.get('name', '')).lower()
                       for a in attacks):
                attacks.append(atk)
                fx_lines.append(f"Attack entry stamped: {atk.get('name')} "
                                f"({atk.get('damage')}).")
            else:
                fx_lines.append(f"Attack entry {atk.get('name')} already on "
                                f"the sheet - not duplicated.")
        else:
            fx_lines.append(f"WARNING: attacks on the sheet is not a list - "
                            f"attack entry {atk.get('name')} NOT stamped; "
                            f"fix the sheet.")
    if fx.get('daily_use') and traits is not None:
        du = copy.deepcopy(fx['daily_use'])
        dailies = traits.setdefault('daily_uses', [])
        if not any(isinstance(d, dict)
                   and str(d.get('name', '')).lower() == str(du.get('name', '')).lower()
                   for d in dailies):
            du.setdefault('source', "Bloomboon (CH p.049)")
            dailies.append(du)
            fx_lines.append(f"Daily use stamped: {du.get('name')} - "
                            f"{du.get('note', '')}")
        else:
            fx_lines.append(f"Daily use {du.get('name')} already on the "
                            f"sheet - not duplicated.")
    lever_lines = []
    for lever in fx.get('dm_levers') or []:
        lever_lines.append(f"  - {lever}")
    return fx_lines, lever_lines


def _character_level_up_bloomboon(character_name: str) -> str:
    """Apply Bloomboon option for Neobloom (gain special power instead of standard advancement)."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    if 'neobloom' not in char.get('species', '').lower():
        return f"{char['name']} is not a Neobloom (only Neoblooms can gain Bloomboons)"

    xp = char.get('xp', {'current': 0, 'needed': char.get('level', 1)})
    if xp.get('current', 0) < xp.get('needed', 1):
        return f"Not enough XP. Current: {xp.get('current', 0)}, Needed: {xp.get('needed', 1)}"

    # Load bloomboon table (engine-bundled rules-data)
    bloomboons_content = read_rules_data("NEOBLOOM_BLOOMBOONS.json")
    bloomboons = json.loads(bloomboons_content)

    # Check existing bloomboons (case-insensitive - dedup must hold even if
    # a sheet name's capitalization drifts from the table)
    existing = [str(b.get('name', '')).lower()
                for b in char.get('bloomboons', []) if isinstance(b, dict)]

    # Roll; on a repeat take the NEXT boon down (book, CH p.049: "If a
    # repeat result is rolled, take the next Boon down"), wrapping 20->1
    # (engine default - the book is silent past 20). All 20 owned = refusal.
    roll = dice.d20()
    bloomboon = bloomboons.get(str(roll), {"name": "Unknown", "effect": "Error"})
    walk_note = None
    source = f'd20={roll}'
    if bloomboon["name"].lower() in existing:
        picked = None
        for step in range(1, 20):
            cand = ((roll - 1 + step) % 20) + 1
            cb = bloomboons.get(str(cand))
            if cb and cb["name"].lower() not in existing:
                picked = cand
                bloomboon = cb
                break
        if picked is None:
            return (f"{char['name']} already owns all 20 Bloomboons - no new "
                    f"boon is possible. Nothing applied (XP and level "
                    f"unchanged); level up via standard advancement instead.")
        wrapped = picked < roll
        walk_note = (f"d20={roll} was a repeat - took the next boon down"
                     + (" (wrapped 20->1)" if wrapped else "")
                     + f": #{picked}")
        source = f'd20={roll} -> next-down #{picked}'

    old_level = char.get('level', 1)
    new_level = old_level + 1
    char['level'] = new_level
    char['xp'] = {'current': 0, 'needed': new_level}

    # Add the Bloomboon + auto-apply its engine_effects. Shared with the
    # creation path so a starting Bloomboon and a level-up Bloomboon resolve
    # identically (one source of truth for engine_effects).
    fx_lines, lever_lines = _apply_bloomboon_to_sheet(char, bloomboon, source)

    _save_single_character(key, char, data)

    out = [
        f"**{char['name']} gained a BLOOMBOON!**",
        f"",
        f"Leveled to **Level {new_level}**",
        f"Rolled d20: **{roll}**",
    ]
    if walk_note:
        out.append(walk_note)
    out += [
        f"",
        f"**New Bloomboon:**",
        f"**{bloomboon['name']}**",
        f"{bloomboon['effect']}",
    ]
    if fx_lines:
        out.append("")
        out.append("**Engine effects applied:**")
        out += [f"  {ln}" for ln in fx_lines]
    if lever_lines:
        out.append("")
        out.append("**DM levers** (not auto-applied - DM adjudicates):")
        out += lever_lines
    out += [
        f"",
        f"**No HP roll or ability increases** (traded for Bloomboon)",
        f"XP reset to 0/{new_level}",
        _pf.next_block(_pf.push_call("character", action="get",
                                     name=char['name']),
                       label="verify the stamped sheet"),
    ]
    return "\n".join(out)

def _remove_wound(key, char, data, record) -> str:
    """The single wound-removal seam (spec section 8). Long Rest's heal-one-wound,
    Sprayflesh, Trauma-Response Rig, and DM fiat all route here: drop the record,
    recompute slots as the SUM of what remains, persist. Derived ('until fixed' /
    state) effects vanish by construction - nothing on the sheet to reverse - so
    the healed line names what just lifted and the DM narrates the recovery.
    Never touches rolled-once mutations (recovery table, deferred) or broken-item
    flags (repair, deferred)."""
    wound_list = char.get('wounds', [])
    if record in wound_list:
        wound_list.remove(record)
    freed = record.get('slots', 0) or 0
    char['wounds_slots_used'] = sum(
        r.get('slots', 0) for r in wound_list if isinstance(r, dict))
    _refresh_slot_fields(char)
    _save_single_character(key, char, data)
    cname = char.get('name', key)
    lines = [f"**{cname}**: {record.get('name', 'Wound')} healed - "
             f"{freed} slot(s) freed."]
    lifted = []
    if record.get('until_fixed_penalty'):
        lifted.append("the until-fixed " + ", ".join(
            f"-{v} {k}" for k, v in record['until_fixed_penalty'].items())
            + " penalty")
    if record.get('deprived'):
        lifted.append("Deprived (HP regain works again)")
    if record.get('av_penalty'):
        lifted.append(f"the -{record['av_penalty']} AV penalty")
    if record.get('blind'):
        lifted.append("blindness")
    if record.get('double_damage'):
        lifted.append("double damage taken")
    if record.get('dis_saves'):
        lifted.append("DIS on " + "/".join(record['dis_saves']) + " saves")
    if record.get('deaths_door'):
        lifted.append("DEATH'S DOOR lethality")
    if record.get('unconscious'):
        lifted.append("unconsciousness")
    if record.get('daily_tick'):
        lifted.append("the daily " + ", ".join(
            f"-{v} {k}" for k, v in record['daily_tick'].items()) + " tick")
    if lifted:
        lines.append("  Effect lifted (derived from the wound, no stat reversal "
                     "needed): " + "; ".join(lifted) + " - narrate the recovery.")
    return "\n".join(lines)

def _wound_status_lines(key, char) -> list:
    """Status block for one PC: each active record + a derived-effects summary.
    Empty list when the PC has no wounds (party view skips them)."""
    recs = [r for r in char.get('wounds', []) if isinstance(r, dict)]
    if not recs:
        return []
    cname = char.get('name', key)
    lines = [f"**{cname}** - active wounds:"]
    for r in recs:
        bits = [f"HP {r.get('hp_threshold', '?')}", f"{r.get('slots', 0)} slot(s)"]
        if r.get('pending_con_save'):
            bits.append("CON save PENDING")
        if r.get('unconscious'):
            rounds = r.get('unconscious_rounds')
            bits.append(f"UNCONSCIOUS ({rounds} rounds)" if rounds else "UNCONSCIOUS")
        if r.get('duration'):
            bits.append(f"duration {r['duration']} (DM-adjudicated)")
        lines.append(f"  {r.get('name', '?')} ({', '.join(bits)})")
    eff = _wnd.derived_effects(recs)
    summary = []
    if eff['dis_saves']:
        summary.append("DIS on " + "/".join(eff['dis_saves']) + " saves")
    if eff['deprived']:
        summary.append("Deprived - cannot regain HP")
    if eff['av_penalty']:
        summary.append(f"-{eff['av_penalty']} AV")
    if eff['av_bonus']:
        summary.append(f"+{eff['av_bonus']} AV (Gitch plating)")
    if eff['double_damage']:
        summary.append("takes DOUBLE damage")
    if eff['blind']:
        summary.append("blind (no ranged; melee at DIS)")
    if eff['unconscious']:
        summary.append("unconscious - all attacks automatically hit")
    if eff['deaths_door']:
        summary.append("DEATH'S DOOR - any further damage is LETHAL")
    if eff['pending_con_save']:
        summary.append('awaiting KO CON save - affliction(kind="wound", action="ko_save", ...)')
    for stat, amt in eff['daily_tick'].items():
        summary.append(f"-{amt} {stat} per day")
    summary.extend(eff['notes'])
    if summary:
        lines.append("  Derived: " + "; ".join(summary))
    return lines

def _wound_dispatch(action: str, character: str = None,
                    wound: str = None, result: str = None) -> str:
    """Logic for the wound() tool (separated so it is unit-testable)."""
    action = (action or "").strip().lower()
    _VALID_ACTIONS = {"status", "heal", "ko_save", "wake"}
    if action not in _VALID_ACTIONS:
        return f"Unknown action '{action}'. Use status | heal | ko_save | wake."

    data, err = _load_characters()
    if err or not data:
        return "Could not load characters."

    if action == "status":
        if character:
            key, char = _find_character(data, character)
            if char is None:
                return f"No character named '{character}'."
            items = [(key, char)]
        else:
            items = list(data.get('characters', {}).items())
        lines = []
        for key, char in items:
            lines.extend(_wound_status_lines(key, char))
        return "\n".join(lines) if lines else "No active wounds."

    # heal / ko_save / wake all target one PC
    if not character:
        return f"action='{action}' requires character."
    key, char = _find_character(data, character)
    if char is None:
        return f"No character named '{character}'."
    cname = char.get('name', key)
    recs = [r for r in char.get('wounds', []) if isinstance(r, dict)]

    if action == "heal":
        needle = (wound or "").strip().lower()
        if not needle:
            return "action='heal' requires wound (the wound name, substring ok)."
        if not recs:
            return f"{cname} has no active wounds."
        matches = [r for r in recs if needle in str(r.get('name', '')).lower()]
        if not matches:
            opts = ", ".join(str(r.get('name', '?')) for r in recs)
            return (f"No wound matching '{wound}' on {cname}. "
                    f"Active wounds: {opts}.")
        names = {str(r.get('name', '')).lower() for r in matches}
        if len(names) > 1:
            opts = ", ".join(str(r.get('name', '?')) for r in matches)
            return (f"'{wound}' is ambiguous on {cname} - matches: {opts}. "
                    f"Be more specific.")
        # All matches share one name: stacked duplicates are field-identical
        # (spec: duplicates stack), so there is nothing more specific to say -
        # heal exactly one copy.
        out = _remove_wound(key, char, data, matches[0])
        if len(matches) > 1:
            out += (f"\n  ({len(matches)} stacked copies matched - healed one, "
                    f"{len(matches) - 1} remain{'s' if len(matches) == 2 else ''}.)")
        return out

    if action == "ko_save":
        verdict = (result or "").strip().lower()
        if verdict not in ("pass", "fail"):
            return ("action='ko_save' requires result='pass' or result='fail' "
                    "(the player's rolled CON save).")
        pending = [r for r in recs if r.get('pending_con_save')]
        if not pending:
            return f"{cname} has no pending Knocked-Out CON save."
        # Deliberate simplification: one report covers ALL pending KO records
        # (a stacked second KO before the first save is reported shares the
        # verdict and the d6 duration). One body, one consciousness.
        for r in pending:
            r.pop('pending_con_save', None)
        stack_note = (f" (covers {len(pending)} stacked Knocked Out wounds)"
                      if len(pending) > 1 else "")
        if verdict == "pass":
            _save_single_character(key, char, data)
            return (f"**{cname}** passes the CON save and stays up "
                    f"(the wound itself remains).{stack_note}")
        rounds = random.randint(1, 6)
        for r in pending:
            r['unconscious'] = True
            r['unconscious_rounds'] = rounds
        _save_single_character(key, char, data)
        return (f"**{cname}** fails the CON save - UNCONSCIOUS for {rounds} "
                f"round(s).{stack_note} While unconscious, all attacks "
                f"automatically hit. When the duration ends (DM-adjudicated): "
                f'affliction(kind="wound", action="wake", character="{cname}").')

    # action == "wake"
    cleared = False
    for r in recs:
        if 'unconscious' in r:
            r.pop('unconscious', None)
            # The duration described the shutdown that just ended -- leaving
            # it would render a stale "(4 hours)" on status/push forever.
            r.pop('duration', None)
            cleared = True
        if 'unconscious_rounds' in r:
            r.pop('unconscious_rounds', None)
            cleared = True
    if not cleared:
        return f"{cname} is not unconscious."
    _save_single_character(key, char, data)
    return (f"**{cname}** comes to - unconsciousness cleared "
            f"(the wound itself remains until healed).")

def _character_take_damage(character_name: str, damage: int, damage_type: str) -> str:
    """Apply damage to character. Handles wound generation if HP drops below 0."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    # Check vulnerability (type-based; stays HERE, not in the helper -- toxin
    # ticks carry no damage_type, so vulnerabilities don't apply to ticks).
    actual_damage = damage
    vuln_note = ""
    vulnerabilities = char.get('special_traits', {}).get('vulnerabilities', [])
    for vuln in vulnerabilities:
        if vuln.get('type', '').lower() in damage_type.lower():
            if 'double' in vuln.get('effect', '').lower():
                actual_damage = damage * 2
                vuln_note = f" (DOUBLED from {damage} due to {vuln.get('source', 'vulnerability')})"

    old_hp = char.get('hp', {}).get('current', 0)
    dmg_lines, _lethal_dd = _apply_hp_damage_and_wounds(key, char, data, actual_damage)
    new_hp = char.get('hp', {}).get('current', 0)

    output = [f"**{char['name']}** takes {actual_damage} {damage_type} damage{vuln_note}"]
    output.append(f"HP: {old_hp} -> {new_hp}")
    output.extend(dmg_lines)

    _save_single_character(key, char, data)

    return "\n".join(output)

def _vehicle_take_damage(name, amount, weapon_tags=None):
    """Apply Hull-Points damage to a vehicle (CH p.73): a single source reduces
    Hull by amount//10 (a hit under 10 does nothing). The book's "sources do
    NOT stack within a round" rule is the CALLER's to uphold (make ONE
    aggregated damage call per round); this helper floors each call
    independently. damage_immune vehicles
    (Vimana, R-D5e) take 0 unless the weapon is tagged 'anti_paradox'. Hull 0 =
    wrecked. NOT a PC death - never touches the resurrection/death seam."""
    weapon_tags = weapon_tags or []
    data, err = _load_characters()
    if err:
        return err
    key, v = _find_character(data, name)
    if not v or v.get("type") != "vehicle":
        return f"{name} is not a vehicle."
    if v.get("damage_immune") and "anti_paradox" not in weapon_tags:
        return ("{} is impervious to all damage (only anti-paradox weapons "
                "unravel it, CH p.74).".format(v.get("name", name)))
    hull = v.get("hull")
    hull = hull if isinstance(hull, dict) else {"current": 0, "max": 0}
    loss = int(amount) // 10
    if loss <= 0:
        return ("{} shrugs off {} damage - Hull-Points only drop on a single hit "
                "of 10+ (CH p.73). Hull {}/{}.".format(
                    v.get("name", name), amount, hull.get("current", 0),
                    hull.get("max", 0)))
    hull["current"] = max(0, int(hull.get("current", 0)) - loss)
    v["hull"] = hull
    out = ["{} takes {} Hull damage (from {} raw, 1:10) -> Hull {}/{}.".format(
        v.get("name", name), loss, amount, hull["current"], hull.get("max", 0))]
    if hull["current"] <= 0:
        v["operational"] = False
        out.append("**{} WRECKED** - Hull 0. Repair with spare parts (1 day/Hull) "
                   "via character(action=\"repair_vehicle\").".format(
                       v.get("name", name).upper()))
    _save_single_character(key, v, data)
    return "\n".join(out)

def _vehicle_attack_bonus(sheet):
    """CH p.73: a SYNTHETIC vehicle attacks on its own using current Hull as the
    to-hit bonus. Returns the bonus int, or None for non-synthetic vehicles
    (they need a weapon operator)."""
    if not isinstance(sheet, dict) or sheet.get("type") != "vehicle":
        return None
    if str(sheet.get("species", "")).lower() != "synthetic":
        return None
    hull = sheet.get("hull")
    hull = hull if isinstance(hull, dict) else {}
    return int(hull.get("current", 0))

def _vehicle_speed_save_lines(a_name, b_name):
    """CH p.73: pursuit/race = an opposed Speed save. Returns the push lines (the
    DM rolls d20 + each vehicle's Speed). Wind Barge Speed is rolled d6 each day."""
    data, err = _load_characters()
    if err:
        return [err]
    out = ["CHASE: opposed Speed save (CH p.73) - higher total catches/outruns:"]
    for nm in (a_name, b_name):
        _k, v = _find_character(data, nm)
        if not v or v.get("type") != "vehicle":
            out.append(f"  {nm}: not a vehicle.")
            continue
        sp = v.get("speed")
        sp_txt = ("d6 (roll today)" if sp == "d6/day" else "+{}".format(sp))
        out.append(f"  {v.get('name', nm)}: d20 {sp_txt} Speed.")
    return out

def _character_check_death(character_name: str) -> str:
    """Check if character meets any death condition."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    is_dead, reason = _check_death_conditions(char)

    if is_dead:
        lines = [f"**{char['name']}:** {reason}"]
        lines.extend(_cnd.resurrection_push())
        return "\n".join(lines)

    hp = char.get('hp', {}).get('current', 0)
    slots = _calculate_slots(char)
    abilities = char.get('abilities', {})
    min_ability = min(
        (a.get('current', 0) if isinstance(a, dict) else a)
        for a in abilities.values()
    ) if abilities else 0

    twin_partner = _cnd.condition_effects(
        char.get('conditions') or []).get('twinned_partner')
    twin_note = (f"\n  (Twinned with {twin_partner} - cannot die unless both fall "
                 f"in one window)") if twin_partner else ""
    return (f"**{char['name']}** is ALIVE\n  HP: {hp} (death at -20)\n"
            f"  Wound slots: {slots['wounds']}/{slots['capacity']} (death if full)\n"
            f"  Lowest ability: {min_ability:+d} (death below -10)"
            + twin_note)



_INJECTED = ("VAARNISH_ELIXIRS", "BIOLOGICAL_WOUNDS", "SYNTHETIC_WOUNDS",)


def register_character_tools(srv):
    """Bind the live server module + inject the server-resident data tables."""
    global _server
    _server = srv
    g = globals()
    for _name in _INJECTED:
        g[_name] = getattr(srv, _name)
