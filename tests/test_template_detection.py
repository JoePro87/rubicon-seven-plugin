"""Tests for construction-frame (template) detection in the blacklist evolver.

The DM's prose mutates around literal phrase-bans into recurring SYNTACTIC frames
that the phrase mechanism can never see ("the way she grips a rail" and "the way
weather clears" are one frame, two strings). These tests pin the frame extractor,
the candidate finder, and the nomination-only write path (never auto-ban).
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blacklist_evolver import (
    extract_frames,
    find_template_candidates,
    run_template_scan,
)

REAL_BLACKLIST = Path(__file__).resolve().parents[1] / "hooks" / "blacklist.json"


def _real_structural_patterns():
    data = json.loads(REAL_BLACKLIST.read_text(encoding="utf-8"))
    return [p["pattern"] for p in data.get("structural_patterns", [])]


# ---------------------------------------------------------------------------
# extract_frames — normalization
# ---------------------------------------------------------------------------

def test_proper_noun_midsentence_becomes_slot():
    frames = extract_frames("The way Kesh moved through the market")
    joined = " || ".join(frames)
    assert "kesh" not in joined  # proper noun normalized away
    assert "<N>" in joined


def test_first_word_capitalized_is_not_a_proper_noun():
    # Sentence-initial capital is just the start of a sentence, not a name.
    frames = extract_frames("Weather turned against the caravan")
    joined = " || ".join(frames)
    assert "<N>" not in joined
    assert "weather" in joined


def test_pronouns_become_slot():
    frames = extract_frames("the way she grips a rail")
    joined = " || ".join(frames)
    assert "<P>" in joined
    assert " she " not in f" {joined} "


def test_numbers_become_slot():
    frames = extract_frames("the caravan lost 3 water rations")
    assert any("<#>" in f for f in frames)


def test_ngram_sizes_are_3_4_5():
    frames = extract_frames("alpha beta gamma delta epsilon zeta")
    lengths = {len(f.split()) for f in frames}
    assert lengths == {3, 4, 5}


def test_stopword_only_frames_are_skipped():
    # "in the a of" is all stopwords -> no frame should survive.
    frames = extract_frames("in the a of and to")
    assert frames == []


def test_slot_plus_stopword_only_is_skipped():
    # "<P>" is a slot, "the"/"a" stopwords -> no content token, skip.
    frames = extract_frames("She the a it")
    assert frames == []


# ---------------------------------------------------------------------------
# find_template_candidates — the core behaviour
# ---------------------------------------------------------------------------

def test_shared_frame_across_unrelated_strings():
    # Two unrelated sentences, one shared construction frame ("the way <P> ...").
    samples = ["The way she grips a rail"] * 5 + ["The way she wrings a cloth"] * 5
    cands = find_template_candidates(samples, min_count=8)
    frames = {c["frame"] for c in cands}
    assert "the way <P>" in frames
    top = next(c for c in cands if c["frame"] == "the way <P>")
    assert top["count"] == 10
    assert "the way" in top["example"].lower()


def test_threshold_respected():
    samples = ["the caravan crossed the salt flat"] * 7
    assert find_template_candidates(samples, min_count=8) == []
    samples2 = ["the caravan crossed the salt flat"] * 8
    assert find_template_candidates(samples2, min_count=8) != []


def test_sorted_by_count_desc():
    samples = ["red gate opens slowly"] * 12 + ["blue door shuts quietly"] * 9
    cands = find_template_candidates(samples, min_count=8)
    counts = [c["count"] for c in cands]
    assert counts == sorted(counts, reverse=True)


def test_existing_pattern_filtering_real_regex():
    # Prose that the live "the way X <verbs>" structural regex already covers
    # must NOT be nominated as a fresh template.
    patterns = _real_structural_patterns()
    the_way_rx = [p for p in patterns if "the way" in p]
    assert the_way_rx, "expected a 'the way' structural pattern in the real blacklist"

    samples = ["the way she grips a rail"] * 10 + ["the way soldiers march forward"] * 10
    unfiltered = find_template_candidates(samples, min_count=8)
    filtered = find_template_candidates(samples, min_count=8, existing_patterns=patterns)

    assert any("the way" in c["frame"] for c in unfiltered)
    # every surviving frame's example must escape the existing regex
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    for c in filtered:
        assert not any(rx.search(c["example"]) for rx in compiled)


def test_invalid_existing_regex_is_skipped():
    samples = ["the beacon flared over the dunes"] * 9
    # "(" is an invalid regex; must not raise.
    cands = find_template_candidates(samples, min_count=8, existing_patterns=["("])
    assert cands  # still returns candidates, bad pattern ignored


def test_subframe_collapse():
    # A 3-gram that ONLY ever appears inside one longer candidate is dropped
    # in favour of the longer frame.
    samples = ["the pale rider crested the ridge"] * 10
    cands = find_template_candidates(samples, min_count=8)
    frames = {c["frame"] for c in cands}
    # "pale rider crested" (3) lives only inside "the pale rider crested" (4)+
    assert "the pale rider crested" in frames or "the pale rider crested the" in frames
    assert "pale rider crested" not in frames


# ---------------------------------------------------------------------------
# run_template_scan — nomination-only write path
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_blacklist(tmp_path):
    dst = tmp_path / "blacklist.json"
    shutil.copy(REAL_BLACKLIST, dst)
    return dst


def test_scan_writes_only_to_nominations(tmp_blacklist):
    before = json.loads(tmp_blacklist.read_text(encoding="utf-8"))
    banned_before = list(before.get("blacklisted_phrases", []))
    sparingly_before = list(before.get("use_sparingly", []))
    structural_before = list(before.get("structural_patterns", []))

    samples = ["the copper sky pressed down hard"] * 12
    result = run_template_scan(samples, tmp_blacklist, nominated_date="2026-07-19", min_count=8)

    after = json.loads(tmp_blacklist.read_text(encoding="utf-8"))
    # never auto-bans
    assert after["blacklisted_phrases"] == banned_before
    assert after["use_sparingly"] == sparingly_before
    assert after["structural_patterns"] == structural_before
    # nominations landed
    assert result["nominated"] >= 1
    noms = after["template_nominations"]
    assert all(n["status"] == "pending" for n in noms)
    assert all(n["nominated"] == "2026-07-19" for n in noms)


def test_scan_preserves_all_existing_keys(tmp_blacklist):
    before_keys = set(json.loads(tmp_blacklist.read_text(encoding="utf-8")).keys())
    run_template_scan(["the glass tower leaned east"] * 10, tmp_blacklist,
                      nominated_date="2026-07-19")
    after = json.loads(tmp_blacklist.read_text(encoding="utf-8"))
    assert before_keys <= set(after.keys())
    assert "template_nominations" in after


def test_scan_dedupes_across_runs(tmp_blacklist):
    samples = ["the copper sky pressed down hard"] * 12
    r1 = run_template_scan(samples, tmp_blacklist, nominated_date="2026-07-19")
    count_after_first = len(json.loads(tmp_blacklist.read_text(encoding="utf-8"))["template_nominations"])
    r2 = run_template_scan(samples, tmp_blacklist, nominated_date="2026-07-20")
    count_after_second = len(json.loads(tmp_blacklist.read_text(encoding="utf-8"))["template_nominations"])

    assert r1["nominated"] >= 1
    assert r2["nominated"] == 0  # same frames, already pending
    assert count_after_first == count_after_second


def test_scan_does_not_renominate_any_status(tmp_blacklist):
    # A frame already recorded (even as 'accepted'/'rejected') is not re-added.
    data = json.loads(tmp_blacklist.read_text(encoding="utf-8"))
    data["template_nominations"] = [
        {"frame": "the copper sky pressed", "count": 99, "example": "x",
         "nominated": "2026-01-01", "status": "rejected"}
    ]
    tmp_blacklist.write_text(json.dumps(data, indent=2), encoding="utf-8")

    run_template_scan(["the copper sky pressed down hard"] * 12, tmp_blacklist,
                      nominated_date="2026-07-19")
    after = json.loads(tmp_blacklist.read_text(encoding="utf-8"))
    frames = [n["frame"] for n in after["template_nominations"]]
    assert frames.count("the copper sky pressed") == 1
