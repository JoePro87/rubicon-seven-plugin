"""verify_claims.py extractors (D135 complaint item 1 — record/reality drift).

The seam incident: memory claimed "'seam' added to blacklist.json — enforced"
while the file lacked it, for two real days. These tests pin the claim
extractors' calibration: catch the real claim shapes from the 2026-07-20 audit
(wrapped lines, hyphenated NOT-PUSHED, branch-only claims) without the noise
classes that drowned the first run (apostrophe spans, example sentences,
bullet-list contamination, HTML-comment history).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.verify_claims import (  # noqa: E402
    extract_blacklist_membership_claims,
    extract_count_claims,
    extract_merge_claims,
    extract_unmerged_branch_claims,
    token_in_blacklist,
)


def test_membership_claim_extracted():
    text = "Blacklist regex `load[- ]bearing` in hooks/blacklist.json — ACTUALLY added 2026-07-20."
    assert extract_blacklist_membership_claims(text) == [(1, "load[- ]bearing")]


def test_membership_single_quotes_but_not_apostrophe_spans():
    text = ("'seam' was added to hooks/blacklist.json and it's enforced — "
            "the file's carve-outs held.")
    tokens = [t for _, t in extract_blacklist_membership_claims(text)]
    assert tokens == ["seam"], tokens  # no it's→file's apostrophe span


def test_membership_skips_example_sentences_and_filenames():
    text = ('Banned in hooks/blacklist.json; say "that wall carries the tier '
            'above it." instead — see `blacklist_evolver.py` for the cycle.')
    assert extract_blacklist_membership_claims(text) == []


def test_token_in_blacklist_matches_inside_entries():
    sections = {"blacklisted_phrases": ["(?<!salt )seams?(?!-Between)"],
                "use_sparingly": [], "protected_phrases": [],
                "structural_patterns": []}
    assert token_in_blacklist("seam", sections, raw="") is True
    assert token_in_blacklist("velvet dark", sections, raw="") is False


def test_count_claims_extracted():
    text = "- Loads blacklist.json: 92 blacklisted phrases + 36 use-sparingly + 5 protected + 10 structural"
    assert extract_count_claims(text) == [(1, (92, 36, 5, 10))]


def test_merge_claim_wraps_across_lines():
    # The D4 shape: hash on one line, the pending flag on the continuation.
    text = ("- **PASS 1** on branch `chore/x-hygiene` (commit `d9b3023`,\n"
            "  suite green; **NOT merged to main, NOT pushed — gated**):")
    claims = extract_merge_claims(text)
    assert (1, "d9b3023", False) in claims


def test_hyphenated_not_pushed_counts_as_pending():
    text = "## STATUS: MERGED (engine `0ab610b`; both LOCAL-NOT-PUSHED)."
    assert (1, "0ab610b", False) in extract_merge_claims(text)


def test_bullet_list_does_not_cross_contaminate():
    # One bullet's "NOT merged" must not flip its shipped siblings.
    text = ("- Feature A shipped 2026-06-16 (`25b50b4`); merged clean.\n"
            "- Feature B: branch reviewed READY, NOT merged (gated).\n"
            "- Feature C shipped (`d702995`); merged.\n")
    claims = extract_merge_claims(text)
    assert (1, "25b50b4", True) in claims
    assert (3, "d702995", True) in claims
    assert not any(h in ("25b50b4", "d702995") and not merged
                   for _, h, merged in claims)


def test_html_comment_history_is_skipped():
    text = ("<!-- SUPERSEDED 2026-05-31 — old counts 78 blacklisted + 46 "
            "use-sparingly kept as dated record -->\n"
            "Live text with no claims.")
    assert extract_count_claims(text) == []


def test_branch_only_pending_claim():
    # The D2 shape: no hash on the line at all.
    text = "- Settlement v1 follow-ons: branch `feat/settlement-v1-followons` reviewed READY, NOT merged (gated)."
    assert extract_unmerged_branch_claims(text) == [(1, "feat/settlement-v1-followons")]


def test_day_labels_are_not_hashes():
    text = "D134 fixes merged to main the same day."
    assert extract_merge_claims(text) == []
