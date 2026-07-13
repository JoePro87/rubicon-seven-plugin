---
name: maintenance
description: Toggle maintenance mode to bypass check_canon enforcement and tool reminders. Use when doing file edits, reviewing campaign state, or other non-gameplay work.
user-invocable: true
allowed-tools: Read, Write, mcp__rubicon-seven__session_mode
---

# Maintenance Mode

You are entering maintenance mode for this Vaults of Vaarn campaign. This bypasses the check_canon enforcement and tool reminder hook that normally run on every turn.

## What This Does

Maintenance mode is for non-gameplay work:
- Editing campaign files
- Reviewing/fixing state
- Prep file work
- System maintenance

**It does NOT disable the MCP tools** — you can still use them if needed. It just stops the automatic check_canon requirement and tool reminders that normally fire.

## Step 1: Enable Bypass

Call the engine tool:

```
session_mode(action="maintenance_on")
```

This mutes check_canon enforcement, prose coaching, and the Haiku prose observer. (Engine-owned and cross-platform — no shell, no file paths.)

## Step 2: Confirm

After running the command, tell the player:

> **Maintenance mode active.**
>
> I can now help with file edits, state review, and prep work without the check_canon requirement or tool reminders.
>
> To return to gameplay mode, use `/session-start` or just say "back to gameplay".

## Returning to Gameplay

When the player is done with maintenance and wants to resume play:

1. Call `/session-start` (resets flags automatically)
2. OR disable manually:

```
session_mode(action="maintenance_off")
```

This restores normal check_canon enforcement and the prose observer, and clears the prose-catch counters for a fresh session.

## Important Notes

- Maintenance mode does NOT persist across sessions
- /session-start automatically clears all three flags (`maintenance_mode`, `skip_canon_enforcement`, `skip_semantic_observer`) plus the prose-catch counters
- You can still call check_canon manually if you need context
- The MCP tools remain fully functional
