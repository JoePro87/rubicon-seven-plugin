"""Tests for the correction-capture learning loop."""
from hooks.fabrication_bans import FabricationBans
from hooks.distillation_cache import DistillationCache
from hooks.correction_capture import looks_like_correction, capture_correction


def test_caps_correction_detected():
    assert looks_like_correction("NO. Joss is a NAVIGATOR not a botanist.")


def test_explicit_correction_detected():
    assert looks_like_correction("wrong, you made that up — she's his mother-in-law")


def test_parenthetical_correction_detected():
    assert looks_like_correction("(Joss is Mira's father, not a botanist)")


def test_normal_play_not_a_correction():
    assert not looks_like_correction("I draw my glaive and step toward the door.")


def test_capture_writes_fact_and_ban(tmp_path):
    cache = DistillationCache(tmp_path / "c.json")
    bans = FabricationBans(tmp_path / "b.json")

    def fake_extractor(prior_dm, correction):
        return {
            "entity": "Joss",
            "wrong_terms": ["botanist"],
            "correct_fact": "Joss is a navigator, Mira's father.",
            "failure_mode": "wrong_relationship",
            "participants": ["Joss", "Mira"],
        }

    ok = capture_correction(
        prior_dm="Joss, the botanist, set down his charts.",
        correction="NO, Joss is Mira's father, a navigator.",
        cache=cache, bans=bans, extractor=fake_extractor,
        session_id="s1", turn=12,
    )
    assert ok is True
    assert len(bans.check_draft("Joss the botanist")) == 1
    assert cache.get("joss_mira_relationship") is not None


def test_capture_aborts_when_extractor_returns_none(tmp_path):
    cache = DistillationCache(tmp_path / "c.json")
    bans = FabricationBans(tmp_path / "b.json")
    ok = capture_correction("prior", "NO that's wrong",
                            cache=cache, bans=bans, extractor=lambda a, b: None,
                            session_id="s1", turn=1)
    assert ok is False
    assert bans.all_bans() == []


def test_capture_returns_false_when_extractor_raises(tmp_path):
    cache = DistillationCache(tmp_path / "c.json")
    bans = FabricationBans(tmp_path / "b.json")
    def boom(prior_dm, correction):
        raise RuntimeError("boom")
    ok = capture_correction("prior", "NO that's wrong", cache=cache, bans=bans,
                            extractor=boom, session_id="s1", turn=1)
    assert ok is False
    assert bans.all_bans() == []


def test_extract_corrections_from_transcript(tmp_path):
    import json
    from hooks.correction_capture import extract_corrections_from_transcript
    lines = [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "Joss, the botanist, looks up."}]}},
        {"type": "user", "message": {"role": "user",
         "content": "NO. Joss is a navigator, you made that up."}},
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "The wind moves over the flats."}]}},
        {"type": "user", "message": {"role": "user", "content": "I draw my glaive."}},
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    recs = extract_corrections_from_transcript(p)
    assert len(recs) == 1
    assert "botanist" in recs[0]["what_dm_got_wrong"]
    assert recs[0]["player_signal"].startswith("NO")
    assert recs[0]["is_hallucination"] is True


def test_bootstrap_from_corpus_populates_stores(tmp_path):
    import json
    from hooks.distillation_cache import DistillationCache
    from hooks.fabrication_bans import FabricationBans
    from hooks.correction_capture import bootstrap_from_halluc_results

    corpus = tmp_path / "halluc.json"
    corpus.write_text(json.dumps({"hallucinations": [
        {"is_hallucination": True,
         "what_dm_got_wrong": "DM called Joss a botanist",
         "player_signal": "Joss is a navigator, Mira's father, not a botanist",
         "category": "wrong_relationship"},
        {"is_hallucination": False, "what_dm_got_wrong": "", "player_signal": "cool"},
    ]}))
    cache = DistillationCache(tmp_path / "c.json")
    bans = FabricationBans(tmp_path / "b.json")

    def fake_extractor(prior_dm, correction):
        return {"entity": "Joss", "wrong_terms": ["botanist"],
                "correct_fact": "Joss is a navigator, Mira's father.",
                "failure_mode": "wrong_relationship", "participants": ["Joss", "Mira"]}

    n = bootstrap_from_halluc_results(corpus, cache, bans, extractor=fake_extractor)
    assert n == 1
    assert len(bans.check_draft("Joss the botanist")) == 1
    assert cache.get("joss_mira_relationship") is not None


def test_prior_dm_text_extracted_from_transcript():
    from hooks.turn_reset import _last_dm_text
    hook_input = {"transcript_messages": [
        {"role": "user", "content": "I open the door."},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Joss, the botanist, looks up."}]},
        {"role": "user", "content": "NO he's a navigator."},
    ]}
    assert "botanist" in _last_dm_text(hook_input)


def test_runner_seeds_from_payload(tmp_path, monkeypatch):
    import json
    from hooks import correction_capture
    from hooks.correction_capture_runner import run
    from hooks.fabrication_bans import FabricationBans

    # Monkeypatch the default extractor so the runner needs no API.
    monkeypatch.setattr(correction_capture, "_default_extractor",
        lambda prior, corr: {"entity": "Joss", "wrong_terms": ["botanist"],
            "correct_fact": "Joss is a navigator.", "failure_mode": "x",
            "participants": ["Joss"]})
    payload = {"prior_dm": "Joss the botanist", "correction": "NO navigator",
               "session_id": "s", "turn": 1,
               "cache_path": str(tmp_path / "c.json"), "bans_path": str(tmp_path / "b.json")}
    f = tmp_path / "in.json"
    f.write_text(json.dumps(payload))
    assert run(str(f)) == 0
    assert len(FabricationBans(tmp_path / "b.json").check_draft("Joss the botanist")) == 1
    assert not f.exists()  # temp payload cleaned up
