# Generating CLAUDE.md and the output style from the tone answers

How the Step-1 tone conversation fills the two templates. Fill the placeholders, strip
every `<!-- ... -->` comment and `"//"` key, then write the files. Keep all tool/protocol
scaffolding verbatim — only the tone sections are authored.

## Files written
- `assets/CLAUDE.md.template` → `<CAMPAIGN_DIR>/CLAUDE.md`
- `assets/output-style.template` → `<CAMPAIGN_DIR>/.claude/output-styles/rubicon-seven-dm.md`
  (then `settings.json` sets `"outputStyle": "Rubicon Seven DM"`)

## Placeholder map (CLAUDE.md.template)

| Placeholder | Source answer | Notes |
|-------------|---------------|-------|
| `{{CAMPAIGN_TITLE}}` | optional name, else "Vaults of Vaarn" | one short line |
| `{{MOOD}}` | mood answer | grim / wondrous / playful / horror |
| `{{LETHALITY}}` | lethality answer | deadly-consequential vs forgiving-heroic |
| `{{PACING_FOCUS}}` | pacing/focus answer | exploration, survival, drama, combat |
| `{{CONTENT_BOUNDARIES}}` | boundaries answer | verbatim; if none, write "nothing flagged" |
| `{{PACING_RHYTHM}}` | derived from pacing answer | one sentence on default scene cadence |

## Placeholder map (output-style.template)

| Placeholder | Source | Notes |
|-------------|--------|-------|
| `{{VOICE_MOOD_CLAUSE}}` | mood answer | one phrase inside the description string |
| `{{TONE_DIRECTIVE}}` | mood + lethality | 1-2 standing sentences to the voice |

## Example fills

**Mood = "grim and melancholy", lethality = "deadly":**
- `{{MOOD}}` → "Grim, melancholy, dying-earth. Beauty is broken or repurposed; the world is indifferent."
- `{{LETHALITY}}` → "Deadly and consequential. Death is on the table; do not soften outcomes to protect the player."
- `{{VOICE_MOOD_CLAUSE}}` → "literary science-fantasy, dying-earth, weird and melancholy, never heroic"
- `{{TONE_DIRECTIVE}}` → "Hold the dying-earth melancholy. Danger is real and named; consequences land, including death, and you do not flinch from them."

**Mood = "wondrous and strange", lethality = "forgiving":**
- `{{MOOD}}` → "Wondrous and strange. The world is vast and full of marvels half-understood; awe over despair."
- `{{LETHALITY}}` → "Forgiving and heroic. Setbacks bruise but rarely kill; let the player feel capable and the world feel survivable."
- `{{VOICE_MOOD_CLAUSE}}` → "wondrous and strange science-fantasy, vast and melancholy, full of broken marvels"
- `{{TONE_DIRECTIVE}}` → "Lead with wonder. Threats threaten but seldom end the story; give the player room to be the hero of their own strangeness."

**Mood = "darkly playful":**
- `{{VOICE_MOOD_CLAUSE}}` → "darkly playful science-fantasy, the absurd beside the sacred, melancholy with a grin"

**Pacing answers → `{{PACING_FOCUS}}` and `{{PACING_RHYTHM}}`:**
- exploration/mystery → focus "Exploration and mystery — ruins, secrets, the slow reveal."; rhythm "linger in discovery; reward looking closely; let mysteries sit unresolved."
- survival/scarcity → focus "Survival and scarcity — water, supplies, the desert's cost."; rhythm "make resources felt; every rest and ration is a decision."
- character drama → focus "Character drama — relationships, NPCs, the inner weather."; rhythm "give scenes room to breathe; quiet beats earn their length."
- combat → focus "Combat and danger — kinetic, decisive encounters."; rhythm "keep encounters sharp and consequential; don't drag the build-up."

## Tripwires (filled AFTER Step 3)
The TRIPWIRES table starts with only its header + placeholder row. After the character is
rolled, append one row per character-specific fact the DM must never get wrong, derived from
ancestry/mutations/gifts. Format: `| <the wrong assumption> | <the correct fact> |`. Examples:
- Neobloom (photosynthetic) → `| PC offered food | NEVER eats (photosynthesis) |`
- Gliding mutation → `| PC flies | GLIDES — needs altitude, must climb to glide again |`
- Synth → `| PC eats/sleeps | synth: no food/water/sleep; immune poison/disease |`
If the rolled character has no such facts, leave the placeholder row as-is.

## Prose coaching
The Step-1 prose-coaching choice does NOT touch these two files — it is recorded only in
`settings.json` (add/omit the `phrase_reminder.py` UserPromptSubmit hook). Default OFF.
