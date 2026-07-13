"""Book-lore canon layer — shipped CH world facts surface via check_canon.

Spec: docs/superpowers/specs/2026-07-12-book-lore-canon-layer-design.md
The layer is DM-facing RAG. Campaign canon always wins; fail-open always.
"""
import json
from pathlib import Path

import book_lore


RAW = {
    "version": "2.0.0",
    "source": "Vaarn 2e Preview",
    "entries": [
        {"id": "lore-gnomon-city", "keywords": ["Gnomon", "city of shaded markets"],
         "text": "City-state of Vaarn, dominated by the Hegemony.", "source": "CH"},
        {"id": "lore-referee-principles", "keywords": ["referee principles"],
         "text": "Advice for the referee.", "source": "CH", "scene_inject": False},
        {"id": "lore-empty", "keywords": [], "text": "orphan", "source": "CH"},
        {"id": "lore-faith-promised-sun", "keywords": ["promised sun", "sun"],
         "text": "A faith of Gnomon.", "source": "CH"},
    ],
}


def test_book_entries_converts_to_lorebook_shape():
    entries = book_lore.book_entries(RAW)
    gnomon = next(e for e in entries if "Gnomon" in e["keywords"])
    assert gnomon["category"] == "book"
    assert gnomon["status"] == "CH"
    assert gnomon["context"] == "City-state of Vaarn, dominated by the Hegemony."
    assert gnomon["short_context"] == gnomon["context"]  # <=500 chars copies through


def test_book_entries_skips_scene_inject_false_and_keywordless():
    entries = book_lore.book_entries(RAW)
    ids_texts = [e["context"] for e in entries]
    assert "Advice for the referee." not in ids_texts
    assert "orphan" not in ids_texts


def test_book_entries_fail_open_on_garbage():
    assert book_lore.book_entries({}) == []
    assert book_lore.book_entries({"entries": "not-a-list"}) == []
    assert book_lore.book_entries(None) == []


def test_book_entries_one_bad_entry_does_not_discard_good_ones():
    raw = {"entries": [
        {"id": "bad", "keywords": None, "text": "x"},
        {"id": "good", "keywords": ["gnomon"], "text": "City-state."},
    ]}
    entries = book_lore.book_entries(raw)
    assert len(entries) == 1
    assert entries[0]["context"] == "City-state."


def test_book_entries_long_text_gets_empty_short_context():
    raw = {"entries": [{"id": "long", "keywords": ["x"], "text": "y" * 501}]}
    entries = book_lore.book_entries(raw)
    assert entries[0]["short_context"] == ""
    assert entries[0]["context"] == "y" * 501


def test_match_specific_keyword_word_boundary():
    entries = book_lore.book_entries(RAW)
    m = book_lore.match_book_entries(entries, "we approach the gates of gnomon.", set(), set())
    assert len(m) == 1
    entry, kw, is_specific = m[0]
    assert kw == "gnomon" and is_specific is True
    # substring inside a word must NOT match
    assert book_lore.match_book_entries(entries, "the gnomonic projection", set(), set()) == []


def test_campaign_keyword_silences_book_entry():
    entries = book_lore.book_entries(RAW)
    # campaign lorebook has ANY entry keyworded 'gnomon' -> book stays silent on it
    m = book_lore.match_book_entries(
        entries, "we approach the gates of gnomon.", {"gnomon"}, set())
    assert m == []


def test_broad_keyword_matches_as_non_specific():
    entries = book_lore.book_entries(RAW)
    m = book_lore.match_book_entries(entries, "the sun sets over the dunes.", set(), {"sun"})
    assert len(m) == 1
    entry, kw, is_specific = m[0]
    assert kw == "sun" and is_specific is False


def test_match_book_entries_survives_bad_entry_between_good_ones():
    import book_lore
    entries = [
        {"keywords": ["gnomon"], "category": "book", "status": "CH", "context": "a", "short_context": "a"},
        {"keywords": None, "category": "book", "status": "CH", "context": "bad", "short_context": ""},
        {"keywords": ["ikor"], "category": "book", "status": "CH", "context": "b", "short_context": "b"},
    ]
    m = book_lore.match_book_entries(entries, "gnomon and ikor.", set(), set())
    assert len(m) == 2


