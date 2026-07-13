"""Decomposition slice 6 (FINAL) — extract the CHARACTER section into character_tools.py.

VERBATIM AST extraction. Moves the whole character-management cluster (the helpers
between the character() dispatcher and the cybernetics banner) out of server.py into
character_tools.py: character CRUD/leveling, elixirs, companions/followers/mercenaries/
pets/steeds/vehicles, resurrection, wounds, and vehicle-damage helpers — 57 funcs + 5
consts. The character()/wound() tool dispatchers stay in server.py and alias the moved
names back. _roll_cacogen_mutation STAYS (re-exported; single mint path, patched).

SEAM HANDLING (recon: scripts/recon_slice6.py) — the largest seam surface of the set:
  * DELEGATES (call-time shims to the live server module): 18 cross-module funcs the
    movers call that stay in server/engine_core — persistence, the death/wound seam,
    status helpers, _roll_cacogen_mutation, _poison_enemy_save (substances alias),
    _elixir_row_for (generators alias). Patch-transparent (many are heavily patched).
  * map_system is REBIND-patched by tests (`setattr(server, "map_system", MapSystem(...))`),
    so neither import nor inject survives. A _LiveServerProxy forwards attribute access to
    _server.map_system at call time, so rebinds stay effective.
  * INJECT by reference (never-rebound server data tables): VAARNISH_ELIXIRS,
    BIOLOGICAL_WOUNDS, SYNTHETIC_WOUNDS.
  * Direct imports (stable / attribute-patched only, never rebind-patched): stdlib +
    engine_core (CAMPAIGN_DIR/read_file/dice/GAME_STATE) + the domain modules
    (followers/mercenaries/pets_steeds/vehicles/wounds/conditions/item_slots/ancestries/
    weapon_schema/push_format) + ToolError.
  * We do NOT `import server` (the slice-2 __main__ boot bug); register_character_tools
    binds the live module.
  * FAULT LINES: 5 movers are patched on server AND called via mover->mover edges
    (_active_vault_turn, _move_sheet_to_departed, _roll_3d6_lowest, _roll_d4, _roll_d6) —
    dual-patched in their tests. _character_take_damage is patched too but has NO
    mover->mover caller (staying combat uses the server alias), so it needs no dual-patch.

Idempotent-ish: refuses to run if character_tools.py already exists.
"""
import ast
import os
import sys

if os.path.exists("character_tools.py"):
    sys.exit("ABORT: character_tools.py already exists — slice 6 has already run.")

SECTION_LO, SECTION_HI = 9342, 12505
# Keep in server.py (NOT moved): _roll_cacogen_mutation (single mint path, re-exported),
# plus 5 generic utility leaves that are patched on server AND called via mover->mover
# edges — keeping them resident + delegating to them makes the patches bite with zero
# per-test dual-patching, and they aren't really "character" domain (vault/file/dice).
MUST_STAY = {
    "_roll_cacogen_mutation",
    "_active_vault_turn", "_move_sheet_to_departed",
    "_roll_3d6_lowest", "_roll_d4", "_roll_d6",
}

DELEGATES = [
    "_parse_status_content", "_revival_cleanup", "read_current_status",
    "_roll_cacogen_mutation", "_save_game_state", "_apply_wound", "_elixir_hp_floor",
    "_elixir_row_for", "_is_pc_sheet", "_apply_hp_damage_and_wounds", "_calculate_slots",
    "_check_death_conditions", "_death_gate", "_refresh_slot_fields", "_find_character",
    "_load_characters", "_save_single_character", "_poison_enemy_save",
    # generic leaves kept in server (patched + mover->mover called) — delegated so the
    # moved helpers reach them at call time, patch-transparent:
    "_active_vault_turn", "_move_sheet_to_departed",
    "_roll_3d6_lowest", "_roll_d4", "_roll_d6",
]
INJECT = ["VAARNISH_ELIXIRS", "BIOLOGICAL_WOUNDS", "SYNTHETIC_WOUNDS"]
PROXIES = ["map_system"]

