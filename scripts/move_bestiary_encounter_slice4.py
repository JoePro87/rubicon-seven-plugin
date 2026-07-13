"""Decomposition slice 4 — extract bestiary + encounter/reaction helpers.

VERBATIM AST extraction. Moves 7 bestiary/encounter/reaction helpers out of server.py
into bestiary_encounter.py. The `lookup`/`test_dice` tools and the content_forge
registration stay in server.py and import-and-alias the moved names back.

SEAM HANDLING (recon: scripts/recon_slice4.py) —
  * content_forge registration (server.py, after the moved span) passes
    _roll_encounter_table / _roll_reaction / _roll_reaction_for_character BY REFERENCE
    to register_content_forge_tools. The alias-back sits at the removal site, BEFORE
    that registration, so the names resolve (same ordering slice 1 relied on for
    _roll_exotica). The functions are only stored at registration, called at tool-time.
  * rulebook_system is server's module-level VARIABLE — the instance returned by
    register_rulebook_tools (its _cache is an INSTANCE attribute). Bestiary lookups read
    rulebook_system._cache and tests do `setattr(server.rulebook_system, "_cache", fix)`
    (mutating the attribute on that shared instance, never rebinding the name). So we
    INJECT rulebook_system by reference via register_bestiary_encounter(): same instance,
    test _cache mutations stay visible.
  * Movers call 5 server-resident functions (_load_characters, _find_character,
    _faction_clamp, _load_factions, _resolve_resistance_profile) — reached via call-time
    DELEGATING SHIMS bound to the live server module (patch-transparent; _load_characters
    is patched 93x).
  * dice (engine_core singleton) is patched in tests only by ATTRIBUTE mutation
    (`setattr(server.dice, "d20", ...)`) on the shared object, so a plain import is safe.
    Field (pydantic), _ancestries, _factions imported directly (never rebind-patched).
  * FAULT LINE: _faction_rep (moved) is called by _reaction_modifiers (moved) via a
    bare mover->mover edge AND patched on server (test_reaction.py) — dual-patched there.
  * We do NOT `import server` (the slice-2 __main__ boot bug); register_bestiary_encounter
    hands us the live running module.

Idempotent-ish: refuses to run if bestiary_encounter.py already exists.
"""
import ast
import os
import sys

if os.path.exists("bestiary_encounter.py"):
    sys.exit("ABORT: bestiary_encounter.py already exists — slice 4 has already run.")

MOVE_FUNCS = [
    "_get_bestiary_entry", "_lookup_creature_stats", "_roll_encounter_table",
    "_roll_reaction", "_faction_rep", "_reaction_modifiers", "_roll_reaction_for_character",
]
MOVE_CONSTS = []

# Server-resident functions the movers call -> call-time delegating shims.
DELEGATES = [
    "_load_characters", "_find_character", "_faction_clamp",
    "_load_factions", "_resolve_resistance_profile",
]
# Server-resident object injected by reference (never rebound; tests mutate its attrs).
INJECT = ["rulebook_system"]

