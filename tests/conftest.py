"""
Shared test fixtures for Rubicon Seven MCP tests.

CRITICAL: Prevents test suites from writing to production campaign files.
All tests that import from server.py will automatically get a temp campaign dir.
"""

import os
import pytest
import shutil
import tempfile
from pathlib import Path


# PHASE 1: Set env var at module import time, before any test files import server
# This ensures server.py reads the temp path when it first loads
_TEST_CAMPAIGN_DIR = Path(tempfile.mkdtemp(prefix="rubicon_test_global_"))
os.environ["RUBICON_CAMPAIGN_DIR"] = str(_TEST_CAMPAIGN_DIR)


def _real_campaign_dir():
    """Locate the REAL campaign repo (source of read-only rulebook data) in a
    platform-independent way.

    The suite runs under the Windows venv Python (per CLAUDE.md), where a
    hardcoded POSIX path like ``/mnt/c/...`` normalises to ``\\mnt\\c\\...`` and
    does NOT exist — so any fixture that copied data from such a path silently
    staged nothing. We resolve relative to this file instead (the campaign repo
    is a sibling of the mcp repo), with explicit Windows/WSL mounts as fallback.
    """
    candidates = [
        Path(__file__).resolve().parents[2] / "rubicon-seven-campaign",
    ]
    return next((c for c in candidates if c.exists()), candidates[0])


REAL_CAMPAIGN_DIR = _real_campaign_dir()


@pytest.fixture(autouse=True)
def isolate_campaign_dir(tmp_path, monkeypatch):
    """
    Automatically redirect all campaign file operations to a temp directory.

    What: Every test gets its own temporary campaign directory.
    Why: Tests were writing garbage to production MASTER_CONTINUITY_CURRENT.md
         and corrupting CURRENT_STATUS.md (the Feb 9/Feb 15 disaster).
    Effect: No test can ever touch production campaign files again.

    Implementation:
    - Phase 1 (module-level above): Set env var before any imports
    - Phase 2 (this fixture): Patch the already-loaded server module per test
    """
    # Get the active campaign dir (will be the global test dir from module-level setup)
    import sys
    if 'server' in sys.modules:
        import server
        active_campaign_dir = server.CAMPAIGN_DIR
    else:
        active_campaign_dir = Path(os.environ["RUBICON_CAMPAIGN_DIR"])

    # Create minimal directory structure tests might expect
    (active_campaign_dir / "prep").mkdir(exist_ok=True, parents=True)
    (active_campaign_dir / "chroma-db").mkdir(exist_ok=True, parents=True)

    # Create minimal CURRENT_STATUS.md so tools don't crash
    status_file = active_campaign_dir / "CURRENT_STATUS.md"
    if not status_file.exists():
        status_file.write_text(
            "# CURRENT STATUS - DAY 50\n\n"
            "**Last Updated:** 2026-01-01 00:00\n\n"
            "---\n\n"
            "## SCENE STATE (check_canon reads this section)\n\n"
            "**Day:** 50\n"
            "**Location:** Test Location\n"
            "**Present:** Creenash, Vela\n"
        )

    # Create minimal continuity file
    continuity = active_campaign_dir / "MASTER_CONTINUITY_CURRENT.md"
    if not continuity.exists():
        continuity.write_text("# MASTER CONTINUITY - CURRENT SESSION\n\n")

    # Create minimal antagonist cultivation file with proper template structure
    cult_file = active_campaign_dir / "ANTAGONIST_CULTIVATION.md"
    if not cult_file.exists():
        cult_file.write_text(
            "# ANTAGONIST CULTIVATION\n"
            "*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*\n\n"
            "Last updated: Day 0\n\n"
            "---\n\n"
            "## ACTIVE THREATS\n"
            "*Things currently in motion, escalating*\n\n"
            "[None yet]\n\n"
            "---\n\n"
            "## DORMANT SEEDS\n"
            "*Resentments, mistakes, vulnerabilities not yet active*\n\n"
            "[None yet]\n\n"
            "---\n\n"
            "## ESCALATION LOG\n"
            "*Chronicle of how threats develop over time*\n\n"
            "[None yet]\n\n"
            "---\n\n"
            "## OPPORTUNITIES\n"
            "*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*\n\n"
            "[None yet]\n\n"
            "---\n\n"
            "## PRUNING LOG\n"
            "*Seeds removed after going nowhere for 20+ days*\n\n"
            "[None yet]\n"
        )

    # creature_resistances.json is now engine-bundled rules-data (read from
    # data/rules/rulebook/ via _load_creature_resistances), no longer copied into
    # the temp campaign dir. Reset the cache so each test reads it fresh.
    import server as _srv
    _srv._CREATURE_RESISTANCES_CACHE = None

    yield active_campaign_dir

    # Cleanup: Clear the global test dir after each test
    # This ensures tests don't interfere with each other.
    # NOTE: the state .md files are deleted too — a test that rewrites
    # CURRENT_STATUS.md (e.g. the S1 supply tests set "DAY 100") must not
    # leak that content into later tests; setup above recreates pristine
    # defaults on every test. (Found 2026-06-10: test_photosynthesis_window
    # polluted test_push_audit_batch2's prepare_save_state token tests.)
    import shutil
    for item in active_campaign_dir.iterdir():
        if item.is_dir() and item.name not in ['prep', 'chroma-db']:
            shutil.rmtree(item, ignore_errors=True)
        elif item.is_file():
            # missing_ok handles a vanished file, but on Windows a leftover file
            # can be TRANSIENTLY locked (AV/indexer/unreleased handle) and raise
            # PermissionError — that must not error the just-finished test's
            # teardown. The next test's setup recreates pristine defaults, so a
            # briefly-locked leftover is harmless.
            try:
                item.unlink(missing_ok=True)
            except PermissionError:
                pass


