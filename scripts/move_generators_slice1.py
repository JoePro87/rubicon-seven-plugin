"""Decomposition slice 1 — extract the content generators into generators.py.

VERBATIM AST extraction (server.py mojibake makes hand-edits hazardous). Moves 20
generator functions + 10 generator-private data tables out of server.py into a new
generators.py. The `generate`/`lookup` tool dispatchers STAY in server.py and
import-and-alias the moved names back.

4 data tables are SHARED with the live poison/elixir/combat systems that stay
(VAARNISH_POISONS, VAARNISH_ELIXIRS, MELEE_WEAPONS, RANGED_WEAPONS) + the helper
_stamp_slots_uses — these stay defined in server.py and are INJECTED into
generators.py via register_generators(srv) (by-reference; never reassigned, so safe).

Load order: the import+alias-back goes BEFORE the content_forge registration (which
references _roll_exotica by name); register_generators() goes AFTER the session_tools
registration (by which point all injected names are defined). Idempotent-ish: refuses
to run if generators.py already exists.
"""
import ast
import os
import sys

if os.path.exists("generators.py"):
    sys.exit("ABORT: generators.py already exists — slice 1 has already run.")

MOVE_FUNCS = [
    "_roll_exotica", "_lookup_exotica", "_load_exotica_generator", "_generate_faction",
    "_generate_gift", "_generate_poison", "_generate_codex", "_generate_drug",
    "_elixir_row_for", "_generate_elixir", "_generate_exotica", "_generate_weapon_obj",
    "_render_weapon_markdown", "_generate_weapon", "_lookup_weapon_tag",
    "_generate_armour_obj", "_render_armour_markdown", "_generate_npc", "_lookup_career",
    "_generate_crucible",
]
MOVE_CONSTS = [
    "EXOTICA_TABLE", "_exotica_generator_data", "BASIC_TAGS", "ADVANCED_TAGS",
    "EXOTIC_TAGS", "VAARNISH_DRUGS", "CODEX_APPEARANCES", "HYPERGEOMETRIC_EQUATIONS",
    "CRUCIBLE_QUALITIES", "CRUCIBLE_SHAPES",
]
INJECT = ["VAARNISH_POISONS", "VAARNISH_ELIXIRS", "MELEE_WEAPONS", "RANGED_WEAPONS",
          "_stamp_slots_uses"]

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


# Extract verbatim, in source order, so generators.py reads top-to-bottom sensibly.
moved = sorted(
    [(span(n)[0], "func", name, body_text(n)) for name, n in func_nodes.items()]
    + [(span(n)[0], "const", name, body_text(n)) for name, n in const_nodes.items()]
)

# --- Build generators.py ---
header = '''"""Content generators — decomposition slice 1 (2026-06-17).

Extracted VERBATIM from server.py: the d100/table-driven generators behind the
`generate` and `lookup` tools (exotica, weapons, armour, NPCs, factions, gifts,
poisons, codices, drugs, elixirs, crucibles). The tool DISPATCHERS stay in
server.py and import-and-alias these back; this module never imports server.

Four data tables are shared with the live poison/elixir/combat systems and stay
in server.py — they are injected here via register_generators(srv) at startup,
along with the _stamp_slots_uses helper. Bound to None at import; never reassigned.
"""
import json
import random
from pathlib import Path
from typing import Optional

from pydantic import Field

import weapon_schema as ws
import gifts as _gifts
import factions as _factions
import push_format as _pf
from content_forge import ContentForge
from engine_core import CAMPAIGN_DIR, read_file, write_file, dice
from npc_tables import (
    ANCESTRY_TABLE, MANNER_TABLE, VOICE_TABLE, DRIVE_TABLE,
    SECRET_TABLE, BOND_TABLE, FAITH_TABLE, FACTION_REPUTATION_TABLE,
    NAMES_A, NAMES_B, NAMES_C, NAMES_D, CAREERS_TABLE,
)

# Injected from server.py at registration (shared with poison/elixir/combat — by
# reference, never reassigned). Bound to None until register_generators() runs.
VAARNISH_POISONS = None
VAARNISH_ELIXIRS = None
MELEE_WEAPONS = None
RANGED_WEAPONS = None
_stamp_slots_uses = None
'''

