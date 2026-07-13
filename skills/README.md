# Skills — live in the campaign repo, not here

**Decided 2026-06-15.** Skills for Rubicon Seven live in the **campaign repo**
(`rubicon-seven-campaign`), which is the single home. This repo is the engine —
the "boiler room" where the MCP tools are built and tested. It does **not** carry
gameplay skills.

**Why:** keeping skill copies in both repos created copy-drift — the same skill
existed here *and* in the campaign repo and the two versions fell out of sync
(e.g. `content-forge` was a stale 7-file subset here vs. the live 11-file version
in the campaign repo). One home = no drift. (This reverses the 2026-06-10
"canonical-here, deploy-downstream" migration, which was the source of the drift.)

## Where the skills live now

| Skill | Home |
|-------|------|
| `content-forge` | campaign repo `content-forge/` |
| `session-start` | campaign repo `.claude/skills/session-start/` |
| `session-end` | campaign repo `.claude/skills/session-end/` |
| `dm-design` | campaign repo `.claude/skills/dm-design/` |
| `vaarn-portrait` | dropped 2026-06-15 (was engine-only; recoverable from git history if ever wanted) |

## Open follow-ups (tracked, not yet done)

- **A skill→tool-name guard in the campaign repo.** This repo's
  `tests/test_skill_tool_names.py` now only sees this README (no skills remain here),
  so the real guarding has to happen in the *campaign* repo where the skills live —
  it needs to be built there, able to see both the skills and the engine's live tool
  list. Until then, the campaign skill/tool wiring is unguarded (this is what the
  consolidation session exposed).
- **Re-point the campaign skills** to the consolidated tool names (the 64→~31 tool
  merge retired names like `condition`/`disease`/`read_file_section`/etc.).

The DM output style similarly lives in the campaign repo's
`.claude/output-styles/`, selected via `outputStyle` in that repo's settings.