src = open("server.py", encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

# Move set = every top-level func + const whose def starts in the section, minus MUST_STAY.
func_nodes, const_nodes = {}, {}
for n in tree.body:
    s = getattr(n, "lineno", 0)
    if not (SECTION_LO <= s <= SECTION_HI):
        continue
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name not in MUST_STAY:
        func_nodes[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                const_nodes[t.id] = n

MOVE_FUNCS = list(func_nodes)
MOVE_CONSTS = list(const_nodes)


def span(node):
    start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
    return start, node.end_lineno


def body_text(node):
    s, e = span(node)
    return "".join(lines[s - 1:e])


moved = sorted(
    [(span(n)[0], name, body_text(n)) for name, n in func_nodes.items()]
    + [(span(n)[0], name, body_text(n)) for name, n in const_nodes.items()]
)

# --- Build character_tools.py ---
delegates_repr = "(\n" + "".join(f'    "{n}",\n' for n in DELEGATES) + ")"
inject_repr = "(" + "".join(f'"{n}", ' for n in INJECT).rstrip(", ") + ",)"
header = '''"""Character management — decomposition slice 6 (2026-06-17), the final + largest.

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
from engine_core import CAMPAIGN_DIR, read_file, dice, GAME_STATE

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
_DELEGATES = ''' + delegates_repr + '''
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n

''' + "".join(f'{p} = _LiveServerProxy("{p}")\n' for p in PROXIES) + '''
# Injected by reference at registration (server data tables; never rebound).
''' + "".join(f"{n} = None\n" for n in INJECT)

blocks = "\n\n".join(text.rstrip("\n") for _, _, text in moved)

register_fn = (
    "\n\n\n_INJECTED = " + inject_repr + "\n\n\n"
    "def register_character_tools(srv):\n"
    '    """Bind the live server module + inject the server-resident data tables."""\n'
    "    global _server\n"
    "    _server = srv\n"
    "    g = globals()\n"
    "    for _name in _INJECTED:\n"
    "        g[_name] = getattr(srv, _name)\n"
)

ct_src = header + "\n\n" + blocks + "\n" + register_fn
open("character_tools.py", "w", encoding="utf-8").write(ct_src)

# --- Rewrite server.py: remove moved spans, insert import+alias-back at the site ---
remove = set()
for n in list(func_nodes.values()) + list(const_nodes.values()):
    s, e = span(n)
    remove.update(range(s, e + 1))

ALIAS_NAMES = MOVE_FUNCS + MOVE_CONSTS
alias_block = (
    "# CHARACTER section (57 funcs + 5 consts) moved to character_tools.py (decomposition\n"
    "# slice 6); imported-and-aliased back here. The character()/wound() tool dispatchers\n"
    "# stay and call these. _roll_cacogen_mutation stays (re-exported). \n"
    "# register_character_tools() (below) binds the live module + injects the data tables.\n"
    "import character_tools\n"
    "from character_tools import (\n"
    + "".join(f"    {name},\n" for name in ALIAS_NAMES)
    + ")\n"
)

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

# --- Insert register_character_tools() AFTER session_tools registration ---
ANCHOR_SESS = "session_tools.register_session_tools(mcp, sys.modules[__name__])\n"
assert new_server.count(ANCHOR_SESS) == 1, "session_tools registration anchor not unique/found"
reg_call = (
    ANCHOR_SESS
    + "\n# Slice 6: bind the live server module + inject the data tables into the\n"
    "# relocated character-management helpers.\n"
    "character_tools.register_character_tools(sys.modules[__name__])\n"
)
new_server = new_server.replace(ANCHOR_SESS, reg_call, 1)

open("server.py", "w", encoding="utf-8").write(new_server)

# --- Report ---
moji_before = src.count("Ã")
moji_after = new_server.count("Ã") + ct_src.count("Ã")
print(f"MOVE SET: {len(MOVE_FUNCS)} funcs + {len(MOVE_CONSTS)} consts")
print(f"  consts: {MOVE_CONSTS}")
print(f"character_tools.py: {len(ct_src.splitlines())} lines")
print(f"server.py: {len(lines)} -> {len(new_lines)} lines ({len(lines) - len(new_lines)} removed)")
print(f"mojibake: server+ct before={moji_before} after={moji_after} (net-new={moji_after - moji_before})")
