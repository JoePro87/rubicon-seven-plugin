import ast, builtins
MOVE_FUNCS = [
    "_get_bestiary_entry","_lookup_creature_stats","_roll_encounter_table",
    "_roll_reaction","_faction_rep","_reaction_modifiers","_roll_reaction_for_character",
]
src=open("server.py",encoding="utf-8").read(); tree=ast.parse(src)
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
move_set=set(MOVE_FUNCS)
movers=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS]
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
staying=[n for n in tree.body if not (isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS)]
su=set()
for n in staying:
    for s in ast.walk(n):
        if isinstance(s,ast.Name) and isinstance(s.ctx,ast.Load): su.add(s.id)
print("DELEGATE? cross-module FUNCS movers call (server-defined):",sorted(fr&mod_funcs))
print("imported names used bare:",sorted(fr&mod_imports))
print("module-level consts/vars read:",sorted(fr&mod_assigns))
print("module aliases (need import):",sorted(used_mods&mod_imports))
print("UNKNOWN free names:",sorted(fr-mod_funcs-mod_imports-mod_assigns))
print("movers referenced by STAYING code (alias back):",sorted(move_set&su))
