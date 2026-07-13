"""Tool visibility tag definitions for Rubicon Seven MCP server.

Three dimensions of tags:
1. Safety Level - enforcement (always, gated, dangerous)
2. Game Phase - noise reduction (startup, exploration, combat, social, travel, rest, generation)
3. Data Domain - organizational (character, location, narrative, mechanics, meta)
"""

# Safety levels - controls enforcement behavior
class Safety:
    ALWAYS = "safety:always"      # Never disabled
    GATED = "safety:gated"        # Requires check_canon first

# Game phases - controls visibility during play
class Phase:
    STARTUP = "phase:startup"
    EXPLORATION = "phase:exploration"
    COMBAT = "phase:combat"
    SOCIAL = "phase:social"
    TRAVEL = "phase:travel"
    REST = "phase:rest"
    GENERATION = "phase:generation"
    SESSION = "phase:session"

# Data domains - organizational grouping
class Domain:
    CHARACTER = "domain:character"
    LOCATION = "domain:location"
    NARRATIVE = "domain:narrative"
    MECHANICS = "domain:mechanics"
    META = "domain:meta"
    FILE = "domain:file"

# Tool -> Tags mapping
TOOL_TAGS = {
    # === ALWAYS SAFE (read-only, no state changes) ===
    "check_canon": {Safety.ALWAYS, Phase.STARTUP, Domain.META},
    "reset_gate": {Safety.ALWAYS, Domain.META},
    # session_mode toggles maintenance on/off. ALWAYS so it works BEFORE check_canon
    # and BEFORE full_session_startup (it IS the canon-bypass; gating it would deadlock).
    "session_mode": {Safety.ALWAYS, Phase.SESSION, Domain.META},
    # dm_view RETIRED 2026-07-02 (C28) — was a permanently dead retrieval surface.
    "validate_prep_file": {Safety.ALWAYS, Phase.EXPLORATION, Domain.LOCATION},
    "lookup": {Safety.ALWAYS, Phase.COMBAT, Phase.GENERATION, Domain.MECHANICS},
    "cybernetic": {Safety.GATED, Phase.REST, Domain.CHARACTER},
    "gift": {Safety.GATED, Phase.REST, Domain.CHARACTER},
    "load_last_session": {Safety.ALWAYS, Phase.STARTUP, Domain.META},
    "reference_location": {Safety.ALWAYS, Domain.LOCATION},
    "test_dice": {Safety.ALWAYS, Phase.SESSION, Domain.MECHANICS},
    "validate_campaign_state": {Safety.ALWAYS, Phase.SESSION, Domain.META},
    "full_session_startup": {Safety.ALWAYS, Phase.STARTUP, Domain.META},
    "get_visibility_status": {Safety.ALWAYS, Domain.META},

    # === CONSOLIDATED TOOLS ===
    "geography": {Safety.GATED, Phase.TRAVEL, Domain.LOCATION},
    "map": {Safety.GATED, Phase.EXPLORATION, Domain.LOCATION},
    "lorebook": {Safety.GATED, Phase.SOCIAL, Domain.NARRATIVE},
    "rulebook": {Safety.ALWAYS, Phase.COMBAT, Phase.EXPLORATION, Domain.MECHANICS},

    # === W1 FAMILY MERGES (2026-06-14) — new domain tools. Source-name keys and
    # tombstone aliases removed in the tombstone-removal cleanup (2026-06-14). ===
    # constraint = constraint_add(GATED) U constraint_check(ALWAYS): the WRITE
    # posture wins (never under-gate a state write); check now needs canon, but
    # canon is already verified mid-scene where checks happen.
    "constraint": {Safety.GATED, Phase.EXPLORATION, Domain.MECHANICS},
    # narrative_qa = anti_patterns U validate_prose — identical tags, no tension.
    "narrative_qa": {Safety.ALWAYS, Phase.SESSION, Domain.NARRATIVE},
    # W2 (2026-06-14): files (the 3 read tools, all ALWAYS) and edit_file (the 2 write
    # tools, both GATED) stay split — reads and writes have opposite gate postures and
    # both matter, so a single `file` tool would force a gate-tension.
    "files": {Safety.ALWAYS, Domain.FILE},
    "edit_file": {Safety.GATED, Phase.SESSION, Domain.FILE},
    # W3 (2026-06-14): search merges the 3 READ tools (2 async queries + the index
    # health diagnostic), all ALWAYS — no gate tension. The index-WRITE tools
    # (reindex_recent/ingest_distillations/distill_session) stay separate (save-
    # pipeline-sensitive).
    "search": {Safety.ALWAYS, Phase.SESSION, Domain.NARRATIVE},
    # Affliction wave (2026-06-14): condition+disease+toxin+wound -> affliction(kind,action).
    # All four sources are GATED -> no gate-tension; union of their phases/domains.
    "affliction": {Safety.GATED, Phase.REST, Phase.COMBAT, Domain.CHARACTER, Domain.MECHANICS},
    # log = log_beat(GATED) U get_session_log(ALWAYS): the READ posture wins so
    # log(action='get') stays available at resume time (pre-canon); beat-logging
    # is continuity bookkeeping, not a mechanical write, so dropping its gate is safe.
    "log": {Safety.ALWAYS, Phase.SESSION, Domain.NARRATIVE},

    # === SESSION SAVE (always accessible for pre-compaction saves) ===
    "save_state": {Safety.ALWAYS, Phase.SESSION, Domain.META},
    "prepare_save_state": {Safety.ALWAYS, Phase.SESSION, Domain.META},
    "confirm_save": {Safety.ALWAYS, Phase.SESSION, Domain.META},

    # === GATED (requires check_canon first) ===
    "advance_day": {Safety.GATED, Phase.REST, Domain.META},
    "codex": {Safety.GATED, Phase.REST, Domain.CHARACTER},
    "rest": {Safety.GATED, Phase.REST, Domain.CHARACTER},
    "supply": {Safety.GATED, Phase.REST, Domain.CHARACTER},
    "relationship": {Safety.GATED, Phase.SOCIAL, Domain.NARRATIVE},
    "faction": {Safety.GATED, Phase.SOCIAL, Domain.NARRATIVE},
    "thread": {Safety.GATED, Domain.NARRATIVE},
    "npc": {Safety.GATED, Phase.SOCIAL, Domain.NARRATIVE},
    "update_location_progress": {Safety.GATED, Phase.EXPLORATION, Domain.LOCATION},
    "roll": {Safety.GATED, Phase.GENERATION, Domain.MECHANICS},
    "character": {Safety.ALWAYS, Phase.COMBAT, Domain.CHARACTER},
    "combat": {Safety.GATED, Phase.COMBAT, Domain.MECHANICS},
    "usage": {Safety.GATED, Phase.COMBAT, Domain.MECHANICS},
    "generate": {Safety.GATED, Phase.GENERATION, Domain.MECHANICS},

    # === PREVIOUSLY UNTAGGED (added 2026-05-07) ===
    "antagonist": {Safety.GATED, Domain.NARRATIVE},
    "reindex_recent": {Safety.GATED, Phase.SESSION, Domain.META},
    "distill_session": {Safety.ALWAYS, Phase.SESSION, Domain.META},
    "ingest_distillations": {Safety.ALWAYS, Phase.SESSION, Domain.META},

    # === GATED FILE OPS (require check_canon, previously DANGEROUS) ===
    "sync_campaign_day": {Safety.GATED, Phase.SESSION, Domain.META},
    "update_active_prep": {Safety.GATED, Domain.LOCATION, Phase.EXPLORATION},
}

def get_tags_for_tool(tool_name: str) -> set[str]:
    """Get all tags for a tool, or empty set if not mapped."""
    return TOOL_TAGS.get(tool_name, set())

def get_tools_by_tag(tag: str) -> set[str]:
    """Get all tools that have a specific tag."""
    return {name for name, tags in TOOL_TAGS.items() if tag in tags}

def get_tools_by_safety(safety_level: str) -> set[str]:
    """Get all tools at a specific safety level."""
    return get_tools_by_tag(safety_level)
