"""Substances — decomposition slice 2 (2026-06-17).

Extracted VERBATIM from server.py: the toxin / poison / usage(ammo) / item-consumable
helper web behind the usage, affliction, and supply tools. The tool DISPATCHERS stay
in server.py and import-and-alias these back.

Cross-module functions the movers call (weapon helpers, character persistence, the
death/wound seam) STAY in server.py and are reached here through call-time DELEGATING
SHIMS (_DELEGATES below): each resolves server.<name> at call time, so the tests that
monkeypatch server.<name> keep working untouched. (A frozen by-reference inject would
bypass those patches.) The never-patched data table VAARNISH_POISONS is injected by
reference via register_substances(srv). GAME_STATE is the engine_core by-reference
singleton, imported exactly as server itself does.
"""
import re
import random

import push_format as _pf
import dice_chain as _dc
import item_slots as _isl
import conditions as _cnd
from engine_core import GAME_STATE

# The running server module, supplied by register_substances() at startup. We do
# NOT `import server` here: when the MCP launches via `python server.py`, server runs
# as `__main__`, so `import server` would execute it a SECOND time as a distinct
# module and the alias-back would hit a partially-initialized substances → circular
# ImportError. Registration hands us the real running module (be it `__main__` or
# `server`), which is also exactly the namespace tests monkeypatch.
_server = None


def _make_delegate(_name):
    """Build a call-time delegate to the running server.<_name> (keeps monkeypatches live)."""
    def _delegate(*args, **kwargs):
        return getattr(_server, _name)(*args, **kwargs)
    _delegate.__name__ = _name
    _delegate.__qualname__ = _name
    return _delegate


# Bare-name calls inside the moved helpers resolve to these module globals, each a
# thin delegate to the still-resident server function. Generated uniformly so the
# seam is one obvious mechanism, not 17 hand-written stubs.
_DELEGATES = (
    "_find_weapon_record",
    "_weapon_has_tag",
    "_weapon_is_ranged",
    "_save_game_state",
    "_load_characters",
    "_save_single_character",
    "_find_character",
    "_apply_ability_damage_from_wound",
    "_apply_hp_damage_and_wounds",
    "_check_death_conditions",
    "_death_gate",
    "_death_seam_lines",
    "_condition_save_note",
    "_wound_save_note",
    "_encumbrance_save_note",
    "_calculate_slots",
    "_refresh_slot_fields",
)
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n

# Injected by reference at registration (never-patched, never-reassigned table).
VAARNISH_POISONS = None


_NON_BIOLOGICAL_PC_SPECIES = {"synth"}

def _toxin_susceptible_enemy(stats: dict) -> bool:
    """Enemy is susceptible iff its type string mentions 'Biological'."""
    t = (stats.get("resist_type") or stats.get("type") or "").lower()
    return "biological" in t

def _toxin_susceptible_pc(char: dict) -> bool:
    """PC is Biological unless flagged toxin_immune, a Synth species, or its
    physiology says it is poison-immune. Most ancestries (True-kin, Cacogen,
    Neobloom, Newbeast) are Biological."""
    if char.get("toxin_immune") is True:
        return False
    species = (char.get("species") or "").strip().lower()
    if any(s in species for s in _NON_BIOLOGICAL_PC_SPECIES):
        return False
    physiology = (char.get("physiology") or "").lower()
    if "immune to poison" in physiology:
        return False
    return True

def _toxin_resolve(name: str):
    """Resolve a combatant name to a toxin handle.

    Returns one of:
      {"kind": "enemy", "enemy": <dict>, "key": <str>}
      {"kind": "pc", "char": <dict>, "key": <str>, "data": <dict>}
      None  (not found)
    Enemy lookup mirrors _combat_damage's bare-name resolution.
    """
    combat = GAME_STATE.get("active_combat")
    if combat:
        enemies = combat.get("enemies", {})
        if name in enemies:
            return {"kind": "enemy", "enemy": enemies[name], "key": name}
        nl = name.strip().lower()
        matches = [k for k in enemies
                   if k.lower() == nl or k.lower().startswith(nl + " (")]
        if len(matches) == 1:
            return {"kind": "enemy", "enemy": enemies[matches[0]], "key": matches[0]}
    data, err = _load_characters()
    if not err and data:
        key, char = _find_character(data, name)
        if char:
            return {"kind": "pc", "char": char, "key": key, "data": data}
    return None

def _toxin_get(handle) -> str:
    """Current toxin rung for a handle ('cured' when clean/absent)."""
    obj = handle["enemy"] if handle["kind"] == "enemy" else handle["char"]
    return obj.get("toxin_die") or "cured"

def _toxin_set(handle, die: str) -> None:
    """Set (and persist) the toxin rung. 'cured' clears the field."""
    die = _dc._norm(die)
    if handle["kind"] == "enemy":
        if die == "cured":
            handle["enemy"].pop("toxin_die", None)
        else:
            handle["enemy"]["toxin_die"] = die
        _save_game_state()
    else:
        if die == "cured":
            handle["char"].pop("toxin_die", None)
        else:
            handle["char"]["toxin_die"] = die
        _save_single_character(handle["key"], handle["char"], handle.get("data"))

