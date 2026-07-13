"""C6 — rulebook(search) dedup cooldown must self-expire and never suppress silently.

Before the fix, RulebookSystem._turn only advanced via rulebook(action="turn"),
which had zero callers, so _turn stayed 0 forever and every entry a search ever
returned was suppressed for the life of the process — silently ("No matches").

The fix makes the cooldown self-driven (one tick per search call) so it expires
after COOLDOWN_TURNS searches, and surfaces a suppression count instead of a bare
"No matches".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rulebook_system import RulebookSystem, register_rulebook_tools


def _rb_with_fake_entry():
    """A RulebookSystem whose cache holds one matchable rule (no disk dependency)."""
    rb = RulebookSystem(Path(__file__).parent.parent)
    rb._cache = {
        'rules': [{'id': 'rule-morale', 'keywords': ['morale', 'flee'], 'name': 'Morale', 'rule': 'Check morale.'}],
        'tables': {'rolling': [], 'reference': []},
        'bestiary': [], 'equipment': [], 'gifts': [], 'lore': [],
    }
    rb._injections = {}
    rb._turn = 0
    return rb


def test_first_search_returns_entry_and_no_suppression():
    rb = _rb_with_fake_entry()
    results = rb.search("morale")
    assert [r['id'] for r in results] == ['rule-morale']
    assert rb._last_suppressed == 0


def test_immediate_re_search_suppresses_and_counts():
    rb = _rb_with_fake_entry()
    rb.search("morale")            # returns + marks on cooldown
    results = rb.search("morale")  # same turn-ish → suppressed
    assert results == []
    assert rb._last_suppressed == 1


def test_cooldown_expires_after_horizon():
    rb = _rb_with_fake_entry()
    rb.search("morale")  # returned, marked at turn 1
    # Every subsequent search advances the clock by one tick.
    reappeared = False
    for _ in range(RulebookSystem.COOLDOWN_TURNS + 1):
        results = rb.search("morale")
        if results:
            reappeared = True
            break
    assert reappeared, "entry never became searchable again — cooldown did not expire"
    assert rb._last_suppressed == 0


def test_skip_cooldown_never_suppresses_or_ticks():
    rb = _rb_with_fake_entry()
    start_turn = rb._turn
    rb.search("morale")  # normal → marks
    r = rb.search("morale", skip_cooldown=True)
    assert [x['id'] for x in r] == ['rule-morale']
    assert rb._last_suppressed == 0
    # skip_cooldown search must not advance the clock
    assert rb._turn == start_turn + 1  # only the first (non-skip) search ticked


def _capture_rulebook_tool():
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    rb_sys = register_rulebook_tools(_FakeMCP(), Path(__file__).parent.parent)
    return captured["rulebook"], rb_sys


def test_tool_reports_suppression_count_not_silent():
    rulebook, rb_sys = _capture_rulebook_tool()
    rb_sys._cache = {
        'rules': [{'id': 'rule-morale', 'keywords': ['morale'], 'name': 'Morale', 'rule': 'Check morale.'}],
        'tables': {'rolling': [], 'reference': []},
        'bestiary': [], 'equipment': [], 'gifts': [], 'lore': [],
    }
    rb_sys._injections = {}
    rb_sys._turn = 0

    first = rulebook(action="search", query="morale")
    assert "Morale" in first or "morale" in first.lower()

    second = rulebook(action="search", query="morale")
    # Suppressed, but must SAY so — not a bare "No matches".
    assert "suppressed by dedup cooldown" in second
    assert "1 matching entr" in second


def test_session_reset_clears_cooldown_state():
    rb = _rb_with_fake_entry()
    rb.search("morale")
    rb.search("morale")
    assert rb._injections  # something on cooldown
    rb.reset_session()
    assert rb._injections == {}
    assert rb._turn == 0
    assert rb._last_suppressed == 0
    # Fresh session → entry searchable again immediately
    assert [r['id'] for r in rb.search("morale")] == ['rule-morale']
