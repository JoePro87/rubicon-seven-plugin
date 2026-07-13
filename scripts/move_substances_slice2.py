"""Decomposition slice 2 — extract the substance helper web into substances.py.

VERBATIM AST extraction (server.py mojibake makes hand-edits hazardous). Moves the
toxin / poison / usage(ammo) / item-consumable helper functions (38 funcs + 2 consts)
out of server.py into a new substances.py. The usage/affliction/supply TOOL
dispatchers stay in server.py and import-and-alias the moved names back.

SEAM HANDLING (recon: scripts/recon_slice2.py + recon_slice2_free.py) —
  * Movers call 17 cross-module functions that STAY in server.py (weapon helpers,
    character persistence, and the death/wound seam). Many are heavily monkeypatched
    on `server` by tests (_load_characters 91x, _save_single_character 55x,
    _check_death_conditions 13x, ...). A by-reference inject would FREEZE those
    bindings and bypass every patch. Instead substances.py installs a uniform
    DELEGATING SHIM per name: each resolves `server.<name>` at CALL TIME, so every
    existing monkeypatch keeps working with ZERO test churn. (Tests always patch
    server.<name> — even the engine_core death-seam dual-patches mirror onto server.)
  * VAARNISH_POISONS is a never-patched, never-reassigned data table — injected
    by-reference via register_substances() (it is indexed, not called, so no shim).
  * GAME_STATE is the engine_core by-reference singleton (mutated in place, never
    rebound) — imported straight from engine_core, exactly as server itself does.
  * Three movers are themselves monkeypatched on `server` AND called via internal
    mover->mover edges (_toxin_resolve, _toxin_enemy_save, _poison_enemy_save). A
    shim can't cover a function calling its own sibling, so the affected tests are
    DUAL-PATCHED separately (patch both server.X and substances.X) — done outside
    this script.

Load order: import+alias-back goes at the removal site (early; substances imports
cleanly there — it touches no server attribute at import time). register_substances()
goes AFTER session_tools registration, by which point every injected name is defined.
Idempotent-ish: refuses to run if substances.py already exists.
"""
import ast
import os
import sys

if os.path.exists("substances.py"):
    sys.exit("ABORT: substances.py already exists — slice 2 has already run.")

MOVE_FUNCS = [
    # toxin
    "_toxin_susceptible_enemy", "_toxin_susceptible_pc", "_toxin_resolve", "_toxin_get",
    "_toxin_set", "_toxin_save_dc", "_toxin_enemy_save", "_toxin_incur", "_toxin_tick",
    "_toxin_cure", "_toxin_dispatch", "_toxin_die_from_dice", "_toxin_attack_reroute",
    # poison
    "_poison_record", "_poison_immune", "_poison_enemy_save", "_poison_current_day",
    "_poison_death", "_poison_resolve_effect",
    # usage (ammo / charges)
    "_usage_to_chain", "_usage_to_ammo", "_usage_applies", "_usage_is_parasitic",
    "_usage_is_fungal", "_usage_is_expended", "_usage_ammo_max", "_usage_resolve",
    "_usage_get", "_usage_set", "_usage_carried_ammo", "_usage_deplete_roll",
    "_usage_feed", "_usage_reload", "_usage_dispatch",
    # item consumables
    "_broken_item_msg", "_item_depletes", "_item_resolve", "_item_use",
]
MOVE_CONSTS = ["_NON_BIOLOGICAL_PC_SPECIES", "POISON_SAVE_TN"]

# Cross-module functions the movers call that stay in server.py. Each gets a
# call-time delegating shim to server.<name> (patch-transparent). Complete closure
# computed by scripts/recon_slice2.py (server-defined) + recon_slice2_free.py (all
# free names incl. engine_core imports).
DELEGATES = [
    # weapon helpers (server-resident)
    "_find_weapon_record", "_weapon_has_tag", "_weapon_is_ranged",
    # game-state + character persistence
    "_save_game_state", "_load_characters", "_save_single_character", "_find_character",
    # death / wound / condition seam (engine_core, imported into server)
    "_apply_ability_damage_from_wound", "_apply_hp_damage_and_wounds",
    "_check_death_conditions", "_death_gate", "_death_seam_lines",
    "_condition_save_note", "_wound_save_note", "_encumbrance_save_note",
    # item-slot helpers
    "_calculate_slots", "_refresh_slot_fields",
]
# Never-patched, never-reassigned data table → injected by reference (it is indexed,
# not called, so it can't be a delegating shim).
INJECT = ["VAARNISH_POISONS"]