def _toxin_save_dc(tox_die: str) -> int:
    """Book-literal, uncapped: 10 + die faces."""
    return 10 + _dc.size(tox_die)

def _toxin_enemy_save(enemy: dict, tox_die: str, rng=random.randint):
    """Auto-roll a creature CON save: d20 + Level (cap +10) vs 10 + die faces.
    Returns (passed: bool, detail: str)."""
    bonus = min(int(enemy.get("lvl", 1) or 1), 10)
    d20 = rng(1, 20)
    total = d20 + bonus
    dc = _toxin_save_dc(tox_die)
    return total >= dc, f"d20={d20}+{bonus}={total} vs DC {dc}"

def _toxin_incur(handle, tox_die: str, save_passed: bool) -> str:
    """Apply a TOX exposure outcome. On a failed save, escalate (bigger-wins);
    on success, no change. Returns a short human-readable note."""
    if save_passed:
        return "save succeeded — no toxin gained"
    before = _toxin_get(handle)
    after = _dc.escalate(before, tox_die)
    _toxin_set(handle, after)
    if after == before:
        return f"save failed — toxin holds at {before} (new {tox_die} not larger)"
    return f"save failed — Toxin Die now **{after}**"

def _toxin_tick(handle, rng=random.randint):
    """Roll the current toxin die, subtract from HP, deplete one rung on a 1-2.
    Returns a per-tick message, or None if there is nothing to tick.
    A single roll does double duty: it is both the damage and the deplete check."""
    die = _toxin_get(handle)
    if die == "cured":
        return None
    dmg = _dc.roll(die, rng=rng)
    name = handle["key"]
    out = [f"{name}: Toxin Die ({die}) ticks for {dmg}"]

    if handle["kind"] == "enemy":
        e = handle["enemy"]
        e["hp"] = max(0, e["hp"] - dmg)
        out.append(f"{e['hp']}/{e['max_hp']} HP")
        if e["hp"] <= 0 and not e.get("defeated"):
            e["defeated"] = True
            out.append(f"{name} defeated by toxin!")
    else:
        c = handle["char"]
        # Unified HP<=0 trigger (_apply_hp_damage_and_wounds): same in-memory
        # dict as _toxin_set's later save, so wound records persist without a
        # lost update. The helper mutates HP/wounds and NEVER saves.
        dmg_lines, _lethal_dd = _apply_hp_damage_and_wounds(
            handle["key"], c, handle.get("data"), dmg)
        out.append(f"{c['hp']['current']}/{c['hp']['max']} HP")
        out.extend(dmg_lines)

    new_die = _dc.step_down(die) if dmg in (1, 2) else die
    _toxin_set(handle, new_die)
    if new_die != die:
        out.append(f"depletes -> {new_die}")
    return " | ".join(s.strip() for s in out if s.strip())

def _toxin_cure(handle, full: bool = False) -> str:
    """DM lever: step the toxin die down one rung, or clear it entirely (full)."""
    die = _toxin_get(handle)
    if die == "cured":
        return f"{handle['key']} has no Toxin Die."
    new_die = "cured" if full else _dc.step_down(die)
    _toxin_set(handle, new_die)
    return f"{handle['key']}: Toxin Die {die} -> {new_die}"

