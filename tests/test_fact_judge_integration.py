"""Integration tests for fabrication checks wired into the Gate (validate_prose)."""


def test_vp_check_fabrication_bans_flags_banned_claim(tmp_path, monkeypatch):
    import server
    from hooks.fabrication_bans import FabricationBans
    bans_path = tmp_path / "bans.json"
    FabricationBans(bans_path).add_ban(
        entity="Joss", wrong_terms=["botanist"], correct_fact="Joss is a navigator, Mira's father.",
        failure_mode="wrong_relationship", session_id="s1", turn=1)
    monkeypatch.setattr(server, "_FABRICATION_BANS_PATH", bans_path, raising=False)
    monkeypatch.setattr(server, "_get_fabrication_bans",
                        lambda: FabricationBans(bans_path), raising=False)

    violations = server._vp_check_fabrication_bans("Joss, the botanist, smiled.")
    assert any("NEVER-AGAIN" in v and "navigator" in v for v in violations)


def test_vp_check_fabrication_bans_clean_when_no_match(tmp_path, monkeypatch):
    import server
    from hooks.fabrication_bans import FabricationBans
    bans_path = tmp_path / "bans.json"
    monkeypatch.setattr(server, "_get_fabrication_bans",
                        lambda: FabricationBans(bans_path), raising=False)
    assert server._vp_check_fabrication_bans("Joss studied the stars.") == []


def test_vp_check_petnames_flags_petname_in_dialogue(synthetic_tripwires):
    import server
    v = server._vp_check_petnames('"As you wish, Moonpetal," the gatewarden said.')
    assert any("PET-NAME" in x for x in v)


def test_vp_check_tripwires_flags_non_glider_gliding(synthetic_tripwires):
    import server
    v = server._vp_check_tripwires("Fenwick glided across the deck on her patagia.")
    assert any("TRIPWIRE" in x for x in v)


def test_vp_check_petnames_allows_bond_text(synthetic_tripwires):
    import server
    # A pet-name inside *bond* italics is the sanctioned private channel — must NOT flag.
    assert server._vp_check_petnames("*Goodnight, Moonpetal.*") == []


def test_vp_check_narration_claims_flags_familial_about_party(monkeypatch):
    import server
    # Isolate from the real distillation cache so the test is deterministic.
    monkeypatch.setattr(server, "_vp_cache_facts_blob", lambda text="": "", raising=False)
    # Party names now derive from the live roster; supply one for determinism.
    monkeypatch.setattr(server, "_vp_party_names", lambda: {"Mira"}, raising=False)
    # Mira is a party member; "married" is a familial verb; empty answer key.
    hits = server._vp_check_narration_claims("Mira married a stranger from the dunes.")
    assert any("NARRATION CLAIM" in h for h in hits)


def test_fact_judge_returns_violations_from_payload(monkeypatch):
    import server
    monkeypatch.setattr(server, "_vp_fact_judge_raw", lambda text, answer_key: {
        "violations": [
            {"quote": "Joss, the botanist", "contradicts": "Joss is a navigator",
             "confidence": "high"},
        ]
    }, raising=False)
    out = server._vp_call_fact_judge("Joss, the botanist, smiled.", "Joss is a navigator.")
    assert any("FACT" in v and "botanist" in v for v in out)


def test_fact_judge_low_confidence_dropped(monkeypatch):
    import server
    monkeypatch.setattr(server, "_vp_fact_judge_raw", lambda text, answer_key: {
        "violations": [{"quote": "maybe", "contradicts": "x", "confidence": "low"}]
    }, raising=False)
    assert server._vp_call_fact_judge("text", "key") == []


def test_fact_judge_fails_open(monkeypatch):
    import server
    def boom(text, answer_key):
        raise RuntimeError("no api")
    monkeypatch.setattr(server, "_vp_fact_judge_raw", boom, raising=False)
    assert server._vp_call_fact_judge("text", "key") == []