# ---------------------------------------------------------------------------
# End-to-end: the layer inside check_canon (isolated temp campaign dir)
# ---------------------------------------------------------------------------
import pytest

import server


class _MockCtx:
    """check_canon never touches ctx before the blocks we exercise."""
    pass


def _seed_lorebook(entries):
    (Path(server.CAMPAIGN_DIR) / "lorebook.json").write_text(
        json.dumps({"entries": entries}), encoding="utf-8")


@pytest.fixture
def fresh_hook_state(tmp_path, monkeypatch):
    """Hermetic delta-fold state for the e2e tests.

    check_canon's output rides canon_delivery's delta-fold, whose delivered-keys
    ledger lives in hooks/.hook_state.json (module global server.HOOK_STATE_FILE,
    resolved at call time by _read_hook_state/_write_hook_state). Under
    pytest-randomly, an earlier test that already "delivered" a book keyword
    makes these tests see a folded pointer stub instead of the full [BOOK] line.
    Mirror tests/test_set_bell.py's established mechanism: monkeypatch
    HOOK_STATE_FILE to a per-test temp file. Seeded as a quiet MID-SESSION turn
    (turn_count > 1, scene_changed False) with an EMPTY canon_delivered ledger —
    a bare/empty state would trigger the session_start block set (turn_count <= 1
    loads lorebook_full => lore_intent), changing the behavior under test.
    """
    state_file = tmp_path / ".hook_state.json"
    state_file.write_text(json.dumps({
        "turn_count": 5,
        "last_canon_turn": 4,
        "scene_changed": False,
        "canon_delivered": {},
    }), encoding="utf-8")
    monkeypatch.setattr(server, "HOOK_STATE_FILE", state_file)
    return state_file


def test_e2e_book_entry_injects_tagged_book(isolate_campaign_dir, fresh_hook_state):
    _seed_lorebook([])
    out = server.check_canon(_MockCtx(), user_input="We approach the gates of Gnomon.", needs=[])
    assert "[BOOK]" in out
    assert "(CH)" in out
    assert "Gnomon" in out


def test_e2e_campaign_entry_silences_book_subject(isolate_campaign_dir, fresh_hook_state):
    _seed_lorebook([{"keywords": ["gnomon"], "category": "places", "status": "ESTABLISHED",
                     "context": "Gnomon as this campaign knows it.", "short_context": ""}])
    out = server.check_canon(_MockCtx(), user_input="We approach the gates of Gnomon.", needs=[])
    assert "Gnomon as this campaign knows it" in out
    assert "[BOOK]" not in out


def test_e2e_book_subcap_is_three(isolate_campaign_dir, fresh_hook_state):
    _seed_lorebook([])
    out = server.check_canon(
        _MockCtx(),
        user_input=("The Faa nomads ride past martyr tree groves and a sandworm "
                    "husk toward Gnomon, beneath the Argent Halo."),
        needs=[])
    assert 1 <= out.count("[BOOK]") <= 3


def test_e2e_broad_only_book_match_hidden_without_lore_intent(isolate_campaign_dir, fresh_hook_state):
    """A book entry matched only by a broad token (e.g. 'sun') must stay
    hidden in a quiet scene — same rule as campaign broad matches."""
    _seed_lorebook([])
    out = server.check_canon(_MockCtx(), user_input="The sun sets over the dunes.", needs=[])
    assert "[BOOK]" not in out


def test_e2e_book_matches_do_not_trigger_full_escalation(isolate_campaign_dir, fresh_hook_state):
    """Auto-FULL escalation counts CAMPAIGN specific matches only — book hits
    must not flip a quiet scene into the full context load."""
    _seed_lorebook([])
    out = server.check_canon(
        _MockCtx(),
        user_input=("The Faa nomads ride past martyr tree groves and a sandworm "
                    "husk toward Gnomon, beneath the Argent Halo."),
        needs=[])
    assert "FULL: high_match_count" not in out


