import ast, builtins

# Re-extract from the ORIGINAL server (pre-move) via git show to be safe? No —
# substances.py now holds the movers verbatim. Analyze substances.py movers directly.
sub = open("substances.py", encoding="utf-8").read()
tree = ast.parse(sub)

MOVERS = set()
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): MOVERS.add(n.name)

# names substances already provides at module level (imports, shim, injected stubs, consts)
provided = set(MOVERS)
for n in tree.body:
    if isinstance(n,(ast.Import,ast.ImportFrom)):
        for a in n.names: provided.add(a.asname or a.name.split(".")[0])
    elif isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name): provided.add(t.id)
    elif isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
        provided.add(n.name)

builtin_names = set(dir(builtins))

def free_names(fn):
    locals_=set()
    for sub_ in ast.walk(fn):
        if isinstance(sub_,ast.arg): locals_.add(sub_.arg)
        if isinstance(sub_,ast.Assign):
            for t in sub_.targets:
                if isinstance(t,ast.Name): locals_.add(t.id)
        if isinstance(sub_,(ast.comprehension,)):
            pass
        if isinstance(sub_,ast.Name) and isinstance(sub_.ctx,ast.Store):
            locals_.add(sub_.id)
        if isinstance(sub_,(ast.FunctionDef,ast.AsyncFunctionDef)) and sub_ is not fn:
            locals_.add(sub_.name)
    used=set()
    for sub_ in ast.walk(fn):
        if isinstance(sub_,ast.Name) and isinstance(sub_.ctx,ast.Load):
            used.add(sub_.id)
    return used - locals_

allfree=set()
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
        allfree |= free_names(n)

unresolved = sorted(allfree - provided - builtin_names)
print("=== FREE names in movers NOT provided by substances.py and NOT builtins ===")
for u in unresolved: print(" ", u)
