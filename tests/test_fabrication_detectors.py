"""Tests for deterministic fabrication detectors (pet-names, tripwires, narration claims).

Campaign pet-names/tripwires load from the campaign dir's fabrication_tripwires.json
(see the synthetic_tripwires fixture in conftest — invented characters only)."""
from hooks.fabrication_detectors import check_pet_names, check_tripwires


# --- Forbidden pet-names (bond-names no NPC may use) ---

def test_petname_in_dialogue_is_flagged(synthetic_tripwires):
    text = 'The gatewarden bowed. "As you wish, Moonpetal."'
    hits = check_pet_names(text)
    assert any("moonpetal" in h.lower() for h in hits)


def test_petname_in_bond_text_is_allowed(synthetic_tripwires):
    # *...* is private bond speech — the sanctioned context.
    text = "*Sleep well, Moonpetal.*"
    assert check_pet_names(text) == []


def test_no_petname_no_flag(synthetic_tripwires):
    assert check_pet_names('"Good morning, Warden," he said.') == []


def test_no_campaign_file_means_no_petname_guards(tmp_path, monkeypatch):
    # Fail-open: without a campaign rules file there are no pet-name guards.
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))
    assert check_pet_names('"As you wish, Moonpetal."') == []


# --- Tripwires ---

def test_glider_tripwire_is_flagged(synthetic_tripwires):
    hits = check_tripwires("Fenwick spread her patagia and glided down to the deck.")
    assert any("fenwick" in h.lower() and "glid" in h.lower() for h in hits)


def test_actual_glider_is_allowed(synthetic_tripwires):
    assert check_tripwires("Thornback spread her patagia and glided down.") == []


def test_mystic_gift_save_is_flagged():
    # Built-in book-rule tripwire — needs no campaign file.
    hits = check_tripwires("The Dissolving Thread required a PSY save to take hold.")
    assert any("mystic" in h.lower() or "save" in h.lower() for h in hits)


def test_photosynthete_eating_is_flagged(synthetic_tripwires):
    hits = check_tripwires("Thornback ate the bread slowly.")
    assert any("thornback" in h.lower() for h in hits)


def test_neutral_text_no_tripwire(synthetic_tripwires):
    assert check_tripwires("The wind moved across the salt flats.") == []


def test_synth_drinking_is_flagged(synthetic_tripwires):
    hits = check_tripwires("Cogsworth drank from the flask.")
    assert any("cogsworth" in h.lower() or "synth" in h.lower() for h in hits)


def test_synth_calculating_is_allowed(synthetic_tripwires):
    assert check_tripwires("Cogsworth calculated the trajectory.") == []


def test_photosynthete_drinking_is_flagged(synthetic_tripwires):
    hits = check_tripwires("Thornback sipped the broth.")
    assert any("thornback" in h.lower() for h in hits)


def test_cross_sentence_subject_action_does_not_fire(synthetic_tripwires):
    # Fenwick and the gliding are in DIFFERENT sentences — must not fire.
    assert check_tripwires("Thornback glided down to the deck. Fenwick watched from the rail.") == []


def test_malformed_campaign_entry_is_skipped(tmp_path, monkeypatch):
    # A bad regex entry must be skipped, not crash the gate.
    import json
    (tmp_path / "fabrication_tripwires.json").write_text(json.dumps({
        "tripwires": [
            {"subject": "([unclosed", "context": "x", "message": "bad"},
            {"subject": r"\bthornback\b", "context": r"\bate\b", "message": "TRIPWIRE: ok"},
        ]}), encoding="utf-8")
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))
    assert check_tripwires("Thornback ate the bread.") == ["TRIPWIRE: ok"]


# --- Narration claims ---

from hooks.fabrication_detectors import check_narration_claims


def test_narration_job_claim_about_named_char_flagged():
    # "the botanist Joss" in narration, with Joss a known canon name, no cache support.
    hits = check_narration_claims(
        "Joss, the botanist, set down his charts.",
        known_names={"joss", "amara"},
        cache_facts_blob="joss is a navigator and mira's father.",
    )
    assert any("joss" in h.lower() for h in hits)