def test_e2e_fail_open_when_lore_file_missing(isolate_campaign_dir, fresh_hook_state, monkeypatch, tmp_path):
    _seed_lorebook([])
    monkeypatch.setattr(server, "RULES_DATA_DIR", tmp_path / "nonexistent")
    out = server.check_canon(_MockCtx(), user_input="We approach the gates of Gnomon.", needs=[])
    assert "[BOOK]" not in out
    assert isinstance(out, str) and out  # check_canon still functions normally


# ---------------------------------------------------------------------------
# Data guards on the SHIPPED lore file (real file, read-only)
# ---------------------------------------------------------------------------
_LORE_PATH = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook" / "lore_additions.json"


def _shipped_lore():
    return json.loads(_LORE_PATH.read_text(encoding="utf-8"))


# Bare common-English tokens that would fire on incidental prose. A book entry
# may use them only inside a multi-word keyword ("vaarn regions"), never alone.
# Kept in sync with the Task-3 data-hygiene pass: every bare token actually
# stripped from an injectable entry's keywords lives here so it can't regress.
_GENERIC_DENY = {
    # brief-provided floor
    "interior", "regions", "essences", "influences", "languages", "curse",
    "venom", "prophecy", "myth", "origin", "colossus", "exemplar", "banisher",
    "crucible", "destrier", "ghoul", "gorgon", "juggernaut", "unfolder",
    # additional generic tokens removed during the audit (see task-3-report.md)
    "lore", "flat", "ai", "apex", "mech", "face", "dancer", "yucca", "gene",
    "thief", "choir", "codex", "language", "leech", "psyche", "swarm",
    "scintillating", "star", "vampire", "titan", "acolyte", "toxin", "tox",
    "void", "dragon",
    # second hygiene pass: longer common words the len<=5 audit threshold missed
    # (reviewer's wrong-entry trigger list + disclosed leftovers; see task-3-report.md)
    "ranger", "knight", "sentry", "turret", "nightmare", "herald", "oblivion",
    "obelisk", "spectre", "indifference", "master", "wisdom", "eyeless",
    "legionary", "autarch", "government", "polity", "grandfather", "crystal",
    "mineral", "advocates", "courtier", "mutant", "mutation", "labyrinth",
    "seeker", "seekers",
}

# Referee-advice entries: excluded from scene injection (rulebook tool still
# serves them). This list is the implementation's contract with the spec.
# (lore-vault-entrance-in-settlement was judged a world fact, not referee
# advice, during Task 3 and deliberately excluded — see task-3-report.md.)
_META_IDS = {
    "lore-referee-principles",
    "lore-campaign-scope-long", "lore-campaign-scope-one-shot",
    "lore-campaign-scope-open-table", "lore-campaign-scope-short",
    "lore-influences",
}


def test_shipped_meta_entries_flagged_out_of_scene_injection():
    data = _shipped_lore()
    by_id = {e["id"]: e for e in data["entries"]}
    for meta_id in _META_IDS:
        assert meta_id in by_id, f"expected shipped entry {meta_id}"
        assert by_id[meta_id].get("scene_inject") is False, meta_id


def test_no_bare_generic_trigger_keywords_on_injectable_entries():
    data = _shipped_lore()
    offenders = []
    for e in data["entries"]:
        if e.get("scene_inject", True) is False:
            continue
        for k in e.get("keywords", []):
            if k.lower().strip() in _GENERIC_DENY:
                offenders.append((e["id"], k))
    assert offenders == [], offenders


def test_shipped_entries_well_formed_and_unique():
    data = _shipped_lore()
    ids = [e["id"] for e in data["entries"]]
    assert len(ids) == len(set(ids)), "duplicate entry ids"
    for e in data["entries"]:
        assert e.get("keywords") and e.get("text") and e.get("id")
