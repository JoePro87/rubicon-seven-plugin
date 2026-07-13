"""Cybernetics & Gifts — decomposition slice 3 (2026-06-17).

Extracted VERBATIM from server.py: the cybernetic install/remove/list and gift
add/remove/cost/gleam helpers behind the `cybernetic` and `gift` tools. The tool
DISPATCHERS stay in server.py and import-and-alias these back.

Cross-module functions the movers call (character persistence + slot helpers) STAY
in server.py / engine_core and are reached here through call-time DELEGATING SHIMS
(_DELEGATES below): each resolves on the live server module (bound by
register_cyber_gifts) at call time, so tests that monkeypatch server.<name> keep
working untouched. GAME_STATE is the engine_core by-reference singleton; gift data
lives in the already-extracted gifts module (imported as _gifts).
"""
import json
import random

from pydantic import Field
from fastmcp.exceptions import ToolError

import push_format as _pf
import gifts as _gifts
from engine_core import GAME_STATE


# The running server module, supplied by register_cyber_gifts() at startup. We do NOT
# `import server`: under `python server.py` the server runs as `__main__`, so a fresh
# `import server` would execute it a SECOND time as a distinct module and the alias-back
# would hit a partially-initialized cyber_gifts -> circular ImportError (the slice-2 boot
# bug). Registration hands us the live running module (`__main__` or `server`), which is
# also exactly the namespace tests monkeypatch.
_server = None


def _make_delegate(_name):
    """Build a call-time delegate to the running server.<_name> (keeps monkeypatches live)."""
    def _delegate(*args, **kwargs):
        return getattr(_server, _name)(*args, **kwargs)
    _delegate.__name__ = _name
    _delegate.__qualname__ = _name
    return _delegate


# Bare-name calls inside the moved helpers resolve to these module globals, each a thin
# delegate to the still-resident server/engine_core function.
_DELEGATES = (
    "_save_game_state",
    "_load_characters",
    "_save_single_character",
    "_find_character",
    "_calculate_slots",
    "_check_death_conditions",
)
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n


# Surfaced (in tool output) whenever a removal reverses a pre-fix implant record
# that has no recorded applied-delta, so the DM can sanity-check a stat that may
# have been installed near the +10 cap (where full-bonus reversal over-subtracts).
_LEGACY_IMPLANT_NOTICE = (
    "⚠ legacy implant record (pre-2026-07-02): reversal used the full "
    "listed bonus; verify the ability score if this implant was installed near "
    "the +10 cap.")


def _reverse_implant_stat_bonus(char, implant):
    """C20: reverse a cybernetic implant's APPLIED stat bonus on `char`.

    Install caps a bonus at +10, so the effective amount added may be less than
    the requested bonus. We reverse the EFFECTIVE applied delta recorded at
    install (`stat_bonus_applied`), falling back to the requested `stat_bonus`
    for legacy records that predate that field. Any CON change recomputes slot
    capacity (10 + CON), matching engine_core._apply_ability_damage_from_wound.
    Mutates `char` in place; callers own their output + the death check.

    Returns True iff the LEGACY fallback was taken (no stat_bonus_applied key on
    a record that still carries a stat_bonus) so the caller can surface a notice.
    """
    used_legacy = ('stat_bonus_applied' not in implant
                   and bool(implant.get('stat_bonus')))
    applied = implant.get('stat_bonus_applied')
    if not applied:
        applied = implant.get('stat_bonus') or {}
    abilities = char.get('abilities', {})
    for stat, amount in applied.items():
        stat = str(stat).upper()
        if stat in abilities and isinstance(abilities[stat], dict):
            abilities[stat]['current'] = abilities[stat].get('current', 0) - amount
            abilities[stat].pop('notes', None)
            if stat == 'CON':
                new_con = abilities[stat]['current']
                char['slot_capacity_bonus'] = new_con
                char['slot_capacity_total'] = 10 + new_con
    return used_legacy