src = open("server.py", encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# --- Locate spans ---
func_nodes, const_nodes = {}, {}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS:
        func_nodes[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id in MOVE_CONSTS:
                const_nodes[t.id] = n

missing_f = set(MOVE_FUNCS) - set(func_nodes)
missing_c = set(MOVE_CONSTS) - set(const_nodes)
assert not missing_f, f"missing funcs: {missing_f}"
assert not missing_c, f"missing consts: {missing_c}"


def span(node):
    start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
    return start, node.end_lineno


def body_text(node):
    s, e = span(node)
    return "".join(lines[s - 1:e])


# Extract verbatim, in source order, so substances.py reads top-to-bottom sensibly.
moved = sorted(
    [(span(n)[0], "func", name, body_text(n)) for name, n in func_nodes.items()]
    + [(span(n)[0], "const", name, body_text(n)) for name, n in const_nodes.items()]
)

# --- Build substances.py ---
delegates_repr = "(\n" + "".join(f'    "{n}",\n' for n in DELEGATES) + ")"
header = '''"""Substances — decomposition slice 2 (2026-06-17).

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
_DELEGATES = ''' + delegates_repr + '''
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n

# Injected by reference at registration (never-patched, never-reassigned table).
VAARNISH_POISONS = None
'''

blocks = "\n\n".join(text.rstrip("\n") for _, _, _, text in moved)

register_fn = (
    "\n\n_INJECTED = " + repr(tuple(INJECT)) + "\n\n\n"
    "def register_substances(srv):\n"
    '    """Inject the shared, never-patched data + helpers that stay resident in server.py."""\n'
    "    g = globals()\n"
    "    for _name in _INJECTED:\n"
    "        g[_name] = getattr(srv, _name)\n"
)

sub_src = header + "\n\n" + blocks + "\n" + register_fn
open("substances.py", "w", encoding="utf-8").write(sub_src)

# --- Rewrite server.py: remove all moved spans, insert import+alias-back at the site ---
remove = set()
for n in list(func_nodes.values()) + list(const_nodes.values()):
    s, e = span(n)
    remove.update(range(s, e + 1))

# Alias back EVERY moved name (funcs AND consts) so every `server.X` reference —
# tests and staying callers — keeps resolving (slice-1 lesson). Both consts are
# immutable, so an alias can't go stale.
ALIAS_NAMES = MOVE_FUNCS + MOVE_CONSTS
alias_block = (
    "# Substance helpers (toxin/poison/usage/item — 38 funcs + 2 consts) moved to\n"
    "# substances.py (decomposition slice 2); imported-and-aliased back here. Shared\n"
    "# never-patched deps (_find_weapon_record/_weapon_has_tag/_weapon_is_ranged/\n"
    "# VAARNISH_POISONS) stay here, injected via register_substances() below.\n"
    "import substances\n"
    "from substances import (\n"
    + "".join(f"    {name},\n" for name in ALIAS_NAMES)
    + ")\n"
)

first_removed = min(remove)
new_lines = []
marker_done = False
for i, line in enumerate(lines, start=1):
    if i in remove:
        if not marker_done:
            new_lines.append(alias_block)
            marker_done = True
        continue
    new_lines.append(line)
new_server = "".join(new_lines)

# --- Insert register_substances() AFTER session_tools registration ---
ANCHOR_SESS = "session_tools.register_session_tools(mcp, sys.modules[__name__])\n"
assert new_server.count(ANCHOR_SESS) == 1, "session_tools registration anchor not unique/found"
reg_call = (
    ANCHOR_SESS
    + "\n# Slice 2: inject the shared, never-patched substance deps (defined above) into\n"
    "# the relocated substance helpers.\n"
    "substances.register_substances(sys.modules[__name__])\n"
)
new_server = new_server.replace(ANCHOR_SESS, reg_call, 1)

open("server.py", "w", encoding="utf-8").write(new_server)

# --- Report ---
moji_before = src.count("Ã")
moji_after = new_server.count("Ã") + sub_src.count("Ã")
print(f"MOVED {len(MOVE_FUNCS)} funcs + {len(MOVE_CONSTS)} consts to substances.py")
print(f"substances.py: {len(sub_src.splitlines())} lines")
print(f"server.py: {len(lines)} -> {len(new_lines)} lines ({len(lines) - len(new_lines)} removed)")
print(f"mojibake: server+sub before={moji_before} after={moji_after} (net-new={moji_after - moji_before})")