def _toxin_dispatch(action: str, target: str = None, tox_die: str = None,
                    save_total: int = None, full: bool = False,
                    poison=None, weapon: str = None) -> str:
    """Logic for the toxin() tool (separated so it is unit-testable)."""
    action = (action or "").strip().lower()

    if action == "status":
        if target:
            h = _toxin_resolve(target)
            if not h:
                return f"No combatant named '{target}'."
            die = _toxin_get(h)
            return f"{h['key']}: {'clean (no Toxin Die)' if die == 'cured' else 'Toxin Die ' + die}"
        lines = ["**Toxin Die status**"]
        data, err = _load_characters()
        if not err and data:
            for key, char in data.get("characters", {}).items():
                die = char.get("toxin_die")
                if die:
                    lines.append(f"  {char.get('name', key)}: {die}")
        combat = GAME_STATE.get("active_combat")
        if combat:
            for key, e in combat.get("enemies", {}).items():
                if e.get("toxin_die"):
                    lines.append(f"  {key}: {e['toxin_die']}")
        return "\n".join(lines) if len(lines) > 1 else "No active Toxin Dice."

    if not target:
        return f"Action '{action}' requires target."
    h = _toxin_resolve(target)
    if not h:
        return f"No combatant named '{target}'."

    susceptible = (_toxin_susceptible_enemy(h["enemy"]) if h["kind"] == "enemy"
                   else _toxin_susceptible_pc(h["char"]))

    if action == "check":
        if not tox_die:
            return "Action 'check' requires tox_die (e.g. 'd8')."
        if not susceptible:
            return f"{h['key']} is **immune** to TOX (non-Biological)."
        dc = _toxin_save_dc(tox_die)
        if h["kind"] == "pc":
            _c = h.get("char")
            _enc = (_encumbrance_save_note(_c, "CON") + _wound_save_note(_c, "CON")
                    + _condition_save_note(_c, "CON")) if _c else ""
            _call = _pf.push_call(
                "affliction", kind="toxin", action="resolve", target=h["key"],
                tox_die=tox_die, save_total=_pf.raw("<your roll>"))
            return (f"{h['key']} hit by {tox_die} TOX — **roll a CON save vs DC {dc}** "
                    f"(d20 + CON){_enc}, then call {_call}.")
        passed, detail = _toxin_enemy_save(h["enemy"], tox_die)
        note = _toxin_incur(h, tox_die, save_passed=passed)
        return f"{h['key']} CON save {detail} — {note}"

    if action == "resolve":
        if not tox_die or save_total is None:
            return "Action 'resolve' requires tox_die and save_total."
        if not susceptible:
            return f"{h['key']} is immune to TOX (non-Biological)."
        dc = _toxin_save_dc(tox_die)
        passed = save_total >= dc
        note = _toxin_incur(h, tox_die, save_passed=passed)
        verdict = "PASS" if passed else "FAIL"
        return f"{h['key']} CON save {save_total} vs DC {dc} — {verdict}. {note}"

    if action == "tick":
        msg = _toxin_tick(h)
        return msg or f"{h['key']} has no Toxin Die."

    if action == "cure":
        return _toxin_cure(h, full=full)

    # --- B2 Vaarnish poisons (R-B2a save fork) ---
    if action == "poison_apply":
        row, perr = _poison_record(poison)
        if perr:
            return perr
        if _poison_immune(h):     # physiology/cybernetic immunity, ALL rows
            return f"{h['key']} is **immune to poisons** - no effect."
        fx = row.get("engine_effects") or {}
        label = (f"{row.get('colour', 'Unknown')} {row.get('form', '')} poison "
                 f"({row.get('delivery', '?')}) - {row.get('effect_text', '')}")
        if fx.get("save") == "none":
            lines = _poison_resolve_effect(h, row, save_passed=False,
                                           day=_poison_current_day(h))
            out = f"**POISON** {label}\n" + "\n".join(lines)
        elif h["kind"] == "pc":
            _call = _pf.push_call(
                "affliction", kind="toxin", action="poison_resolve", target=h["key"],
                poison=_pf.raw(repr(poison)), save_total=_pf.raw("<roll>"))
            return (f"**POISON** {label}\n{h['key']} - **roll a CON save vs "
                    f"TN {POISON_SAVE_TN}** (d20 + CON), then call {_call}.")
        else:
            passed, detail = _poison_enemy_save(h["enemy"])
            lines = _poison_resolve_effect(h, row, save_passed=passed,
                                           day=_poison_current_day(h))
            out = (f"**POISON** {label}\n{h['key']} CON save {detail} - "
                   f"{'lesser' if passed else 'greater'} effect.\n"
                   + "\n".join(lines))
        if h["kind"] == "pc":
            _save_single_character(h["key"], h["char"], h.get("data"))
        return out

    if action == "poison_coat":
        # target here is the PC; weapon + poison required (R-B2b).
        row, perr = _poison_record(poison)
        if perr:
            return perr
        if h["kind"] != "pc":
            return "poison_coat targets a PC's weapon."
        if not weapon:
            return "Action 'poison_coat' requires weapon."
        wrec = _find_weapon_record(h["char"], weapon)
        if wrec is None:
            return f"{h['key']} has no weapon '{weapon}' (or the name is ambiguous)."
        wname = wrec.get("name", weapon)
        replaced = ""
        old_coat = wrec.get("poison_coating")
        if isinstance(old_coat, dict):
            replaced = (f" NOTE: it was already coated with "
                        f"{old_coat.get('label', 'a poison')} - that dose is "
                        f"REPLACED (lost).")
        wrec["poison_coating"] = {
            "label": f"{row.get('colour', 'Unknown')} poison ({row.get('effect_text', '')})",
            "poison": poison if not isinstance(poison, dict) else row,
        }
        # Inline records minted as items (sap doses): consume ONE carried
        # item matching the record's name - the dose moves onto the blade.
        consumed = ""
        if isinstance(poison, dict) and poison.get("name"):
            carried = (h["char"].get("inventory") or {}).get("carried", [])
            for i, item in enumerate(carried):
                if (isinstance(item, dict) and str(item.get("name", "")).lower()
                        == str(poison["name"]).lower()):
                    carried.pop(i)
                    consumed = f" {poison['name']} consumed from inventory."
                    break
        _save_single_character(h["key"], h["char"], h.get("data"))
        return (f"{wname} coated with {wrec['poison_coating']['label']} - "
                f"fires on the next successful hit (one dose, R-B2b)."
                f"{consumed}{replaced}")

    if action == "poison_resolve":
        row, perr = _poison_record(poison)
        if perr:
            return perr
        if _poison_immune(h):     # same gate as poison_apply (all rows)
            return f"{h['key']} is **immune to poisons** - no effect."
        if (row.get("engine_effects") or {}).get("save") == "none":
            # A save:none row (pure TOX) has no application save to resolve -
            # a stray resolve call must not report it "resisted".
            lines = _poison_resolve_effect(h, row, save_passed=False,
                                           day=_poison_current_day(h))
            return ("This poison has no application save (the Toxin Die "
                    "mechanic is the save) - applying directly:\n"
                    + "\n".join(lines))
        if save_total is None:
            return "Action 'poison_resolve' requires save_total."
        passed = save_total >= POISON_SAVE_TN
        lines = _poison_resolve_effect(h, row, save_passed=passed,
                                       day=_poison_current_day(h))
        if h["kind"] == "pc":
            _save_single_character(h["key"], h["char"], h.get("data"))
        verdict = "PASS - lesser effect" if passed else "FAIL - greater effect"
        return (f"{h['key']} CON save {save_total} vs TN {POISON_SAVE_TN} - "
                f"{verdict}.\n" + "\n".join(lines))

    return (f"Unknown action '{action}'. Use status|check|resolve|tick|cure"
            f"|poison_apply|poison_resolve|poison_coat.")