def _cybernetic_install(
    character_name: str,
    implant_name: str,
    ability_slot: str,
    effect: str,
    stat_bonus: str = None,
    day_installed: int = None
) -> str:
    """Install cybernetic implant. Use after surgery scene or implant acquisition. Rejects if ability slot occupied."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    ability_slot = ability_slot.upper()
    if ability_slot not in ['STR', 'DEX', 'CON', 'INT', 'PSY', 'EGO']:
        return f"Invalid ability slot '{ability_slot}'"

    augs = char.setdefault('augmentations', {})

    # E3: an infection-marked slot is blocked until the nanomachine is cured.
    _occupant = augs.get(ability_slot)
    if isinstance(_occupant, dict) and _occupant.get("infection"):
        _dis = _occupant.get("disease") or _occupant.get("name", "an infection")
        return (f"REJECTED: {char['name']}'s {ability_slot} slot is infected by "
                f"{_dis} - cure the infection first before installing here.\n"
                + _pf.next_block(
                    _pf.push_call("affliction", kind="condition", action="save",
                                  character=char['name'], name=_dis,
                                  save_total=_pf.raw("<cure roll>")),
                    label="cure to free the slot"))

    # Check if slot occupied
    if augs.get(ability_slot) is not None:
        existing = augs[ability_slot]
        if isinstance(existing, list):
            existing_name = ", ".join(a.get('name', '?') for a in existing)
        else:
            existing_name = existing.get('name', 'Unknown')
        raise ToolError(f"REJECTED: {ability_slot} slot already occupied by: {existing_name}")

    # Build implant entry
    implant = {
        'name': implant_name,
        'effect': effect,
        'day_installed': day_installed or data.get('meta', {}).get('campaign_day', 83)
    }

    # Apply stat bonus if specified
    if stat_bonus:
        try:
            bonus = json.loads(stat_bonus)
            implant['stat_bonus'] = bonus
            # C20: record the EFFECTIVE applied delta per stat (may be < the
            # requested bonus when the +10 cap engages) so removal reverses
            # exactly what was added and never over-subtracts.
            applied = {}
            for stat, amount in bonus.items():
                stat = stat.upper()
                if stat in char.get('abilities', {}):
                    old_val = char['abilities'][stat].get('current', 0) if isinstance(char['abilities'][stat], dict) else char['abilities'][stat]
                    new_val = min(10, old_val + amount)  # Cap at +10
                    applied[stat] = new_val - old_val
                    if isinstance(char['abilities'][stat], dict):
                        char['abilities'][stat]['current'] = new_val
                        char['abilities'][stat]['notes'] = f"+{amount} from {implant_name}"
                    else:
                        char['abilities'][stat] = {'current': new_val, 'base': old_val, 'notes': f"+{amount} from {implant_name}"}
                    # C20: keep slot capacity in sync with CON, like every other
                    # CON-mutating path (engine_core._apply_ability_damage_from_wound).
                    if stat == 'CON':
                        char['slot_capacity_bonus'] = new_val
                        char['slot_capacity_total'] = 10 + new_val
            implant['stat_bonus_applied'] = applied
        except json.JSONDecodeError:
            pass

    augs[ability_slot] = implant
    _save_single_character(key, char, data)

    return f"**{char['name']}** installed: {implant_name} in {ability_slot} slot\nEffect: {effect}"

def _cybernetic_remove(
    character_name: str,
    implant_name: str
) -> str:
    """Remove cybernetic implant. Use after surgery scene to remove augmentation. Removes stat bonuses."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    augs = char.get('augmentations', {})
    implant_lower = implant_name.lower()

    for slot, aug in augs.items():
        if aug is None:
            continue

        # Handle list of implants in slot
        if isinstance(aug, list):
            for i, a in enumerate(aug):
                if implant_lower in a.get('name', '').lower():
                    removed = aug.pop(i)
                    if not aug:
                        augs[slot] = None

                    # C20: reverse the EFFECTIVE applied delta (falls back to the
                    # requested stat_bonus for legacy records); recomputes slots on CON.
                    _legacy = _reverse_implant_stat_bonus(char, removed)

                    _save_single_character(key, char, data)
                    return _remove_result_line(char, removed['name'], slot, _legacy)
        else:
            if implant_lower in aug.get('name', '').lower():
                removed = aug
                augs[slot] = None

                # C20: reverse the EFFECTIVE applied delta (falls back to the
                # requested stat_bonus for legacy records); recomputes slots on CON.
                _legacy = _reverse_implant_stat_bonus(char, removed)

                _save_single_character(key, char, data)
                return _remove_result_line(char, removed['name'], slot, _legacy)

    return f"Implant '{implant_name}' not found on {char['name']}"


