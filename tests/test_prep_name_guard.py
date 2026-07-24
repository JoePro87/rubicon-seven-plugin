"""Prep naming guard (2026-07-20): near-homograph cast names are a proven
confusion generator — Tessith vs Tesslyn (2 letters apart, same quorum) was
conflated by player AND DM for a week of Thyricost sessions. validate_prep_file
now warns at authoring time, when renaming is still cheap."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


def _text(*names, reps=3, filler=""):
    return filler + " ".join(f"{n} does a thing." for n in names for _ in range(reps))


def test_flags_tessith_tesslyn():
    out = server._prep_name_collisions(_text("Tessith", "Tesslyn"))
    assert len(out) == 1
    assert "Tessith" in out[0] and "Tesslyn" in out[0]
    assert "NAME COLLISION" in out[0]


def test_flags_close_edit_distance_pair():
    out = server._prep_name_collisions(_text("Marden", "Mardin"))
    assert len(out) == 1


def test_ignores_plural_of_same_word():
    out = server._prep_name_collisions(_text("Petition", "Petitions"))
    assert out == []


def test_ignores_rare_mentions():
    # Names must appear >=3 times to count as cast; drive-by words don't fire.
    out = server._prep_name_collisions(_text("Tessith", "Tesslyn", reps=1))
    assert out == []


def test_ignores_common_capitalised_words():
    out = server._prep_name_collisions(
        _text("There", "These", "Where", "Which", reps=5))
    assert out == []


def test_distinct_names_do_not_fire():
    out = server._prep_name_collisions(_text("Tessith", "Saphora", "Creenash"))
    assert out == []


def test_validate_prep_file_carries_the_warning(tmp_path, monkeypatch):
    prep = tmp_path / "COLLIDE_PREP.md"
    prep.write_text(
        "**Type:** Vault\n\n## ROOM: room_a\n**Name:** A\n**Floor:** 1\n"
        "**Connections:** none\n\n" + _text("Tessith", "Tesslyn", reps=4),
        encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.validate_prep_file("COLLIDE_PREP.md")
    assert "NAME COLLISION" in out


def test_common_words_with_lowercase_uses_excluded():
    """Capitalised words that also appear lowercase are not cast names."""
    txt = _text("Policy", "Polly", reps=4) + " the policy binds. policy is law. a policy."
    out = server._prep_name_collisions(txt)
    assert out == []
