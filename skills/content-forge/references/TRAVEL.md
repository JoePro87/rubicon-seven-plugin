# Travel — the unmapped desert (delegate the rolls to the engine)

Crimson Hound travel is **deliberately unmapped**. That vagueness *is* the vibe — Vaarn
resists the hex-grid/spreadsheet treatment. Do **not** track miles, hexes, or navigation
DCs. Narrate the journey; let the engine own the rolls.

## The model (what's true in the book)

- **Distance is measured in DAYS, estimated by NPCs**, not mapped. On foot is the baseline;
  **a vehicle halves the days.** Rough route lengths: close = **d6** days, moderate = **2d6**,
  far = **3d6** (the engine's region generation sets these). There is no hex grid and no mileage.
- **Getting lost:** assume the party are competent navigators — they **do not get lost** while
  they can see sun and stars. Only when that's impossible (e.g. a sandstorm) do they lose the
  way: **add d6 days** to the trip. No INT save, no secret-direction roll, no DC.
- **Encounter checks:** **d6 once during the travel day and once at night** — **1 = Encounter,
  2 = Omen, 3–6 = nothing.** (Not a four-watch schedule.) An Omen is a *sign* of what's near,
  not the thing itself — surface it as fiction.

## The rolls — call the engine

- **Foraging** → `supply(action="forage")` — the certified **d100 Desert Foraging** table
  (Lumenrot pools, vending machines, Sky Whales — the real one). Not a d30; no terrain modifiers.
- **Weather** → `roll(action="weather")` — see `references/WEATHER.md`.
- **Encounters** → the regional encounter roll (`roll(action="encounter", table="<region>")`).
- **Route hazards** → the region's certified **d20** route-hazard column (region generation / `rulebook`).

## How to use it — a journey, not a sim

Travel is **passage and consequence**, not bookkeeping. Mark the days, narrate the crossing,
and let things *land* when they should: a Heatwave pressing on the water count, a Rain day as a
bounty, an Omen at dusk that seeds the next scene. Don't run a per-hex weather/forage/navigation
ledger — the world feels vast and alive precisely because you're *not* mapping it.

*(There are no Crimson Hound tables for "water source quality," "camp encounters," or "travel
complications" — those were fabricated and removed. If a journey needs drama, surface it from
weather, an Omen, or a region hazard, not an invented table.)*
