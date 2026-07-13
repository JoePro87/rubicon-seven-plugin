import ast, builtins
SECTION_LO, SECTION_HI = 9342, 12505      # first helper after character() .. last char helper
MUST_STAY = {"_roll_cacogen_mutation"}     # map: keep re-exported on server

src=open("server.py",encoding="utf-8").read(); tree=ast.parse(src)

# Candidate move set = all top-level funcs + consts whose def starts in the section, minus MUST_STAY
move_funcs, move_consts = [], []
for n in tree.body:
    s = getattr(n,"lineno",0)
    if SECTION_LO <= s <= SECTION_HI:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name not in MUST_STAY:
            move_funcs.append(n.name)
        elif isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name): move_consts.append(t.id)
move_set=set(move_funcs)|set(move_consts)

mod_funcs,mod_assigns,mod_imports=set(),set(),set()
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): mod_funcs.add(n.name)
    elif isinstance(n,ast.ClassDef): mod_funcs.add(n.name)
    elif isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name): mod_assigns.add(t.id)
    elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name): mod_assigns.add(n.target.id)
    elif isinstance(n,(ast.Import,ast.ImportFrom)):
        for a in n.names: mod_imports.add(a.asname or a.name.split(".")[0])

movers=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in move_set]
bi=set(dir(builtins))
def free(fn):
    loc=set()
    for s in ast.walk(fn):
        if isinstance(s,ast.arg): loc.add(s.arg)
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Store): loc.add(s.id)
        if isinstance(s,ast.ExceptHandler) and s.name: loc.add(s.name)
        if isinstance(s,(ast.FunctionDef,ast.AsyncFunctionDef)) and s is not fn: loc.add(s.name)
    return {s.id for s in ast.walk(fn) if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Load)}-loc
allfree=set()
for n in movers: allfree|=free(n)
fr=allfree-move_set-bi
used_mods=set()
for n in movers:
    for s in ast.walk(n):
        if isinstance(s,ast.Attribute) and isinstance(s.value,ast.Name): used_mods.add(s.value.id)
# movers referenced by STAYING code
staying=[n for n in tree.body if not (isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in move_set)]
su=set()
for n in staying:
    for s in ast.walk(n):
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Load): su.add(s.id)

print(f"MOVE SET: {len(move_funcs)} funcs + {len(move_consts)} consts")
print("  consts:", sorted(move_consts))
print("DELEGATE (server-defined funcs movers call, stay):", sorted(fr&mod_funcs))
print("imported names used bare:", sorted(fr&mod_imports))
print("module-level consts/vars read (stay/inject):", sorted(fr&mod_assigns))
print("module aliases (import):", sorted(used_mods&mod_imports))
print("UNKNOWN free names:", sorted(fr-mod_funcs-mod_imports-mod_assigns))
print(f"movers referenced by STAYING code (alias back): {len(move_set&su)} ->", sorted(move_set&su))
