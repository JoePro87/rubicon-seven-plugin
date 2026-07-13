# survival.py
"""Pure Vaarn survival primitives (S1): daily-needs computation, supply
consumption resolution, Deprived condition records, derived condition effects.
No game state, no I/O — shared by server.py and the hooks. Sibling of
wounds.py; same storage rule: persist RECORDS on the sheet, derive effects on
read, server-side appliers own mutations.

Book authority: extraction batch_02 p.35 (1 water/day, Deprived, 3-day thirst
death), batch_03 p.37 (Deprivation blocks Rests). Joe rulings 2026-06-10 in
the spec (docs/superpowers/specs/2026-06-10-survival-supply-design.md):
location-gated tracking, hybrid pool+carried, rest-overlaps-day,
Lithling/Synth exemption, survival parameters are SHEET DATA (gifts/grafts/
mutations edit fields, never code).
"""
import re

DEFAULT_DEATH_DAYS = 3


def survival_block(char: dict) -> dict:
    """Sheet survival parameters with defaults applied. Explicit fields always
    win; wound_table only sets the default. Fail-safe: needs default ON only
    for 'biological' — synthetic/mechanical/vehicle/unknown/missing wound_table
    consumes nothing unless the sheet says so (C1: vehicles merge into the
    characters dict with wound_table 'mechanical')."""
    blk = dict(char.get("survival") or {})
    biological = char.get("wound_table") == "biological"
    blk.setdefault("needs_water", biological)
    blk.setdefault("needs_food", biological)
    blk.setdefault("water_per_day", 1)
    blk.setdefault("food_per_day", 1)
    blk.setdefault("death_days_thirst", DEFAULT_DEATH_DAYS)
    blk.setdefault("death_days_starvation", DEFAULT_DEATH_DAYS)
    return blk


def _iter_items(char: dict):
    """Schema-tolerant walk of every item dict in the sheet's inventory."""
    inv = char.get("inventory") or {}
    for section in inv.values():
        if isinstance(section, list):
            for item in section:
                if isinstance(item, dict):
                    yield item


def _tag_key(name: str) -> str:
    """Normalize a prose tag to its bare lowercased name (strip parenthetical).
    Mirrors weapon_schema._tag_key — inline to keep this module pure (no imports
    from server.py or weapon_schema). Example: 'Parasitic (doubles rations)' -> 'parasitic'."""
    return re.split(r"\s*\(", str(name).strip().lower())[0].strip()


def _has_tag(item: dict, tag: str) -> bool:
    """True if item carries the given tag.

    Recon finding (2026-06-10): server.py._weapon_has_tag checks engine_tags
    with simple lowercasing AND checks tags via ws._tag_key (strips
    parentheticals, e.g. 'Parasitic (doubles rations)' -> 'parasitic').
    This function mirrors both paths without importing weapon_schema:
    - engine_tags: simple lowercase string match
    - tags: _tag_key normalization (parenthetical-stripped lowercase)
    Both fields are checked so generated weapons (engine_tags) AND hand-authored
    items (prose tags list) are covered."""
    tag = tag.lower()
    # engine_tags: generated weapons, simple lowercase
    v = item.get("engine_tags") or []
    if isinstance(v, (list, tuple)) and tag in [str(t).lower() for t in v]:
        return True
    # tags: prose tags with possible parentheticals — normalize via _tag_key
    v = item.get("tags") or []
    if isinstance(v, (list, tuple)) and any(_tag_key(t) == tag for t in v):
        return True
    return False


def daily_needs(char: dict) -> dict:
    """{'water': N, 'food': N} for one day, computed ON-READ: survival block
    (exemptions, Gills) x parasitic doubling (U5: any equipped parasitic item
    doubles rations while equipped)."""
    blk = survival_block(char)
    water = blk["water_per_day"] if blk["needs_water"] else 0
    food = blk["food_per_day"] if blk["needs_food"] else 0
    _dbl = condition_effects(char.get("conditions") or [])["double_rations"]
    if _dbl or any(_has_tag(i, "parasitic") for i in _iter_items(char)):
        water, food = water * 2, food * 2
    return {"water": water, "food": food}


def deprivation_clock(char: dict, cause: str) -> int:
    """Death-clock length in days for a cause ('thirst'|'starvation'|...)."""
    blk = survival_block(char)
    return blk.get(f"death_days_{cause}", DEFAULT_DEATH_DAYS)


def consume_day(needs: dict, pool, carried_items: list, with_pool: bool,
                already: dict = None) -> dict:
    """Resolve one PC-day of consumption. MUTATES pool and carried_items
    (the caller owns load/save). Resolution order per the spec: pool (when it
    exists and the PC is with it) -> carried ration items -> shortfall.
    `already` credits rations consumed earlier today (rest overlap, R-S1c).
    Returns the per-need shortfall dict."""
    shortfall = {}
    for need in ("water", "food"):
        owed = max(0, needs.get(need, 0) - (already or {}).get(need, 0))
        if owed and with_pool and isinstance(pool, dict):
            take = min(owed, max(0, pool.get(need, 0)))
            if take:
                pool[need] = pool.get(need, 0) - take
            owed -= take
        if owed:
            for item in carried_items or []:
                if not isinstance(item, dict) or item.get("ration_type") != need:
                    continue
                take = min(owed, max(0, int(item.get("rations", 0))))
                item["rations"] = int(item.get("rations", 0)) - take
                owed -= take
                if not owed:
                    break
        shortfall[need] = owed
    return shortfall


