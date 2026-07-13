"""The dm-design review gate honors state["skip_dm_design_gate"], and its block
message tells the player to say "skip review" to waive. Before this, nothing set
that flag — the advertised waiver had no detector behind it. These tests lock in
the turn_reset.detect_skip_review wiring that closes the gap (Corelia bug #2).
"""
import pytest

from hooks.turn_reset import detect_skip_review


@pytest.mark.parametrize("msg", [
    "skip review",
    "Skip Review",
    "skip the review",
    "skip dm-design",
    "skip dm design",
    "waive review",
    "waive the review",
    "Let's skip review for this one — it's just discovery content.",
])
def test_waiver_phrases_detected(msg):
    assert detect_skip_review(msg) is True


@pytest.mark.parametrize("msg", [
    "I draw my blade and advance on the cultist.",
    "review the prep file with me",
    "skip ahead to the next scene",
    "We continue the work forward.",
    "",
])
def test_unrelated_messages_not_detected(msg):
    assert detect_skip_review(msg) is False
