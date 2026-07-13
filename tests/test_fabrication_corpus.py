"""Regression: documented failure modes (docs/FAILURE_MODES.md) must be caught by some layer.

Most are caught by the cheap deterministic detectors. Semantic/duration errors like
"lived with for years" are deliberately NOT in the deterministic narration verb set (to
avoid crying wolf); the live system catches those via the fact judge (API) and — permanently
— via the never-again ban once corrected. That class is demonstrated here via the ban layer.
"""
from hooks.fabrication_detectors import check_pet_names, check_tripwires, check_narration_claims
from hooks.fabrication_bans import FabricationBans


def test_petname_by_npc_caught(synthetic_tripwires):
    assert check_pet_names('"As you wish, Moonpetal," the gatewarden murmured.')


def test_non_glider_gliding_caught(synthetic_tripwires):
    assert check_tripwires("Fenwick glided down on her patagia.")


def test_mystic_gift_save_caught():
    assert check_tripwires("The Dissolving Thread demanded a PSY save.")


def test_photosynthete_eating_caught(synthetic_tripwires):
    assert check_tripwires("Thornback ate the lamb Joss had cooked.")


def test_joss_botanist_caught_with_cache():
    # Cache says navigator; draft says botanist -> contradiction in narration (appositive).
    hits = check_narration_claims(
        "Joss, the botanist, unrolled the charts.",
        known_names={"joss"}, cache_facts_blob="joss is a navigator, mira's father.",
    )
    assert hits


def test_lived_with_class_caught_via_never_again_ban(tmp_path):
    # "lived with for years" is activity-ambiguous and intentionally NOT in the narrow
    # narration verb set (avoiding cry-wolf). Once the player corrects it, the never-again
    # ban catches it permanently. Demonstrate that layer (deterministic, no API).
    bans = FabricationBans(tmp_path / "b.json")
    bans.add_ban(
        entity="Amara", wrong_terms=["lived", "with", "varro"],
        correct_fact="Amara managed Varro's correspondence professionally.",
        failure_mode="wrong_relationship", session_id="seed", turn=0,
    )
    hits = bans.check_draft("Amara had lived with Varro for years.")
    assert len(hits) == 1
