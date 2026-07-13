#!/usr/bin/env python3
"""
scaffold_campaign.py — THE single source of truth for the blank Day-1 campaign scaffold.

What a fresh Rubicon Seven campaign folder must contain (file contents + folder set) lives
HERE and nowhere else. Two callers share it, so the structure can never drift across them:
  - /vaarn-start Step 2 (setup) runs this as a SCRIPT, before the engine/MCP is connected,
    to create a brand-new campaign folder.
  - scripts/reset_to_base.py IMPORTS these constants to rewrite an existing campaign to blank.

  Standalone:  python scripts/scaffold_campaign.py --dir /path/to/new-campaign
  Importable:  from scaffold_campaign import blank_files, BLANK_DIRS, scaffold, <constants>

Creates only — never wipes. Existing files are skipped (pass --force to overwrite the blank
set). Refuses to run inside the engine repo.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

# ----------------------------------------------------------------------------------
# Blank Day-1 file contents — the ONE definition. (reset_to_base.py imports these.)
# ----------------------------------------------------------------------------------

CURRENT_STATUS = """# CURRENT STATUS - DAY 1

**Last Updated:** (fresh campaign — onboarding in progress)

---

## SCENE STATE (check_canon reads this section)

**Day:** 1
**Location:** (unset — opening scene set during onboarding)
**Present:** (none yet — the player's character is created during onboarding)

**Last 3 Beats:** (none — the campaign has not started)

---

## ACTIVE PREP

**Active Prep:** (none)
"""

MASTER_CONTINUITY = """# MASTER CONTINUITY - CURRENT SESSION

(fresh campaign — no sessions recorded yet)
"""

ANTAGONIST = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 0

---

## ACTIVE THREATS
*Things currently in motion, escalating*

[None yet]

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

[None yet]

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

[None yet]

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

# {today} is filled by blank_files(); double-braces escape the JSON braces for .format().
META_JSON = """{{
  "version": 1,
  "last_updated": "{today}",
  "campaign_day": 1,
  "system": "Vaults of Vaarn",
  "notes": "Ability scores ARE the bonuses (range -10 to +10). Death at -20 HP, all slots filled with wounds, or any ability < -10."
}}
"""

# Empty canon store. Without it, check_canon early-returns "lorebook.json not found"
# and that failure cascades into the save/reindex on first session-end.
LOREBOOK = """{
  "entries": []
}
"""

# Empty NPC roster, so the session-end pipeline's npc_changes have somewhere to land.
NPC_ROSTER = """# NPC ROSTER

*Standing and relationships of NPCs the party has met. The session-end pipeline updates this.*

(no NPCs yet — the roster fills as the player meets people)
"""

# Privacy guard for players who version-control their campaign. The load-bearing line is
# .claude/memories.json (Claude's per-folder personal-memory store — never publish it). The rest
# keeps derived/transient data out of commits.
GITIGNORE = """# Personal / never-publish
.claude/memories.json

# Per-campaign engine runtime state — holds your play history; never publish.
# Glob covers every canon-cache variant (.json/.lock/.tmp/.staging/.pre-backfill).
catch_analytics.json
.canon_distillations*
fabrication_bans.json

# Derived & regenerable (rebuilt by the engine; don't commit)
chroma-db/
__pycache__/
*.pyc
"""

# Folders a fresh campaign needs (the engine/onboarding write into these).
BLANK_DIRS = ["prep", "characters", "maps", "vehicles", "chroma-db", ".claude/output-styles"]

# Shared with reset_to_base.py: refuse to operate inside the engine repo.
ENGINE_SIGNATURES = ["server.py", "engine_core.py", "requirements.txt"]


def blank_files(today: str) -> dict:
    """The blank Day-1 files as {relpath: content}, with the date stamped into _meta.json."""
    return {
        "CURRENT_STATUS.md": CURRENT_STATUS,
        "MASTER_CONTINUITY_CURRENT.md": MASTER_CONTINUITY,
        "ANTAGONIST_CULTIVATION.md": ANTAGONIST,
        "lorebook.json": LOREBOOK,
        "NPC_ROSTER.md": NPC_ROSTER,
        ".gitignore": GITIGNORE,
        "characters/_meta.json": META_JSON.format(today=today),
    }


def scaffold(root: Path, today: str, overwrite: bool = False) -> list:
    """Create BLANK_DIRS and write blank_files into `root`. Skips files that already
    exist unless overwrite=True. Returns a list of action strings. Creates only — never wipes."""
    actions = []
    for d in BLANK_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
        actions.append(f"dir    {d}/")
    for rel, content in blank_files(today).items():
        p = root / rel
        if p.exists() and not overwrite:
            actions.append(f"skip   {rel} (already exists)")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        actions.append(f"write  {rel}")
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a blank Day-1 Rubicon Seven campaign folder (creates only).")
    parser.add_argument("--dir", required=True,
                        help="The new/empty campaign folder to scaffold.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing blank files (default: skip them).")
    args = parser.parse_args()

    root = Path(args.dir).resolve()
    # Safety: never scaffold over the engine repo.
    engine_hits = [s for s in ENGINE_SIGNATURES if (root / s).exists()]
    if engine_hits:
        print(f"ERROR: {root} looks like the ENGINE repo (found {engine_hits}), not a campaign. Refusing.")
        return 1

    root.mkdir(parents=True, exist_ok=True)
    for a in scaffold(root, date.today().isoformat(), overwrite=args.force):
        print(f"  {a}")
    print(f"Scaffolded blank Day-1 campaign at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
