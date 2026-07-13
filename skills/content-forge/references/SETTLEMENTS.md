# Settlements — delegate to the engine

Settlements are generated from the **certified Crimson Hound tables**. Call the engine and
weave the result into fiction. (A light generative surface — characterful, weird places fast,
not a settlement simulation.)

## Generate a settlement

```
roll(action="settlement")
```

Returns a book-faithful profile, each facet a d20 on the certified tables:

- **Government** — an *adjective* + a *form* (e.g. "Bloodthirsty Synarchism"), with **faith
  rolled separately** (the book's method).
- **Values** — what it **praises**, **despises**, and **lacks**. The despises column mirrors
  the praises — *what the town loves, its rivals hate.* That tension is the roleplay hook.
- **Asset** — a concrete landmark/resource with book detail (Matter Fabricator, Oracle's
  Abode, Orbital Defence Cannon, Pleasure Gardens…).
- **Problem** — a live tension (Power Struggle, Unquiet Dead, Unicorn Infestation, Quantum
  Daemon Curse, Cacklemaw Extortion…).

## When the party RETURNS to a settlement

Crimson Hound has a **Changes** table (Argument, Death of a Leader, New Prophet, New Romance,
Quantum Daemon…) for what's shifted since the last visit — and the engine carries it (table
`settlement_change`, certified). Surface a change as a **hook**, not a status readout: it lands
in a scene. (This ties into the world-spine/heartbeat — settlements *live* between visits.)

## Sub-locations within/near a settlement

These are content-forge's own generators, also engine-served — don't roll them from a table here:

- **Hegemony Protectorate** → `roll(action="location", location_type="hegemony_protectorate")`
- **Oracle's Sanctum** → `roll(action="location", location_type="oracle_sanctum")`

## How to use it — a generative surface, not a sim

Roll, then *write the place*: let the government's adjective colour its mood, the despised
thing create friction, the problem seed a hook, the asset give it a reason to exist. Don't
track settlement economies or simulate politics — the weird specifics on the tables do the
work; you turn them into a place that feels lived-in.
