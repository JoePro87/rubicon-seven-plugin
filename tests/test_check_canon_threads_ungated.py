"""Fix 3 — narrative threads surface on EVERY turn (ungated).

Threads were the only canon store double-gated: `if 'threads' in active_blocks`
wrapped the keyword match, and ordinary-play regex paths never add 'threads' to
active_blocks, so threads silently never surfaced outside lore/high-match turns.
The match now runs unconditionally (like factions and site-features), capped at
2, and returns canon-delivery tuples so the existing delta-dedup fold applies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


THREADS = {
    "threads": {
        "t1": {
            "status": "active", "title": "The Sable Gecko", "urgency": "high",
            "description": "A missing courier. Rumors spread through the market.",
            "foreshadowing": ["broken seal"],
        },
        "t2": {
            "status": "active", "title": "Salt Debt", "urgency": "low",
            "description": "Owed to the guild.",
            "foreshadowing": ["ledger of salt"],
        },
        "t3": {
            "status": "active", "title": "Third Thread", "urgency": "low",
            "description": "unrelated matter", "foreshadowing": ["zzzzz"],
        },
        "t4": {
            "status": "resolved", "title": "Sable Old", "urgency": "low",
            "description": "closed", "foreshadowing": [],
        },
    }
}


def test_thread_surfaces_on_title_keyword():
    """A thread whose title word appears in input surfaces — no active_blocks
    consulted anywhere in the helper (ungated by construction)."""
    els = server._thread_injection_elements(THREADS, "we chase the gecko downtown", [])
    keys = [k for _, k, _ in els]
    assert "thread:The Sable Gecko" in keys


def test_thread_surfaces_on_foreshadowing_keyword():
    """Foreshadowing key terms also trigger a match."""
    els = server._thread_injection_elements(THREADS, "she unrolls the ledger slowly", [])
    keys = [k for _, k, _ in els]
    assert "thread:Salt Debt" in keys


def test_resolved_threads_excluded():
    els = server._thread_injection_elements(THREADS, "the sable business", [])
    keys = [k for _, k, _ in els]
    assert "thread:Sable Old" not in keys


def test_capped_at_two():
    """At most 2 threads surface per turn even when three match."""
    els = server._thread_injection_elements(
        THREADS, "gecko and salt and third all at once", [])
    assert len(els) <= 2


def test_dedup_key_stable_on_repeat():
    """Each element is keyed thread:<title> so the canon_delivered delta-dedup
    fold collapses the same thread on repeat turns (stable key both calls)."""
    first = server._thread_injection_elements(THREADS, "the gecko again", [])
    second = server._thread_injection_elements(THREADS, "the gecko again", [])
    assert [k for _, k, _ in first] == [k for _, k, _ in second]
    section, key, _content = first[0]
    assert section == "ACTIVE THREADS"
    assert key == "thread:The Sable Gecko"


def test_no_match_returns_empty():
    els = server._thread_injection_elements(THREADS, "nothing relevant here", [])
    assert els == []


def test_call_site_is_ungated():
    """The check_canon call site no longer wraps thread matching in
    `if 'threads' in active_blocks`; it calls the helper unconditionally."""
    src = Path(server.__file__).read_text(encoding="utf-8")
    assert "_thread_injection_elements(" in src
    # The retired double-gate must be gone.
    assert "if 'threads' in active_blocks:" not in src
