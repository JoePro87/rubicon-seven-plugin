---
name: dm-design
description: DM-only narrative design brainstorming. Dispatches a subagent to read campaign context, search history, and write design docs. Outputs ONLY "Done." or "Incomplete — [reason]" to the player. Use when narrative prep is needed — dungeon design, arc coherence, antagonist integration, prep file updates, or as a quality gate after content-forge. Invoke proactively when gameplay reveals narrative gaps, timeline questions, or design surfaces that need stitching. Also auto-triggers after content-forge generates ARC content at any scale (location, vault, or region); optional/offered for discovery content.
user-invocable: true
allowed-tools: Read, Agent, mcp__rubicon-seven__session_mode
---

# DM Design — Subagent Dispatch

You are performing DM-only narrative design work. A fresh subagent handles all design to prevent spoiler leakage. The main context never sees design content.

## Step 1: Enable Maintenance Mode

Design work generates meta responses that trigger unnecessary check_canon calls. Bypass enforcement:

```
session_mode(action="maintenance_on")
```

## Step 2: Parse Topic

Extract the design topic from the player's invocation. Examples:
- `/dm-design <location> prep update` → TOPIC: <location> prep update
- `/dm-design stitch <arc name> arc` → TOPIC: stitch <arc name> arc
- `/dm-design content-forge review` → TOPIC: content-forge quality gate
- (auto-triggered after content-forge) → TOPIC: content-forge quality gate for [generated content name]

## Step 3: Read Subagent Prompt

Read the file `dm-design-agent-prompt.md` (in this skill's own directory — the base directory named when this skill loads) — this contains the full methodology for the subagent.

## Step 4: Dispatch Subagent

Spawn a general-purpose Agent with:
- **prompt:** The full contents of `dm-design-agent-prompt.md`, with the topic inserted at the top: `TOPIC: [extracted topic]`
- **mode:** `bypassPermissions` (it needs to read campaign files, call MCP tools, and write design docs)
- **model:** `opus` (hardcoded — design work runs on the most capable available model)
- **description:** "DM narrative design agent"

Tell the player: "Design work dispatched."

## Step 5: Receive and Relay

The subagent returns ONLY one of:
- `"Done."` — design work complete, written to disk
- `"Incomplete — [one neutral sentence]."` — blocked on something, needs player input

**YOUR ONLY PERMITTED RESPONSE TO THE PLAYER IS TO REPEAT THE SUBAGENT'S RETURN VERBATIM.**

Do not elaborate. Do not summarize. Do not describe what the subagent did. Do not name files that were modified. Do not list findings. The subagent wrote everything to disk. The player is the PC. The DM keeps secrets.

If the return is "Incomplete," relay the neutral question. Wait for the player's answer. Then resume the subagent with their input via SendMessage.

## Step 6: Restore Gameplay Mode

After relaying the result:

```
session_mode(action="maintenance_off")
```

## Important Notes

- The subagent has fresh context and full MCP tool access — it does its own searching and verification
- Do NOT read any files the subagent wrote — you do not need to know what it produced
- Do NOT try to verify the subagent's work yourself — the methodology has its own review phase
- If the subagent fails, you can retry by dispatching a new one with the same topic
- The subagent is read-only on gameplay state (no advance_day, no character stat changes, no combat) — it writes only to DM-only design files