def tick_deprivation(conditions: list, cause: str, met: bool, day: int,
                     clock_days: int) -> list:
    """Create/keep/clear the Deprived record for one cause after the day's
    consumption attempt. MUTATES and returns conditions."""
    rec = next((c for c in conditions
                if isinstance(c, dict) and c.get("name") == "Deprived"
                and c.get("cause") == cause), None)
    if met:
        if rec is not None:
            conditions.remove(rec)
        return conditions
    if rec is None:
        conditions.append({"name": "Deprived", "cause": cause,
                           "since_day": day, "death_day": day + clock_days})
    return conditions


# E1: the effects reader graduated into conditions.py (the general framework).
# Re-exported here so every existing _sv.condition_effects caller (rest, the
# supply tick, the hooks) keeps working against the ONE implementation.
from conditions import condition_effects  # noqa: E402,F401


# --- S2 Foraging helpers (pure; spec docs/superpowers/specs/2026-06-11-foraging-design.md) ---

_DICE_RX = re.compile(r"\b(\d*)[dD](\d+)\b")
RATION_NAMES = {"water": "Water Rations", "food": "Food Rations"}
MAX_RATIONS_PER_SLOT = 3  # book p.14/35: up to 3 water rations per slot; food likewise


def resolve_yield(y: dict, roll_fn) -> dict:
    """Resolve a yield annotation ({'water': 'd8', 'food': 3}) into rolled
    amounts. roll_fn(notation) -> int (injected for testability).
    Returns {'water': int, 'food': int, 'detail': ['water d8=5', ...]}.
    Flat ints produce no detail entry (only dice rolls are worth narrating);
    negative annotation values clamp to 0 (a hand-authored table mistake must
    never become a hidden debit)."""
    out = {"water": 0, "food": 0, "detail": []}
    for kind in ("water", "food"):
        v = y.get(kind, 0)
        if isinstance(v, str):
            n = roll_fn(v)
            out[kind] = n
            out["detail"].append(f"{kind} {v}={n}")
        elif v:
            out[kind] = max(0, int(v))
    return out


def roll_dice_in_text(text: str, roll_fn) -> str:
    """Annotate every dice expression in entry text with a rolled value:
    'd6 Glass Tigers' -> 'd6=4 Glass Tigers'. Used for SCENE entries only
    (yield entries resolve via the annotation, never the prose)."""
    def _sub(m):
        expr = f"{m.group(1) or ''}d{m.group(2)}"
        return f"{expr}={roll_fn(expr)}"
    return _DICE_RX.sub(_sub, text)


def adjust_carried(char: dict, water: int = 0, food: int = 0) -> list:
    """Credit/debit carried ration items on a sheet. Mutates char; returns
    human-readable change notes. Credits top up existing ration items to
    MAX_RATIONS_PER_SLOT, then mint new items in the S1 standard shape.
    Debits drain ration items and delete empties. Only items WITH a
    ration_type are touched (Water Tokens currency has none)."""
    notes = []
    inv = char.get("inventory")
    if not isinstance(inv, dict):
        inv = {"carried": []}
        char["inventory"] = inv
    carried = inv.setdefault("carried", [])
    for kind, delta in (("water", water), ("food", food)):
        if not delta:
            continue
        items = [i for i in carried
                 if isinstance(i, dict) and i.get("ration_type") == kind]
        if delta > 0:
            remaining = delta
            for i in items:
                space = MAX_RATIONS_PER_SLOT - int(i.get("rations", 0))
                if space > 0 and remaining:
                    take = min(space, remaining)
                    i["rations"] = int(i.get("rations", 0)) + take
                    remaining -= take
            while remaining > 0:
                take = min(MAX_RATIONS_PER_SLOT, remaining)
                carried.append({"name": RATION_NAMES[kind], "ration_type": kind,
                                "rations": take, "slots": 1})
                remaining -= take
            notes.append(f"+{delta} {kind}")
        else:
            remaining = -delta
            for i in items:
                take = min(int(i.get("rations", 0)), remaining)
                i["rations"] = int(i.get("rations", 0)) - take
                remaining -= take
                if not remaining:
                    break
            carried[:] = [i for i in carried
                          if not (isinstance(i, dict)
                                  and i.get("ration_type") == kind
                                  and int(i.get("rations", 0)) <= 0)]
            taken = -delta - remaining
            notes.append(f"-{taken} {kind}"
                         + (" (only that many on hand)" if remaining else ""))
    return notes