blocks = "\n\n".join(text.rstrip("\n") for _, _, _, text in moved)

register_fn = (
    "\n\n_INJECTED = " + repr(tuple(INJECT)) + "\n\n\n"
    "def register_generators(srv):\n"
    '    """Inject the shared data tables + helper that stay resident in server.py."""\n'
    "    g = globals()\n"
    "    for _name in _INJECTED:\n"
    "        g[_name] = getattr(srv, _name)\n"
)

gen_src = header + "\n\n" + blocks + "\n" + register_fn
open("generators.py", "w", encoding="utf-8").write(gen_src)

# --- Rewrite server.py: remove all moved spans ---
remove = set()
for n in list(func_nodes.values()) + list(const_nodes.values()):
    s, e = span(n)
    remove.update(range(s, e + 1))

# marker at the first removed line so the diff reads intentionally
first_removed = min(remove)
new_lines = []
marker_done = False
for i, line in enumerate(lines, start=1):
    if i in remove:
        if not marker_done:
            new_lines.append(
                "# Content generators (20 funcs + 10 private tables) moved to generators.py\n"
                "# (decomposition slice 1); imported-and-aliased below, before content_forge\n"
                "# registration. Shared tables (VAARNISH_POISONS/ELIXIRS, MELEE/RANGED_WEAPONS)\n"
                "# + _stamp_slots_uses stay here and are injected via register_generators().\n"
            )
            marker_done = True
        continue
    new_lines.append(line)
new_server = "".join(new_lines)

# --- Insert import + alias-back BEFORE content_forge registration ---
ANCHOR_REG = "# Register content_forge now that _roll_encounter_table, _roll_reaction, _roll_exotica are defined\n"
assert new_server.count(ANCHOR_REG) == 1, "content_forge registration anchor not unique/found"
# Alias back funcs + the immutable data tables so every existing `server.X`
# reference (tests + any caller) keeps resolving. Skip _exotica_generator_data —
# it is a mutable lazy cache reassigned via `global` inside generators, so an
# alias would freeze on the import-time None.
ALIAS_NAMES = MOVE_FUNCS + [c for c in MOVE_CONSTS if c != "_exotica_generator_data"]
alias = (
    "import generators\n"
    "from generators import (\n"
    + "".join(f"    {name},\n" for name in ALIAS_NAMES)
    + ")\n\n"
)
new_server = new_server.replace(ANCHOR_REG, alias + ANCHOR_REG, 1)

# --- Insert register_generators() AFTER session_tools registration ---
ANCHOR_SESS = "session_tools.register_session_tools(mcp, sys.modules[__name__])\n"
assert new_server.count(ANCHOR_SESS) == 1, "session_tools registration anchor not unique/found"
reg_call = (
    ANCHOR_SESS
    + "\n# Slice 1: inject the shared data tables + _stamp_slots_uses into the relocated\n"
    "# generator functions (defined above, shared with poison/elixir/combat systems).\n"
    "generators.register_generators(sys.modules[__name__])\n"
)
new_server = new_server.replace(ANCHOR_SESS, reg_call, 1)

open("server.py", "w", encoding="utf-8").write(new_server)

# --- Report ---
moji_before = src.count("Ã")
moji_after = new_server.count("Ã") + gen_src.count("Ã")
print(f"MOVED {len(MOVE_FUNCS)} funcs + {len(MOVE_CONSTS)} consts to generators.py")
print(f"generators.py: {len(gen_src.splitlines())} lines")
print(f"server.py: {len(lines)} -> {len(new_lines)} lines ({len(lines) - len(new_lines)} removed)")
print(f"mojibake: server+gen before={moji_before} after={moji_after} (net-new={moji_after - moji_before})")