def test_narration_claim_supported_by_cache_not_flagged():
    hits = check_narration_claims(
        "Joss, the navigator, set down his charts.",
        known_names={"joss"},
        cache_facts_blob="joss is a navigator and mira's father.",
    )
    assert hits == []


def test_narration_relationship_about_unknown_name_not_flagged():
    # No named canon character involved -> free invention, no flag.
    hits = check_narration_claims(
        "The old trader married a dune-witch, they said.",
        known_names={"joss", "amara"},
        cache_facts_blob="",
    )
    assert hits == []


def test_narration_claim_inside_dialogue_ignored():
    # Dialogue is handled by the dialogue scanner; narration scanner skips quotes.
    hits = check_narration_claims(
        '"Joss was a botanist," Mira lied.',
        known_names={"joss"},
        cache_facts_blob="",
    )
    assert hits == []


def test_narration_activity_verbs_do_not_cry_wolf():
    party = {"brek", "mira", "kess", "bugsie", "saphora", "roscar", "tesslyn"}
    benign = [
        "Kess trained the recruits at dawn.",
        "Bugsie knew the airflow better than anyone.",
        "Saphora worked with the engineers on the conduit.",
        "Mira met the council in the high chamber.",
        "Kess followed the trail north.",
        "Kess raised her crossbow.",
        "His expression betrayed nothing.",
    ]
    for s in benign:
        assert check_narration_claims(s, known_names=party, cache_facts_blob="") == [], s


def test_narration_familial_claim_flags():
    hits = check_narration_claims("Joss married a dune-witch.",
                                  known_names={"joss"}, cache_facts_blob="")
    assert any("joss" in h.lower() for h in hits)


def test_narration_appositive_structural_nouns_do_not_cry_wolf():
    party = {"brek", "mira", "kess", "bugsie", "saphora", "roscar", "tesslyn", "joss", "amara"}
    benign = [
        "The wind Joss felt was cold.",
        "Bugsie, the smallest of them, darted off.",
        "She crossed the bridge Saphora had built.",
        "Over the dunes Kess ran.",
    ]
    for s in benign:
        assert check_narration_claims(s, known_names=party, cache_facts_blob="") == [], s


# --- Combat mechanics leak detector (Iron Law 6 backstop) ---

from hooks.fabrication_detectors import check_combat_mechanics


def test_leaked_damage_type_flagged():
    assert check_combat_mechanics("Roscar fires, damage_type piercing, and the zorse reels.")


def test_leaked_to_hit_flagged():
    assert check_combat_mechanics("He needed a to_hit of 15.")
    assert check_combat_mechanics("She rolls 18 to-hit against the raider.")


def test_leaked_rolls_number_flagged():
    # Mechanically-anchored leak forms must flag.
    assert check_combat_mechanics("Roscar rolls a 18 and the shot lands.")
    assert check_combat_mechanics("Roscar rolled 12 vs the raider.")
    assert check_combat_mechanics("rolls 18 to-hit against the raider")
    assert check_combat_mechanics("The grenade is a 3d12 blast.")


def test_physical_rolling_not_flagged():
    # Critical anti-false-positive guard: ordinary physical rolling is NOT a dice leak.
    benign = [
        "the cart rolls 3 feet down the slope",
        "she rolls 3 knucklebones across the table",
        "Saphora rolls 20 feet of cable across the floor",
        "the crowd rolls 5 deep around the plaza",
    ]
    for s in benign:
        assert check_combat_mechanics(s) == [], s


def test_leaked_hp_fraction_flagged():
    assert check_combat_mechanics("The zorse drops to 12/29 HP.")


def test_leaked_engine_tags_flagged():
    assert check_combat_mechanics("engine_tags: psyche-suppressant applied.")


def test_clean_combat_prose_not_flagged():
    # the target style from the spec — pure narrative, zero mechanics
    clean = ("Roscar sights down the rail-gun and fires. The shot punches through the "
             "zorse's plating -- it lurches, still standing, a dark wet line opening along its flank.")
    assert check_combat_mechanics(clean) == []
