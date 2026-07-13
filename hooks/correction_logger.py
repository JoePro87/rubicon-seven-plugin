#!/usr/bin/env python3
"""Shared utility for logging Stop hook corrections.

NEUTRALIZED 2026-05-29 (§12): corrections.json was write-only — its only reader
(blacklist_evolver) is never invoked at session-end, and the player never sees it.
The functions are kept as no-ops so existing callers
(consolidated_stop_check.log_correction, turn_reset.mark_false_positive) stay safe;
they simply no longer write anything.
"""

from pathlib import Path
from typing import Optional

# Retained for callers/tests that reference the path; nothing is written to it.
CORRECTIONS_FILE = Path(__file__).parent / "corrections.json"


def load_corrections() -> list:
    """No-op (corrections logging retired)."""
    return []


def save_corrections(corrections: list) -> None:
    """No-op (corrections logging retired)."""
    return None


def log_correction(
    hook_name: str,
    caught_text: str,
    reason_given: str,
    severity: str = "hard",
    false_positive: Optional[bool] = None,
) -> None:
    """No-op (corrections logging retired)."""
    return None


def mark_false_positive(index: int = -1) -> bool:
    """No-op (corrections logging retired)."""
    return False


def get_recent_corrections(n: int = 10) -> list:
    """No-op (corrections logging retired)."""
    return []