def _toxin_die_from_dice(damage_dice) -> str:
    """Extract the leading dN from a damage expression ('d8', 'd8+2', '2d6')."""
    m = re.search(r'd(\d+)', str(damage_dice or ""))
    return f"d{m.group(1)}" if m else "d6"

def _toxin_attack_reroute(attacker, target, tox_die, attacker_kind) -> str:
    """A TOX hit landed: replace flat damage with the Toxin Die mechanic.

    Enemy target -> auto-roll the creature save and resolve.
    PC target    -> surface the DC and ask the player to roll (resolve later).
    Non-Biological target -> immune, no effect.
    """
    h = _toxin_resolve(target)
    if not h:
        return f"TOX hit but no combatant '{target}' found."
    susceptible = (_toxin_susceptible_enemy(h["enemy"]) if h["kind"] == "enemy"
                   else _toxin_susceptible_pc(h["char"]))
    if not susceptible:
        return f"**{target}** is immune to TOX (non-Biological) — no effect."
    dc = _toxin_save_dc(tox_die)
    if h["kind"] == "enemy":
        passed, detail = _toxin_enemy_save(h["enemy"], tox_die)
        note = _toxin_incur(h, tox_die, save_passed=passed)
        return f"**{target}** hit by {tox_die} TOX — CON save {detail}: {note}"
    _enc = ""
    _d, _e = _load_characters()
    if _d and not _e:
        _k, _c = _find_character(_d, target)
        if _c:
            _enc = (_encumbrance_save_note(_c, "CON") + _wound_save_note(_c, "CON")
                    + _condition_save_note(_c, "CON"))
    _call = _pf.push_call(
        "affliction", kind="toxin", action="resolve", target=target,
        tox_die=tox_die, save_total=_pf.raw("<roll>"))
    return (f"**{target}** hit by {tox_die} TOX — **roll CON save vs DC {dc}** (d20 + CON){_enc}, "
            f"then {_call}.")

POISON_SAVE_TN = 15  # engine default (R-B2a); the book's only flat-save precedent

def _poison_record(poison):
    """Resolve a poison argument: int/str row number -> table row; dict -> inline."""
    if isinstance(poison, dict):
        rec = dict(poison)
        rec.setdefault("effect_text", rec.get("name", "custom poison"))
        return rec, None
    try:
        roll = int(poison)
    except (TypeError, ValueError):
        return None, f"poison must be a row number 1-20 or an inline record, got {poison!r}."
    row = VAARNISH_POISONS.get(roll)
    if not row:
        return None, f"No poison row {roll} (1-20)."
    return row, None

def _poison_immune(handle) -> bool:
    """Poison immunity, checked BEFORE the save for ALL rows (not just TOX).
    PC: the B1 physiology check (Synth species, toxin_immune flag, 'immune to
    poison' physiology) plus a cybernetics scan (Cyberliver's 'immunity to all
    poisons'). Enemy: TOX-equivalence (non-Biological)."""
    if handle["kind"] == "enemy":
        return not _toxin_susceptible_enemy(handle["enemy"])
    char = handle["char"]
    if not _toxin_susceptible_pc(char):
        return True
    augs = char.get("augmentations")
    if isinstance(augs, dict):
        for aug in augs.values():
            if not isinstance(aug, dict):
                continue
            blob = " ".join(str(aug.get(k) or "")
                            for k in ("name", "effect")).lower()
            if "immunity to all poisons" in blob or "immune to all poisons" in blob:
                return True
    return False

def _poison_enemy_save(enemy: dict, rng=random.randint):
    """Auto-roll a creature CON save vs the flat poison TN (R-B2a).
    Mirrors _toxin_enemy_save: d20 + Level (cap +10). Returns (passed, detail)."""
    bonus = min(int(enemy.get("lvl", 1) or 1), 10)
    d20 = rng(1, 20)
    total = d20 + bonus
    return (total >= POISON_SAVE_TN,
            f"d20={d20}+{bonus}={total} vs TN {POISON_SAVE_TN}")