def _remove_result_line(char, implant_name, slot, legacy=False):
    """Build the removal message and, C20, append (a) a legacy-record notice when
    the reversal used the full listed bonus, and (b) a below-threshold death
    warning if reversing the implant's bonus pushed the sheet into a death
    condition (an ability below -10, or slots now full)."""
    msg = f"**{char['name']}** removed: {implant_name} from {slot} slot"
    if legacy:
        msg += f"\n{_LEGACY_IMPLANT_NOTICE}"
    is_dead, reason = _check_death_conditions(char)
    if is_dead:
        msg += f"\n\n**!!! WARNING: {reason} !!!**"
    return msg

def _cybernetic_list(
    character_name: str = None
) -> str:
    """List cybernetic implants and open slots. Use to check what augmentations characters have installed."""
    data, err = _load_characters()
    if err:
        return err

    def format_char_augs(char):
        augs = char.get('augmentations', {})
        installed = []
        available = []
        for slot in ['STR', 'DEX', 'CON', 'INT', 'PSY', 'EGO']:
            aug = augs.get(slot)
            if aug is None:
                available.append(slot)
            elif isinstance(aug, list):
                for a in aug:
                    installed.append(f"  [{slot}] {a.get('name', 'Unknown')}")
            else:
                installed.append(f"  [{slot}] {aug.get('name', 'Unknown')}")

        output = [f"**{char['name']}**"]
        if installed:
            output.extend(installed)
        else:
            output.append("  (no implants)")
        output.append(f"  Available slots: {', '.join(available) if available else 'NONE'}")
        return output

    if character_name:
        key, char = _find_character(data, character_name)
        if not char:
            raise ToolError(f"Character '{character_name}' not found")
        return "\n".join(format_char_augs(char))

    output = ["**PARTY CYBERNETICS**", ""]
    for key, char in data.get('characters', {}).items():
        output.extend(format_char_augs(char))
        output.append("")

    return "\n".join(output)

def _gift_add(
    character_name: str = Field(description="Character name"),
    gift_name: str = Field(description="Gift name"),
    effect: str = Field(description="Mechanical effect"),
    source: str = Field(description="How acquired"),
    day_acquired: int = Field(default=None, description="Campaign day")
) -> str:
    """Add mystic gift to character. Use after acquiring gift through fungus, surgery, or training. Uses 1 slot, increases Gleam."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    # Check slot capacity
    slots = _calculate_slots(char)
    if slots['free'] < 1:
        raise ToolError(f"REJECTED: {char['name']} has no free slots for new gift. Gifts use 1 slot each.")

    # Check for duplicate gift (prevent accidental double-adds)
    existing_gifts = char.get('mystic_gifts', [])
    for existing in existing_gifts:
        if existing.get('name', '').lower() == gift_name.lower():
            return f"**DUPLICATE:** {char['name']} already has gift '{gift_name}'. Use gift(action='remove') first if replacing."

    gift = {
        'name': gift_name,
        'effect': effect,
        'source': source,
        'day_acquired': day_acquired or data.get('meta', {}).get('campaign_day', 83)
    }

    char.setdefault('mystic_gifts', []).append(gift)

    # Update Gleam
    psy = char.get('abilities', {}).get('PSY', {})
    psy_bonus = psy.get('current', 0) if isinstance(psy, dict) else psy
    char['gleam'] = len(char.get('mystic_gifts', [])) + psy_bonus

    _save_single_character(key, char, data)

    new_slots = _calculate_slots(char)
    return f"**{char['name']}** gained gift: {gift_name}\nEffect: {effect}\nGleam: {char['gleam']}\nSlots: {new_slots['total_used']}/{new_slots['capacity']}"

def _gift_remove(
    character_name: str = Field(description="Character name"),
    gift_name: str = Field(description="Gift to remove")
) -> str:
    """Remove mystic gift. Rare - use only when gift is surgically removed or narratively lost. Decreases Gleam."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    gifts = char.get('mystic_gifts', [])
    gift_lower = gift_name.lower()

    for i, gift in enumerate(gifts):
        if gift_lower in gift.get('name', '').lower():
            removed = gifts.pop(i)

            # Update Gleam
            psy = char.get('abilities', {}).get('PSY', {})
            psy_bonus = psy.get('current', 0) if isinstance(psy, dict) else psy
            char['gleam'] = len(char.get('mystic_gifts', [])) + psy_bonus

            _save_single_character(key, char, data)
            return f"**{char['name']}** lost gift: {removed['name']}\nGleam: {char['gleam']}"

    return f"Gift '{gift_name}' not found on {char['name']}"

