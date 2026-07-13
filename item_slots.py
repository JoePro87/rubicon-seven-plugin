# item_slots.py
"""Pure helpers for Vaarn item slots and item depletion. No game state, no I/O —
just functions over item dicts and slot numbers, so server.py AND the hooks can
share them. Slot-math counterpart to dice_chain.py.
"""
import re

HARD_CEILING = 20  # book absolute max; enforced by callers (e.g. the inventory-add path), not here


def slot_cap(con_bonus: int, bonus: int = 0) -> int:
    """Book: PCs have item slots equal to 10 + CON bonus. `bonus` folds in slot
    mutations (e.g. Kangaroo Pouch +2). This is the personal cap; exceeding it is
    Encumbered (not blocked). HARD_CEILING is the separate absolute add limit."""
    return 10 + int(con_bonus) + int(bonus)


def is_encumbered(used: int, cap: int) -> bool:
    """Over the personal cap = Encumbered. At the cap is NOT over."""
    return used > cap


def item_usage_die(item: dict) -> "str | None":
    """Usage-die notation for an item, reading canonical `usage_die` then the
    weapon alias `ammo`. None if neither (or empty)."""
    return item.get("usage_die") or item.get("ammo") or None


def _int_uses(item: dict) -> "int | None":
    """The item's integer `uses` count, or None if absent/non-integer (non-int
    means DM-managed, e.g. '1/day per INT bonus')."""
    u = item.get("uses")
    if isinstance(u, bool):
        return None
    if isinstance(u, int):
        return u
    return None


def item_is_depletable(item: dict) -> bool:
    """True if the item carries a usage die OR an integer `uses` counter."""
    return bool(item_usage_die(item)) or _int_uses(item) is not None


def item_int_uses(item: dict) -> "int | None":
    """Public accessor for the item's integer `uses` count. None if absent or
    non-integer (non-int means DM-managed). Consumers (e.g. the reflex
    snapshot) call this instead of reaching for the private _int_uses."""
    return _int_uses(item)


def depletable_label(item: dict) -> "str | None":
    """Short surfacing label, e.g. 'Blowtorch (Ud8)' or 'Draught (x3)'. None if the
    item does not deplete."""
    name = item.get("name", "?")
    die = item_usage_die(item)
    if die:
        return f"{name} ({die})"
    u = _int_uses(item)
    if u is not None:
        return f"{name} (x{u})"
    return None


def parse_slots_uses(s) -> dict:
    """Parse the book's exotica `slots_uses` notation into structured fields.

    '<slots>/<uses>' where uses is 'Udx' (usage die), 'xN use(s)' (discrete count),
    'Unlimited' / 'See p.xxx' / absent (none). '<N> slots' = slots only.
    Always returns {slots:int>=1, kind:'usage_die'|'discrete'|'none',
    usage_die:str|None, uses:int|None}; never raises."""
    out = {"slots": 1, "kind": "none", "usage_die": None, "uses": None}
    if not s or not isinstance(s, str):
        return out
    txt = s.strip()

    # "3 slots" form (no slash)
    m_slots_only = re.fullmatch(r"(\d+)\s*slots?", txt, re.IGNORECASE)
    if m_slots_only:
        out["slots"] = int(m_slots_only.group(1))
        return out

    left, sep, right = txt.partition("/")
    if sep:  # only parse slot count when there IS a slash
        m_left = re.search(r"\d+", left)
        if m_left:
            out["slots"] = int(m_left.group(0))
    right = right.strip()

    m_die = re.fullmatch(r"u?d(\d+)", right, re.IGNORECASE)
    if m_die:
        out["kind"] = "usage_die"
        out["usage_die"] = "Ud" + m_die.group(1)
        return out

    m_uses = re.search(r"x\s*(\d+)\s*uses?", right, re.IGNORECASE)
    if m_uses:
        out["kind"] = "discrete"
        out["uses"] = int(m_uses.group(1))
        return out

    return out  # Unlimited / See p.xxx / unrecognised -> none
