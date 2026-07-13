"""Decomposition slice 3 — extract the cybernetic + gift helpers into cyber_gifts.py.

VERBATIM AST extraction (server.py mojibake makes hand-edits hazardous). Moves the
7 cybernetic/gift helper functions out of server.py into a new cyber_gifts.py. The
`cybernetic` and `gift` TOOL dispatchers stay in server.py and import-and-alias the
moved names back.

SEAM HANDLING (recon: scripts/recon_slice3.py) —
  * No server-resident data tables to move (gift data lives in the already-extracted
    gifts.py, imported here as _gifts). No constants. NO mover-on-mover fault line:
    none of the 7 movers is monkeypatched and no helper calls another helper, so the
    tests need ZERO changes.
  * Movers call 5 cross-module functions that STAY (server/engine_core): _save_game_state,
    _load_characters, _save_single_character, _find_character, _calculate_slots — several
    heavily monkeypatched on `server`. A by-reference inject would FREEZE those bindings
    and bypass the patches, so each gets a call-time DELEGATING SHIM that resolves on the
    live server module (bound by register_cyber_gifts) — patch-transparent, zero churn.
  * We do NOT `import server`: under `python server.py` the server runs as __main__, and
    a fresh `import server` would re-execute it as a second module and deadlock the
    alias-back (the slice-2 boot bug). register_cyber_gifts(srv) hands us the live module.
  * GAME_STATE is the engine_core by-reference singleton, imported as server does.

Idempotent-ish: refuses to run if cyber_gifts.py already exists.
"""
import ast
import os
import sys

if os.path.exists("cyber_gifts.py"):
    sys.exit("ABORT: cyber_gifts.py already exists — slice 3 has already run.")

MOVE_FUNCS = [
    "_cybernetic_install", "_cybernetic_remove", "_cybernetic_list",
    "_gift_add", "_gift_remove", "_gift_calculate_cost", "_gleam_check_impl",
]
MOVE_CONSTS = []

# Cross-module functions the movers call that stay in server.py / engine_core. Each
# gets a call-time delegating shim to the live server module (patch-transparent).
DELEGATES = [
    "_save_game_state", "_load_characters", "_save_single_character",
    "_find_character", "_calculate_slots",
]

src = open("server.py", encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

func_nodes, const_nodes = {}, {}
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS:
        func_nodes[n.name] = n
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id in MOVE_CONSTS:
                const_nodes[t.id] = n

missing_f = set(MOVE_FUNCS) - set(func_nodes)
assert not missing_f, f"missing funcs: {missing_f}"


def span(node):
    start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
    return start, node.end_lineno


def body_text(node):
    s, e = span(node)
    return "".join(lines[s - 1:e])


moved = sorted(
    [(span(n)[0], "func", name, body_text(n)) for name, n in func_nodes.items()]
    + [(span(n)[0], "const", name, body_text(n)) for name, n in const_nodes.items()]
)

# --- Build cyber_gifts.py ---
delegates_repr = "(\n" + "".join(f'    "{n}",\n' for n in DELEGATES) + ")"
header = '''"""Cybernetics & Gifts — decomposition slice 3 (2026-06-17).

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
_DELEGATES = ''' + delegates_repr + '''
for _n in _DELEGATES:
    globals()[_n] = _make_delegate(_n)
del _n
'''

blocks = "\n\n".join(text.rstrip("\n") for _, _, _, text in moved)

register_fn = (
    "\n\n\ndef register_cyber_gifts(srv):\n"
    '    """Bind the live running server module so the delegates can resolve on it."""\n'
    "    global _server\n"
    "    _server = srv\n"
)

cg_src = header + "\n\n" + blocks + "\n" + register_fn
open("cyber_gifts.py", "w", encoding="utf-8").write(cg_src)

# --- Rewrite server.py: remove moved spans, insert import+alias-back at the site ---
remove = set()
for n in list(func_nodes.values()) + list(const_nodes.values()):
    s, e = span(n)
    remove.update(range(s, e + 1))

ALIAS_NAMES = MOVE_FUNCS + MOVE_CONSTS
alias_block = (
    "# Cybernetic + gift helpers (7 funcs) moved to cyber_gifts.py (decomposition\n"
    "# slice 3); imported-and-aliased back here. The cybernetic/gift tool dispatchers\n"
    "# stay and call these. register_cyber_gifts() (below) binds the live module.\n"
    "import cyber_gifts\n"
    "from cyber_gifts import (\n"
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

# --- Insert register_cyber_gifts() AFTER session_tools registration ---
ANCHOR_SESS = "session_tools.register_session_tools(mcp, sys.modules[__name__])\n"
assert new_server.count(ANCHOR_SESS) == 1, "session_tools registration anchor not unique/found"
reg_call = (
    ANCHOR_SESS
    + "\n# Slice 3: bind the live server module into the relocated cyber/gift helpers.\n"
    "cyber_gifts.register_cyber_gifts(sys.modules[__name__])\n"
)
new_server = new_server.replace(ANCHOR_SESS, reg_call, 1)

open("server.py", "w", encoding="utf-8").write(new_server)

# --- Report ---
moji_before = src.count("Ã")
moji_after = new_server.count("Ã") + cg_src.count("Ã")
print(f"MOVED {len(MOVE_FUNCS)} funcs + {len(MOVE_CONSTS)} consts to cyber_gifts.py")
print(f"cyber_gifts.py: {len(cg_src.splitlines())} lines")
print(f"server.py: {len(lines)} -> {len(new_lines)} lines ({len(lines) - len(new_lines)} removed)")
print(f"mojibake: server+cg before={moji_before} after={moji_after} (net-new={moji_after - moji_before})")
