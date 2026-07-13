"""Protected phrases are never auto-promoted by the evolver."""
import json
from pathlib import Path
from hooks import blacklist_evolver as ev

PROTECTED = {"deliberate", "unhurried", "says nothing", "without looking"}


def _analytics_with(phrase, total, sessions):
    return {"phrase_stats": {phrase: {"total_catches": total, "sessions_seen": sessions}},
            "_meta": {"total_sessions_tracked": sessions}}


def test_protected_phrase_not_added_to_sparingly():
    analytics = _analytics_with("deliberate", total=9, sessions=5)  # easily over threshold
    cands = ev.find_promotion_candidates(analytics, existing_phrases=set(), protected=PROTECTED)
    assert "deliberate" not in cands


def test_unprotected_phrase_still_added():
    analytics = _analytics_with("brand new tic", total=9, sessions=5)
    cands = ev.find_promotion_candidates(analytics, existing_phrases=set(), protected=PROTECTED)
    assert "brand new tic" in cands


def test_protected_phrase_not_promoted_to_banned():
    analytics = _analytics_with("unhurried", total=9, sessions=5)
    promos = ev.find_tier_promotions(analytics, sparingly_phrases={"unhurried"}, protected=PROTECTED)
    assert "unhurried" not in promos


def test_blacklist_json_protects_and_frees_the_four():
    bl = json.loads(Path("hooks/blacklist.json").read_text(encoding="utf-8"))
    protected = set(p.lower() for p in bl.get("protected_phrases", []))
    sparingly = set(p.lower() for p in bl.get("use_sparingly", []))
    banned = set(p.lower() for p in bl.get("blacklisted_phrases", []))
    for w in ["deliberate", "unhurried", "says nothing", "without looking"]:
        assert w in protected, f"{w} not protected"
        assert w not in sparingly, f"{w} still in use_sparingly"
        assert w not in banned, f"{w} is banned"
