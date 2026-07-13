import ast, builtins

MOVE_FUNCS = [
    "_cybernetic_install", "_cybernetic_remove", "_cybernetic_list",
    "_gift_add", "_gift_remove", "_gift_calculate_cost", "_gleam_check_impl",
]
src = open("server.py", encoding="utf-8").read()
tree = ast.parse(src)

# module-level names server provides (defs, classes, assigns, imports)
mod_funcs, mod_assigns, mod_imports = set(), set(), set()
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): mod_funcs.add(n.name)
    elif isinstance(n,ast.ClassDef): mod_funcs.add(n.name)
    elif isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name): mod_assigns.add(t.id)
    elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name): mod_assigns.add(n.target.id)
    elif isinstance(n,(ast.Import,ast.ImportFrom)):
        for a in n.names: mod_imports.add(a.asname or a.name.split(".")[0])

move_set = set(MOVE_FUNCS)
movers = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS]
builtin_names = set(dir(builtins))

def free_names(fn):
    locals_=set()
    for s in ast.walk(fn):
        if isinstance(s,ast.arg): locals_.add(s.arg)
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Store): locals_.add(s.id)
        if isinstance(s,(ast.FunctionDef,ast.AsyncFunctionDef)) and s is not fn: locals_.add(s.name)
    used=set()
    for s in ast.walk(fn):
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Load): used.add(s.id)
    return used-locals_

allfree=set()
for n in movers: allfree |= free_names(n)
free = allfree - move_set - builtin_names

# classify
deps_serverdef = sorted(free & mod_funcs)
deps_imported  = sorted((free & mod_imports))
deps_const     = sorted(free & mod_assigns)
deps_unknown   = sorted(free - mod_funcs - mod_imports - mod_assigns)

# module aliases accessed via attribute
used_mods=set()
for n in movers:
    for s in ast.walk(n):
        if isinstance(s,ast.Attribute) and isinstance(s.value,ast.Name): used_mods.add(s.value.id)
deps_modalias = sorted(used_mods & mod_imports)

# movers referenced by STAYING code (alias-back set)
staying=[n for n in tree.body if not (isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS)]
staying_used=set()
for n in staying:
    for s in ast.walk(n):
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Load): staying_used.add(s.id)
alias_back=sorted(move_set & staying_used)

print("=== cross-module FUNCTIONS the movers call -> DELEGATE (server-defined):"); [print("  ",d) for d in deps_serverdef]
print("=== imported names used bare -> DELEGATE or import:"); [print("  ",d) for d in deps_imported]
print("=== module-level consts/vars read:"); [print("  ",d) for d in deps_const]
print("=== module aliases (need import):"); [print("  ",d) for d in deps_modalias]
print("=== UNKNOWN free names (investigate!):"); [print("  ",d) for d in deps_unknown]
print("=== movers referenced by STAYING code (alias back):"); [print("  ",d) for d in alias_back]