def _poison_current_day(handle=None) -> int:
    """Current campaign day - same accessor the condition apply site uses
    (characters meta.campaign_day). Falls back to a fresh load for enemy
    handles (which carry no data)."""
    data = (handle or {}).get("data")
    if not isinstance(data, dict):
        data, err = _load_characters()
        if err or not data:
            return 0
    return data.get("meta", {}).get("campaign_day") or 0

def _poison_death(handle):
    """Row 20 greater: death through the real gated seam (Twinning,
    resurrection push) - mirrors the E2 condition-tick allowed-death branch:
    snap HP to -20 first (the gate clamps to -19 on refusal), then push the
    p.229 resurrection menu when the death stands."""
    char, data, key = handle.get("char"), handle.get("data"), handle["key"]
    name = char.get("name", key) if isinstance(char, dict) else key
    if isinstance(char.get("hp"), dict):
        char["hp"]["current"] = -20
    allowed, gate_lines = _death_gate(key, char, data, cause="poison")
    out = list(gate_lines)
    if allowed:
        out.append(f"!!! {name} DIES of poison - HP -20 !!!")
        out.extend(_death_seam_lines(char, data, key))
    return out

def _poison_resolve_effect(handle, row, save_passed, rng=random.randint, day=None):
    """Apply the lesser (save passed) or greater (failed) effect. Returns output lines.

    PC targets get real bookkeeping; enemy targets get prose only (enemies
    carry no ability/condition records) except TOX, which uses the real
    enemy toxin path."""
    fx = (row.get("engine_effects") or {})
    eff = fx.get("lesser") if save_passed else fx.get("greater")
    out = []
    if eff is None:
        out.append(f"{handle['key']} resists the poison - no effect.")
        return out

    kind = eff.get("kind")
    is_pc = handle["kind"] == "pc"
    char = handle.get("char")

    if kind == "tox":
        out.append(_toxin_attack_reroute(None, handle["key"], eff["tox_die"],
                                         attacker_kind="poison"))
        return out

    if not is_pc:
        out.append(f"{handle['key']} - {row.get('effect_text', '')}: "
                   f"{'lesser' if save_passed else 'greater'} effect (DM adjudicates "
                   f"enemy bookkeeping; enemies carry no ability/condition records).")
        return out

    if kind == "ability_loss":
        abilities = eff["abilities"]
        if eff.get("single_roll"):
            sides = int(next(iter(abilities.values())).lstrip("d"))
            rolled = rng(1, sides)
            abilities = {stat: rolled for stat in abilities}
            out.append(f"One roll, both stats (book-literal): d{sides}={rolled}.")
        out.extend(_apply_ability_damage_from_wound(char, abilities))
        # An ability driven below -10 is a real death (the book's third death
        # condition) - route it through the same gated seam row 20 uses, never
        # leave a prose-only "DEATH" flag (Twinning + p.229 push apply).
        dead, _reason = _check_death_conditions(char)
        if dead:
            out.extend(_poison_death(handle))
        return out

    if kind == "condition":
        req = {"name": eff["name"]}
        note = eff.get("note")
        dur_die = eff.get("duration_days_die")
        if dur_die and day is not None:
            days = rng(1, int(dur_die.lstrip("d")))
            req["until_day"] = day + days
            out.append(f"{eff['name']} for {days} days (until day {req['until_day']}).")
        elif dur_die is None:
            out.append(f"{eff['name']} - no book duration; DM adjudicates the cure.")
        if note:
            req["note"] = note
            out.append(f"  ({note})")
        rec, rerr = _cnd.normalize_record(req, day=day or 0)
        if rerr:
            out.append(f"WARNING: condition not recorded ({rerr}).")
        else:
            char.setdefault("conditions", []).append(rec)
        return out

    if kind == "max_hp_loss":
        sides = int(eff["die"].lstrip("d"))
        lost = rng(1, sides)
        hp = char.setdefault("hp", {})
        hp["max"] = max(0, int(hp.get("max", 0)) - lost)
        hp["current"] = min(int(hp.get("current", 0)), hp["max"])
        out.append(f"{handle['key']} loses {lost} Max HP "
                   f"({hp['current']}/{hp['max']}).")
        if hp["max"] <= 0:
            out.extend(_poison_death(handle))
        return out

    if kind == "death":
        out.extend(_poison_death(handle))
        return out

    out.append(f"Unknown poison effect kind '{kind}' - DM adjudicates: "
               f"{row.get('effect_text', '')}")
    return out

def _usage_to_chain(ammo) -> str:
    """'Ud8' -> 'd8'; 'Expended'/'Ud0'/''/None -> 'cured'."""
    s = str(ammo or "").strip().lower()
    if s in ("", "expended", "ud0", "u0"):
        return "cured"
    if s.startswith("u"):
        s = s[1:]            # 'ud8' -> 'd8'
    return _dc._norm(s)

def _usage_to_ammo(die) -> str:
    """'d8' -> 'Ud8'; 'cured'/None -> 'Expended'."""
    die = _dc._norm(die)
    return "Expended" if die == "cured" else "U" + die