src = open("server.py", encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

func_nodes = {}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS:
        func_nodes[n.name] = n
missing_f = set(MOVE_FUNCS) - set(func_nodes)
assert not missing_f, f"missing funcs: {missing_f}"


def span(node):
    start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
    return start, node.end_lineno


def body_text(node):
    s, e = span(node)
    return "".join(lines[s - 1:e])


moved = sorted((span(n)[0], name, body_text(n)) for name, n in func_nodes.items())

# --- Build bestiary_encounter.py ---
delegates_repr = "(\n" + "".join(f'    "{n}",\n' for n in DELEGATES) + ")"
inject_repr = "(" + "".join(f'"{n}", ' for n in INJECT).rstrip(", ") + ",)" if INJECT else "()"
header = '''"""Bestiary & Encounter — decomposition slice 4 (2026-06-17).

Extracted VERBATIM from server.py: bestiary lookups, the encounter table roll, and
the reaction roll/modifier helpers. The `lookup`/`test_dice` tools and the
content_forge registration stay in server.py and import-and-alias these back.

Cross-module persistence/faction functions the movers call STAY in server.py and are
reached via call-time DELEGATING SHIMS (_DELEGATES) bound to the live server module by
register_bestiary_encounter — patch-transparent. rulebook_system (the instance whose
_cache tests mutate) is injected by reference. dice is the engine_core singleton
(tests attribute-patch it, so a plain import is safe); gift/faction/ancestry data come
from their already-extracted modules.
"""
import json
import random

from pydantic import Field
from engine_core import dice
import ancestries as _ancestries
import factions as _factions


# The running server module, supplied by register_bestiary_encounter() at startup.
# We do NOT `import server`: under `python server.py` the server runs as `__main__`,
# so a fresh `import server` would re-execute it as a second module and deadlock the
# alias-back (the slice-2 boot bug). Registration hands us the live running module.
_server = None

# Injected by reference at registration (server's rulebook_system instance; never
# rebound, so the binding can't go stale and tests' _cache mutations stay visible).
rulebook_system = None


def _make_delegate(_name):
    """Build a call-time delegate to the running server.<_name> (keeps monkeypatches live)."""
    def _delegate(*args, **kwargs):
        return getattr(_server, _name)(*args, **kwargs)
    _delegate.__name__ = _name
    _delegate.__qualname__ = _name
    return _delegate


_DELEGATES = ''' + delegates_repr + '''
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n
'''

blocks = "\n\n".join(text.rstrip("\n") for _, _, text in moved)

register_fn = (
    "\n\n\n_INJECTED = " + inject_repr + "\n\n\n"
    "def register_bestiary_encounter(srv):\n"
    '    """Bind the live server module + inject the rulebook_system instance."""\n'
    "    global _server\n"
    "    _server = srv\n"
    "    g = globals()\n"
    "    for _name in _INJECTED:\n"
    "        g[_name] = getattr(srv, _name)\n"
)

be_src = header + "\n\n" + blocks + "\n" + register_fn
open("bestiary_encounter.py", "w", encoding="utf-8").write(be_src)

# --- Rewrite server.py: remove moved spans, insert import+alias-back at the site ---
remove = set()
for n in func_nodes.values():
    s, e = span(n)
    remove.update(range(s, e + 1))

ALIAS_NAMES = MOVE_FUNCS + MOVE_CONSTS
alias_block = (
    "# Bestiary + encounter/reaction helpers (7 funcs) moved to bestiary_encounter.py\n"
    "# (decomposition slice 4); imported-and-aliased back here BEFORE the content_forge\n"
    "# registration (which passes _roll_encounter_table/_roll_reaction/\n"
    "# _roll_reaction_for_character by reference). register_bestiary_encounter() (below)\n"
    "# binds the live module + injects rulebook_system.\n"
    "import bestiary_encounter\n"
    "from bestiary_encounter import (\n"
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

# --- Insert register_bestiary_encounter() AFTER session_tools registration ---
ANCHOR_SESS = "session_tools.register_session_tools(mcp, sys.modules[__name__])\n"
assert new_server.count(ANCHOR_SESS) == 1, "session_tools registration anchor not unique/found"
reg_call = (
    ANCHOR_SESS
    + "\n# Slice 4: bind the live server module + inject rulebook_system into the\n"
    "# relocated bestiary/encounter helpers.\n"
    "bestiary_encounter.register_bestiary_encounter(sys.modules[__name__])\n"
)
new_server = new_server.replace(ANCHOR_SESS, reg_call, 1)

open("server.py", "w", encoding="utf-8").write(new_server)

# --- Report ---
moji_before = src.count("Ã")
moji_after = new_server.count("Ã") + be_src.count("Ã")
print(f"MOVED {len(MOVE_FUNCS)} funcs to bestiary_encounter.py")
print(f"bestiary_encounter.py: {len(be_src.splitlines())} lines")
print(f"server.py: {len(lines)} -> {len(new_lines)} lines ({len(lines) - len(new_lines)} removed)")
print(f"mojibake: server+be before={moji_before} after={moji_after} (net-new={moji_after - moji_before})")