@pytest.fixture(scope="session", autouse=True)
def cleanup_global_test_dir():
    """Clean up the global test directory created at module import time."""
    yield
    # Cleanup after all tests complete
    if _TEST_CAMPAIGN_DIR.exists():
        shutil.rmtree(_TEST_CAMPAIGN_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# Hook-state backup/restore — session-scoped safety net
# ---------------------------------------------------------------------------
# These files live in hooks/ (sibling of tests/) and are written by hook
# processes that several tests invoke via subprocess (e.g. turn_reset.py,
# post_compact.py).  Without protection, a full suite run rewrites live
# play state and leaves git-dirty files behind.
#
# Mechanism: snapshot the raw bytes of every live hook data file at the
# start of the test session, then restore them exactly at session end —
# including deleting any file that did not exist before the tests started.
#
# Individual test files may have their own per-test preserve_state fixtures;
# this fixture is the session-level safety net that catches anything they miss.

_HOOKS_DIR = Path(__file__).resolve().parents[1] / "hooks"

_HOOK_DATA_FILES = [
    _HOOKS_DIR / ".hook_state.json",
    _HOOKS_DIR / "catch_analytics.json",
    _HOOKS_DIR / "blacklist.json",
    _HOOKS_DIR / ".canon_distillations.json",
]


@pytest.fixture(scope="session", autouse=True)
def backup_restore_hook_state():
    """Snapshot live hook data files before the suite and restore them after.

    What: Reads the raw bytes of each live hook file into memory at session
          start, then writes them back (or removes the file) at session end.
    Why:  Subprocess-based hook tests (turn_reset, post_compact) write to the
          real .hook_state.json on disk.  Without this, every test run leaves
          the live play state dirty.
    Effect: After the full suite, hooks/ files are byte-identical to before
            (git status --porcelain hooks/ shows no changes).

    Note: Individual per-test preserve_state fixtures in some test files still
    run — this fixture does not replace them.  It is the session-level safety
    net that catches anything they miss.
    """
    snapshots: dict[Path, bytes | None] = {}
    for path in _HOOK_DATA_FILES:
        snapshots[path] = path.read_bytes() if path.exists() else None

    yield  # --- run the entire test suite ---

    for path, original_bytes in snapshots.items():
        if original_bytes is None:
            # File did not exist before tests; delete it if tests created it.
            if path.exists():
                path.unlink()
        else:
            # Restore original bytes unconditionally.
            path.write_bytes(original_bytes)


# --- Synthetic campaign tripwires (fabrication detectors) ---
# The detectors load pet-names/tripwires from the campaign dir at call time
# (campaign facts are data, not engine code). Tests exercise the MECHANISM
# with invented characters — never real campaign entries.
_SYNTHETIC_TRIPWIRES = {
    "forbidden_pet_names": [
        {"name": "moonpetal",
         "message": ('PET-NAME VIOLATION: "moonpetal" is an intimate bond-name; '
                     'no NPC may speak it.')},
    ],
    "tripwires": [
        {"subject": r"\bfenwick\b",
         "context": r"\bglid(e|es|ing|ed)\b|\bpatagia\b",
         "message": "TRIPWIRE: Fenwick does not glide — that is Thornback's mechanic."},
        {"subject": r"\b(thornback)\b",
         "context": (r"\b(ate|eats|eating|chewed|swallowed|bite(s)?|devour(ed|s)?"
                     r"|drank|drinks|drinking|sipp(ed|ing)|gulp(ed|ing))\b"),
         "message": "TRIPWIRE: Thornback photosynthesizes and NEVER eats or drinks."},
        {"subject": r"\b(cogsworth)\b",
         "context": r"\b(ate|eats|eating|chewed|swallowed|drank|sleeps?)\b",
         "message": "TRIPWIRE: Cogsworth is synth — never eats, drinks, or sleeps."},
    ],
}


@pytest.fixture
def synthetic_tripwires(tmp_path, monkeypatch):
    """Seed a campaign fabrication_tripwires.json with invented characters."""
    import json as _json
    (tmp_path / "fabrication_tripwires.json").write_text(
        _json.dumps(_SYNTHETIC_TRIPWIRES), encoding="utf-8")
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))
    return tmp_path