def _usage_applies(weapon: dict) -> bool:
    """A usage-die weapon iff ranged AND it has a truthy `ammo` field. NOT keyed
    off type/tier (those drift). 'Expended' counts (still a usage weapon, empty)."""
    return _weapon_is_ranged(weapon) and bool(weapon.get("ammo"))

def _usage_is_parasitic(weapon: dict) -> bool:
    return _weapon_has_tag(weapon, "parasitic")

def _usage_is_fungal(weapon: dict) -> bool:
    return _weapon_has_tag(weapon, "fungal")

def _usage_is_expended(weapon: dict) -> bool:
    return _usage_applies(weapon) and _usage_to_chain(weapon.get("ammo")) == "cured"

def _usage_ammo_max(weapon: dict) -> str:
    """The weapon's natural die (cap for feed/reload). Falls back to current
    `ammo` when `ammo_max` is absent (lazy default); 'Expended' if neither."""
    return weapon.get("ammo_max") or weapon.get("ammo") or "Expended"

def _usage_resolve(character: str, weapon_name: str):
    """Resolve (character, weapon_name) to a usage handle, or a str error, or
    None if the load fails or the character is not found. Matches the weapon by
    case-insensitive substring against carried weapons. Lazily stamps ammo_max
    if missing."""
    data, err = _load_characters()
    if err or not data:
        return None
    key, char = _find_character(data, character)
    if char is None:
        return None
    carried = char.get("inventory", {}).get("carried", [])
    weapons = [w for w in carried if _usage_applies(w)]
    needle = (weapon_name or "").lower()
    matches = [w for w in weapons if needle in str(w.get("name", "")).lower()]
    if len(matches) == 0:
        names = ", ".join(w.get("name", "?") for w in weapons) or "(none)"
        return f"usage weapon '{weapon_name}' not found on {character}; options: {names}"
    if len(matches) > 1:
        names = ", ".join(w.get("name", "?") for w in matches)
        return f"ambiguous — '{weapon_name}' matches: {names}"
    w = matches[0]
    if not w.get("ammo_max"):
        w["ammo_max"] = w.get("ammo")
    return {"key": key, "char": char, "data": data, "weapon": w}

def _usage_get(handle) -> str:
    """Current ammo notation ('Ud8'/'Expended')."""
    return handle["weapon"].get("ammo") or "Expended"

def _usage_set(handle, new_ammo: str) -> None:
    """Write the weapon's ammo to the authoritative carried[] entry, sync the
    attacks[] mirror by name, and persist the sheet."""
    w = handle["weapon"]
    w["ammo"] = new_ammo
    if not w.get("ammo_max") and new_ammo != "Expended":
        w["ammo_max"] = new_ammo
    name = w.get("name")
    for a in handle["char"].get("attacks", []):
        if a.get("name") == name and "ammo" in a:
            a["ammo"] = new_ammo
    _save_single_character(handle["key"], handle["char"], handle.get("data"))

def _usage_carried_ammo(char: dict) -> list:
    """Names of carried items tagged type == 'ammo' (for reconcile reminders)."""
    return [it.get("name", "?")
            for it in char.get("inventory", {}).get("carried", [])
            if str(it.get("type", "")).lower() == "ammo"]

def _usage_deplete_roll(handle, rng=None) -> str:
    """Roll the weapon's usage die once; on a 1-2 step it down one rung and
    persist. Parasitic weapons never roll. The book's 'roll once after combat'
    (and the manual single-shot roll)."""
    if rng is None:
        rng = random.randint
    w = handle["weapon"]
    name = w.get("name", "weapon")
    if w.get("broken"):
        # A broken weapon can never be fired (attack guard), so depleting its
        # die is always a slip - block rather than silently waste the die.
        return f"BLOCKED - {_broken_item_msg(name)}"
    if _usage_is_parasitic(w):
        return f"{name}: Parasitic — never needs reload (not rolled)."
    die = _usage_to_chain(w.get("ammo"))
    if die == "cured":
        return f"{name}: already Expended."
    r = _dc.roll(die, rng=rng)
    out = [f"{name}: usage die ({_usage_to_ammo(die)}) rolled {r}"]
    if r in (1, 2):
        new = _usage_to_ammo(_dc.step_down(die))
        _usage_set(handle, new)
        out.append(f"depletes -> {new}")
        if new == "Expended":
            _char_name = handle["char"].get("name") or handle["key"]
            _calls = [_pf.push_call("usage", action="reload",
                                    character=_char_name, weapon=name)]
            if _usage_is_fungal(w):
                _calls.append(_pf.push_call("usage", action="feed",
                                            character=_char_name, weapon=name))
            out.append(_pf.next_block(
                *_calls,
                label="reload or feed" if _usage_is_fungal(w) else "reload",
            ))
    return " | ".join(out)

