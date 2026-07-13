# Weather — delegate to the engine

**The engine owns weather. Do not roll it from a table here.** Crimson Hound weather is
a **d6 hex-chart DRIFT** (a marker walks a small chart, one d6 move per desert day),
not a per-day outcome roll — so weather has *continuity*, which the engine tracks for you
in `weather_state.json`.

## How to get weather

Call once per desert day (or when the party would notice a change):

```
roll(action="weather")
```

It returns the new condition + its mechanical effect, and remembers the marker position
across days. To force a specific d6 direction (1=NW 2=N 3=NE 4=SE 5=S 6=SW), pass
`specific_roll`.

## The eight conditions (what the engine can return)

Still · Hazy · Dust Storm · Sand Storm · Heatwave · Worm-pollen · Rain · Prismatic Tempest.
The engine returns the exact effect text with the result; the ones that *matter* most:

- **Rain** — a rare bounty: collect **2d6 days** of water rations per member.
- **Heatwave** — **double** water to travel.
- **Worm-pollen** — half speed; the spore-drift is edible (**d4 rations/player**).
- **Sand Storm** — nobody travels; any encounter today is sheltering in the same place. Beam weapons don't work.
- **Dust Storm** — half travel speed; Vigilance at DIS.
- **Prismatic Tempest** — no travel; **3d6 electrical/hour** aboveground.
- **Still / Hazy** — texture, not obstacle.

## How to use it — a generative surface, not a sim

Weather is **flavor + occasional consequence**, never bookkeeping. Surface it in the
fiction — the taste of the air, the colour of the light — and let it *land* only when it
should: Rain as a bounty/celebration, a Tempest as a reason to go to ground, a Heatwave
as quiet pressure on the water count. Don't keep a weather spreadsheet, don't track
per-hex micro-weather, don't invent extra modifiers. The marker drifts; you narrate; the
desert feels alive without anyone doing accounting.

*(There is no "psychic weather," no seasonal/regional weather modifier table, and no
weather-combat rules in Crimson Hound — those were removed. If a scene wants an eerie
psychic phenomenon, author it as a discovery/anomaly, not a weather roll.)*
