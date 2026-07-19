"""rubicon_paths.py - portable, dependency-free path resolution.

ONE home for resolving the engine directory and the campaign-data directory,
replacing the ~8 hardcoded machine-specific fallbacks that were duplicated across
engine_core.py and the hooks/. Stdlib-only by design: this module is imported by
hooks that run as standalone `python3 hooks/X.py` scripts, so it must NOT pull in
engine_core / server / chromadb (avoids import cycles and heavy deps).

Resolution rules (env always wins; otherwise derive, never hardcode a machine):

  engine_dir()   = $RUBICON_ENGINE_DIR, else the directory containing THIS file
                   (Path(__file__).resolve().parent) -- the repo root holding
                   server.py / engine_core.py / this module.

  campaign_dir() = $RUBICON_CAMPAIGN_DIR, else the SIBLING of the engine dir named
                   "rubicon-seven-campaign" (engine_dir().parent / name).

In the default sibling layout the engine repo and the campaign repo sit side by
side (e.g. <parent>/rubicon-seven-mcp and <parent>/rubicon-seven-campaign), so the
campaign dir is DERIVED, not a hardcoded machine path. Zero behavior change on a
sibling install, portable for everyone else.
"""
import os
import re
from pathlib import Path

CAMPAIGN_DIR_NAME = "rubicon-seven-campaign"


def engine_dir() -> Path:
    """The engine repo root (holds server.py / engine_core.py / this file).

    Honors $RUBICON_ENGINE_DIR; otherwise derives from this file's own location.
    """
    env = os.environ.get("RUBICON_ENGINE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent


def campaign_dir() -> Path:
    """The campaign-data directory.

    Honors $RUBICON_CAMPAIGN_DIR; otherwise the sibling of the engine dir named
    'rubicon-seven-campaign'.
    """
    env = os.environ.get("RUBICON_CAMPAIGN_DIR")
    if env:
        return Path(env)
    return engine_dir().parent / CAMPAIGN_DIR_NAME


def catch_analytics_path() -> Path:
    """Per-campaign prose-catch analytics store.

    CAMPAIGN-SCOPED. It used to resolve engine-relative (``hooks/catch_analytics.json``),
    which was a privacy leak: engine-dir files are shared across every campaign AND the
    file was git-tracked, so a player's accumulated play history shipped to anyone who
    cloned the repo. Scoping it under the campaign dir gives each campaign its own and
    keeps it out of the engine repo. Missing file = empty (fresh campaigns seed clean);
    the owner's legacy ``<engine>/hooks/catch_analytics.json`` is migrated by an explicit
    one-time copy, not silently read.
    """
    return campaign_dir() / "catch_analytics.json"


def prose_window_path() -> Path:
    """Per-campaign rolling window of recent DM narration turns (JSONL, capped).

    CAMPAIGN-SCOPED for the same privacy reason as catch_analytics_path.
    Written by the Stop hook on narrative turns; consumed by the blacklist
    evolver's template scan (template_nominations) at save-commit."""
    return campaign_dir() / ".prose_window.jsonl"


def _cc_project_slug(path_str: str) -> str:
    """Claude Code's per-project dir slug: every non-alphanumeric char -> '-'.
    Verified against the live store (e.g. '/mnt/c/path/to/campaign'
    -> '-mnt-c-path-to-campaign')."""
    return re.sub(r"[^a-zA-Z0-9]", "-", path_str)


def campaign_memory_md_path() -> Path:
    """The campaign's auto-memory MEMORY.md handoff note, under Claude Code's
    per-project memory dir (~/.claude/projects/<slug>/memory/MEMORY.md).

    Replaces two hardcoded owner-specific slugs (was session_tools.py +
    server.py's antagonist MEMORY scan) -- one home now.

    The slug is Claude Code's mangling of the project path AS CLAUDE CODE SAW IT
    at launch, which can differ from campaign_dir()'s form: on a WSL rig the
    engine runs under Windows Python (campaign_dir() = C:\\...-campaign) while
    Claude Code launched from WSL (slug derived from /mnt/c/...-campaign). So we
    build BOTH candidate slugs -- the native one and, for a Windows drive path,
    the /mnt/<drive>/ WSL-normalized one -- and return whichever candidate's
    MEMORY.md actually exists; failing that, the native default (correct for a
    fresh campaign that has not written one yet)."""
    base = Path.home() / ".claude" / "projects"
    s = str(campaign_dir())
    candidates = [_cc_project_slug(s)]
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        wsl = "/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
        candidates.append(_cc_project_slug(wsl))
    for slug in candidates:
        p = base / slug / "memory" / "MEMORY.md"
        if p.exists():
            return p
    return base / candidates[0] / "memory" / "MEMORY.md"