def _usage_feed(handle) -> str:
    """Fungal-only: step the die UP one rung via the chain, capped at ammo_max."""
    w = handle["weapon"]
    name = w.get("name", "weapon")
    if not _usage_is_fungal(w):
        _char_name = handle["char"].get("name") or handle["key"]
        _reload = _pf.push_call("usage", action="reload",
                                character=_char_name, weapon=name)
        return f"{name} is not Fungal — use {_reload} instead."
    cur = _usage_to_chain(w.get("ammo"))
    cap = _usage_to_chain(_usage_ammo_max(w))
    cur_idx = _dc.CHAIN.index(cur)
    cap_idx = _dc.CHAIN.index(cap)
    if cur_idx >= cap_idx:
        return f"{name}: Fungal feed — already at max ({_usage_to_ammo(cur)})."
    new = _dc.CHAIN[cur_idx + 1]
    _usage_set(handle, _usage_to_ammo(new))
    _char_name = handle["char"].get("name") or handle["key"]
    _push = _pf.next_block(
        _pf.push_call("usage", action="status", character=_char_name),
        label="check load",
    )
    return f"{name}: Fungal feed {_usage_to_ammo(cur)} -> {_usage_to_ammo(new)} | {_push}"

def _usage_reload(handle, to=None) -> str:
    """DM lever: set the die to `to` (or ammo_max), capped at ammo_max. Surfaces
    the ammo_note and carried ammo items; refuses a 'cannot be reloaded' weapon
    unless `to` is given explicitly (DM override)."""
    w = handle["weapon"]
    name = w.get("name", "weapon")
    note = w.get("ammo_note", "")
    carried = _usage_carried_ammo(handle["char"])
    carried_str = ", ".join(carried) if carried else "none"
    cap = _usage_ammo_max(w)
    if note and "cannot" in note.lower() and to is None:
        return (f"{name}: ammo_note says '{note}'. Not auto-reloaded — pass "
                f"to='Udx' to override. Carried ammo: {carried_str}.")
    if to is not None and _usage_to_chain(to) == "cured":
        return f"{name}: '{to}' is not a valid ammo die (e.g. 'Ud6'). Not reloaded."
    target = to or cap
    if _dc.CHAIN.index(_usage_to_chain(target)) > _dc.CHAIN.index(_usage_to_chain(cap)):
        target = cap
    new = _usage_to_ammo(_usage_to_chain(target))
    _usage_set(handle, new)
    msg = f"{name}: reloaded -> {new}"
    if note:
        msg += f" ({note})"
    return msg + f". Carried ammo to reconcile: {carried_str}."

def _broken_item_msg(name: str) -> str:
    """The one broken-item rule line (Damaged Item wound, spec section 6).
    Shared by every guard so the wording can never drift between sites."""
    return (f"{name} is BROKEN (Damaged Item wound) - unusable until fixed. "
            f"Repair is a DM ruling (find a workshop/fixer).")

def _item_depletes(item: dict) -> bool:
    """Any carried item carrying a usage die (usage_die/ammo) or integer uses."""
    # first consumer: the enriched 'status' action (Task 4)
    return _isl.item_is_depletable(item)

def _item_resolve(character: str, item_name: str):
    """Resolve (character, item_name) to a handle over ANY carried item, or a str
    error, or None if the PC can't be loaded/found. Mirrors _usage_resolve but not
    limited to ranged weapons. Non-depletable items resolve correctly so that
    _item_use can return the no-op message for unlimited items."""
    data, err = _load_characters()
    if err or not data:
        return None
    key, char = _find_character(data, character)
    if char is None:
        return None
    carried = char.get("inventory", {}).get("carried", [])
    needle = (item_name or "").lower()
    matches = [it for it in carried if needle in str(it.get("name", "")).lower()]
    if len(matches) == 0:
        names = ", ".join(it.get("name", "?") for it in carried) or "(none)"
        return f"item '{item_name}' not found on {character}; carried: {names}"
    if len(matches) > 1:
        names = ", ".join(it.get("name", "?") for it in matches)
        return f"ambiguous — '{item_name}' matches: {names}"
    return {"key": key, "char": char, "data": data, "item": matches[0]}

