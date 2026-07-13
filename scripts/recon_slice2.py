import ast

MOVE_FUNCS = [
    # toxin
    "_toxin_susceptible_enemy","_toxin_susceptible_pc","_toxin_resolve","_toxin_get",
    "_toxin_set","_toxin_save_dc","_toxin_enemy_save","_toxin_incur","_toxin_tick",
    "_toxin_cure","_toxin_dispatch","_toxin_die_from_dice","_toxin_attack_reroute",
    # poison
    "_poison_record","_poison_immune","_poison_enemy_save","_poison_current_day",
    "_poison_death","_poison_resolve_effect",
    # usage
    "_usage_to_chain","_usage_to_ammo","_usage_applies","_usage_is_parasitic",
    "_usage_is_fungal","_usage_is_expended","_usage_ammo_max","_usage_resolve",
    "_usage_get","_usage_set","_usage_carried_ammo","_usage_deplete_roll",
    "_usage_feed","_usage_reload","_usage_dispatch",
    # item
    "_broken_item_msg","_item_depletes","_item_resolve","_item_use",
]
MOVE_CONSTS = ["_NON_BIOLOGICAL_PC_SPECIES","POISON_SAVE_TN"]

src = open("server.py", encoding="utf-8").read()
tree = ast.parse(src)

mod_funcs, mod_assigns, mod_imports = set(), set(), set()
for n in tree.body:
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): mod_funcs.add(n.name)
    elif isinstance(n,ast.ClassDef): mod_funcs.add(n.name)
    elif isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name): mod_assigns.add(t.id)
    elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name):
        mod_assigns.add(n.target.id)
    elif isinstance(n,(ast.Import,ast.ImportFrom)):
        for a in n.names: mod_imports.add(a.asname or a.name.split(".")[0])

move_set = set(MOVE_FUNCS)|set(MOVE_CONSTS)
mover_nodes = [n for n in tree.body
               if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS]

used_names, used_mods = set(), set()
for node in mover_nodes:
    for sub in ast.walk(node):
        if isinstance(sub,ast.Name) and isinstance(sub.ctx,ast.Load):
            used_names.add(sub.id)
        if isinstance(sub,ast.Attribute) and isinstance(sub.value,ast.Name):
            used_mods.add(sub.value.id)

dep_funcs = sorted((used_names & mod_funcs) - move_set)
dep_consts = sorted((used_names & mod_assigns) - move_set)
dep_mods   = sorted(used_mods & mod_imports)

# which movers are referenced by STAYING code (need alias-back)?
staying_src_nodes = [n for n in tree.body
                     if not (isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in MOVE_FUNCS)]
staying_used=set()
for node in staying_src_nodes:
    for sub in ast.walk(node):
        if isinstance(sub,ast.Name) and isinstance(sub.ctx,ast.Load):
            staying_used.add(sub.id)
alias_back = sorted(move_set & staying_used)

print("=== OUTGOING: server functions the movers call (stay in server) ===")
for f in dep_funcs: print(" ", f)
print("\n=== OUTGOING: server module-level constants/vars the movers read ===")
for c in dep_consts: print(" ", c)
print("\n=== module aliases referenced (need import in substances.py) ===")
for m in dep_mods: print(" ", m)
print("\n=== movers referenced by STAYING code (must alias back) ===")
for a in alias_back: print(" ", a)