def _gift_calculate_cost(
    target_level: int = Field(description="Target's level")
) -> str:
    """Calculate HP cost for mystic gift use. Call before using a gift to determine cost/damage dice."""
    if target_level <= 2:
        die = "d6"
    elif target_level <= 4:
        die = "d8"
    elif target_level <= 6:
        die = "d10"
    elif target_level <= 8:
        die = "d12"
    else:
        die = "d20"

    return f"**Target Level {target_level}:**\n  HP Cost: {die}\n  Damage/Heal: {die}+PSY\n\nReminder: Gifts always hit (no attack roll), but cost HP to use."

def _gleam_check_impl(
    character_name: str = Field(description="Character name"),
    test: bool = Field(default=False, description="True = ROLL the weekly Gleam test (d20 + Gleam vs the CH p.50 table) and resolve the outcome; threat results push a prefilled thread-clock call. Running any test re-stamps the weekly cadence."),
) -> str:
    """Reach for this WHEN the weekly psychic attention check comes due (advance_day pushes GLEAM TEST DUE) or when you need a character's current Gleam.

Gleam = equipped Gifts + PSY bonus (CH p.49; can be negative). test=True rolls d20+Gleam on the book's Gleam Test table: 1-15 nothing, 16-34 individual outcomes, 35+ Extradimensional Mystic Hunter attacks."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    gifts = char.get('mystic_gifts', [])
    psy = char.get('abilities', {}).get('PSY', {})
    psy_bonus = psy.get('current', 0) if isinstance(psy, dict) else psy

    gleam = len(gifts) + psy_bonus
    char['gleam'] = gleam

    if test is not True:
        return "\n".join([
            f"**{char['name']} GLEAM:** {gleam}",
            f"  Gifts: {len(gifts)}",
            f"  PSY bonus: {psy_bonus:+d}",
            "",
            "Weekly test (start of each adventuring week, CH p.49-50): referee rolls d20 + Gleam",
            "  1-15: nothing | 16-34: individual outcomes | 35+ cap: Extradimensional Mystic Hunter attacks",
            _pf.next_block(
                _pf.push_call("gift", action="gleam", character_name=char['name'],
                              test=_pf.raw("True")),
                label="roll the weekly test"),
        ])

    # --- Weekly Gleam test (CH p.50) ---
    d20 = random.randint(1, 20)
    total = d20 + gleam
    current_day = int(data.get('meta', {}).get('campaign_day', 0) or 0)
    lines = [f"**GLEAM TEST - {char['name']}:** d20={d20} + Gleam {gleam} = **{total}**"]

    row = _gifts.gleam_outcome(total)
    if row is None:
        lines.append("Result 1-15: Nothing. The psychic aether passes over them this week.")
    else:
        lines.append(row["text"])
        if row.get("threat"):
            lines.append(f"THREAT: {row['threat']}")
        if row.get("count_die"):
            count = random.randint(1, row["count_die"])
            lines.append(f"Count: d{row['count_die']} = {count}")
        if row.get("arrival_die"):
            arrival = random.randint(1, row["arrival_die"])
            due = current_day + arrival
            lines.append(f"Arrival: d{row['arrival_die']} = {arrival} (Day {due})")
            lines.append(_pf.next_block(
                _pf.push_call("thread", action="add",
                              thread_id=_pf.raw('"<terse-id>"'),
                              title=row["threat"],
                              description=_pf.raw('"<who sensed whom, and why it matters>"'),
                              urgency="high",
                              clock_due_day=_pf.raw(str(due)),
                              clock_label=f"{row['threat']} arrives"),
                label="wind the arrival clock - the WORLD TICK fires it when due"))

    # Stamp the weekly cadence (engine-owned; advance_day nags when 7+ days pass).
    try:
        GAME_STATE.setdefault("world_tick", {})["gleam_last_test_day"] = current_day
        _save_game_state()
    except Exception as _gse:
        lines.append(f"WARNING: cadence stamp failed ({_gse})")

    return "\n".join(lines)



def register_cyber_gifts(srv):
    """Bind the live running server module so the delegates can resolve on it."""
    global _server
    _server = srv