def _item_use(handle, rng=None) -> str:
    """Resolve one per-use depletion. Usage die: roll, step down on 1-2 (stays in
    inventory). Discrete: uses -= 1, remove + free slot at 0. Unlimited: no-op."""
    if rng is None:
        rng = random.randint
    char = handle["char"]
    it = handle["item"]
    name = it.get("name", "item")

    # --- Broken-item guard (Damaged Item wound, spec section 6) ---
    # Brokenness lives on the ITEM, independent of the wound (persists past
    # heal). No roll, no decrement, no removal. Repair (clearing the flag) is
    # the deferred DM-fiat seam.
    if it.get("broken"):
        return f"BLOCKED - {_broken_item_msg(name)}"

    # Wound-removal items (Sprayflesh "Remove 1 Wound", Trauma-Response Rig):
    # the use resolves the depletion; the HEAL it buys is a wound() call --
    # push it so the DM closes the loop (DoD push rule).
    _txt = f'{it.get("description", "")} {it.get("effect", "")}'.lower()
    heal_ptr = ""
    if "wound" in _txt and ("remove" in _txt or "negate" in _txt):
        heal_ptr = (' | then apply the heal: affliction(kind="wound", action="heal", '
                    'character="<target PC>", wound="<wound name>")')

    die = _isl.item_usage_die(it)
    if die:
        rung = _usage_to_chain(die)
        if rung == "cured":
            return f"{name}: already Expended."
        r = _dc.roll(rung, rng=rng)
        out = [f"{name}: usage die ({_usage_to_ammo(rung)}) rolled {r}"]
        if r in (1, 2):
            new = _usage_to_ammo(_dc.step_down(rung))
            field = "usage_die" if it.get("usage_die") else "ammo"
            it[field] = new
            maxf = "usage_max" if field == "usage_die" else "ammo_max"
            if not it.get(maxf):
                it[maxf] = die
            out.append(f"depletes -> {new}")
            if new == "Expended":
                _char_name = char.get("name") or handle["key"]
                out.append(_pf.next_block(
                    _pf.push_call("usage", action="reload",
                                  character=_char_name, item=name),
                    label="reload"))
            _save_single_character(handle["key"], char, handle.get("data"))
        return " | ".join(out) + heal_ptr

    u = it.get("uses")
    if isinstance(u, int) and not isinstance(u, bool):
        if not it.get("uses_max"):
            it["uses_max"] = u
        it["uses"] = u - 1
        if it["uses"] <= 0:
            char["inventory"]["carried"].remove(it)
            slots = _refresh_slot_fields(char)
            _save_single_character(handle["key"], char, handle.get("data"))
            freed = it.get("slots", 1)
            tail = " — now ENCUMBERED" if slots["encumbered"] else ""
            return f"{name}: consumed (last use) — removed, {freed} slot(s) freed{tail}.{heal_ptr}"
        _save_single_character(handle["key"], char, handle.get("data"))
        return f"{name}: used — {it['uses']}/{it.get('uses_max')} uses left.{heal_ptr}"

    return f"{name}: nothing depletes (no usage die or uses)."

def _usage_dispatch(action: str, character: str = None,
                    weapon: str = None, to: str = None, item: str = None) -> str:
    """Logic for the usage() tool (separated so it is unit-testable)."""
    action = (action or "").strip().lower()

    _VALID_ACTIONS = {"status", "roll", "reload", "feed", "use"}
    if action not in _VALID_ACTIONS:
        return f"Unknown action '{action}'. Use status | roll | reload | feed | use."

    if action == "status":
        data, err = _load_characters()
        if err or not data:
            return "Could not load characters."
        chars = data.get("characters", {})
        if character:
            key, char = _find_character(data, character)
            if char is None:
                return f"No character named '{character}'."
            items = [(key, char)]
        else:
            items = list(chars.items())
        lines = ["**Usage / Load status**"]
        load_parts = []
        for key, char in items:
            cname = char.get("name", key)
            slots = _calculate_slots(char)
            tag = " (ENCUMBERED — STR/DEX/CON saves at DIS)" if slots["encumbered"] else ""
            load_parts.append(f"{cname} {slots['total_used'] + slots['wounds']}/{slots['capacity']}{tag}")
        lines.append("LOAD: " + " · ".join(load_parts))
        for key, char in items:
            cname = char.get("name", key)
            for it in char.get("inventory", {}).get("carried", []):
                if not _item_depletes(it):
                    continue
                nm = it.get("name", "?")
                if it.get("broken"):
                    lines.append(f"  {cname} — {nm}: BROKEN (unusable until fixed)")
                elif _usage_is_parasitic(it):
                    lines.append(f"  {cname} — {nm}: ∞ (Parasitic)")
                else:
                    lines.append(f'  {cname} — {_isl.depletable_label(it)} → {_pf.push_call("usage", action="use", character=cname, item=nm)}')
        return "\n".join(lines)

    if action == "use":
        target_name = item or weapon
        if not character or not target_name:
            return "action='use' requires character and item."
        h = _item_resolve(character, target_name)
        if h is None:
            return f"'{character}' is not a player character."
        if isinstance(h, str):
            return h
        return _item_use(h)

    # roll / reload / feed all need a resolved weapon handle
    target_name = item or weapon
    if not character or not target_name:
        return f"action='{action}' requires character and item."
    handle = _usage_resolve(character, target_name)
    if handle is None:
        return f"'{character}' is not a player character."
    if isinstance(handle, str):
        return handle  # not-found / ambiguous

    if action == "roll":
        return _usage_deplete_roll(handle)
    if action == "reload":
        return _usage_reload(handle, to=to)
    if action == "feed":
        return _usage_feed(handle)
    # Unreachable — _VALID_ACTIONS guard above catches unknowns — but kept as a safety net.
    return f"Unknown action '{action}'. Use status | roll | reload | feed."


_INJECTED = ('VAARNISH_POISONS',)


def register_substances(srv):
    """Bind the running server module + inject the shared never-patched data table.

    `srv` is the live server module (sys.modules[__name__] from server.py's startup) —
    `__main__` when launched via `python server.py`, or `server` when imported. The
    delegates resolve their targets on it at call time, so test monkeypatches stay live.
    """
    global _server
    _server = srv
    g = globals()
    for _name in _INJECTED:
        g[_name] = getattr(srv, _name)
