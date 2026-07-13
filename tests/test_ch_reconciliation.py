"""Forward guards for the 2026-07-05 CH reconciliation (fix/ch-reconciliation).

Verified against the authoritative Crimson Hound 07-05-26 PDF:
- elixir brew time is POT Exploration Turns (book p.52), not "one full day"
- the seven Daemon Boons (book p.232) are ingested as rule-quantum-daemon-boons
"""
import json
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "rules" / "rulebook" / "rules.json"


def _entries():
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))["entries"]


def test_brew_time_is_pot_exploration_turns():
    brew = next(e for e in _entries() if e["id"] == "rule-alchemy-brew-elixir")
    assert "Exploration Turns equal to the Elixir's POT" in brew["rule"]
    assert "one full day" not in brew["rule"]


def test_daemon_boons_entry_present_with_all_seven():
    boons = next(e for e in _entries() if e["id"] == "rule-quantum-daemon-boons")
    for name in ("Metamorphosis", "Gifted", "Far-Seeing", "Far-Speaking",
                 "Augury", "Memento Mori", "Quantum Link"):
        assert name in boons["rule"], f"missing boon: {name}"


def test_summon_rule_points_at_boons():
    summon = next(e for e in _entries() if e["id"] == "rule-quantum-daemon-summon")
    assert "rule-quantum-daemon-boons" in summon["rule"]


def test_rule_entries_keep_six_key_shape():
    for e in _entries():
        assert sorted(e.keys()) == ["categories", "contexts", "id", "keywords", "rule", "source"]
