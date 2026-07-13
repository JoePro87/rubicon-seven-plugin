"""Tests for followers.py - image-verified recruitment table + cap helper.

Band-edge assertions below were read directly off
docs/superpowers/plans/data/spark_pages/followers-recruit-a.png.
"""

import pytest

import followers


REQUIRED_FIELDS = {"name", "level", "hp", "av", "ml", "attack", "description"}


# ---------------------------------------------------------------- table shape

def test_all_totals_0_to_30_present():
    assert set(followers.RECRUIT_TABLE.keys()) == set(range(31))


def test_every_row_has_all_fields():
    for total, row in followers.RECRUIT_TABLE.items():
        assert REQUIRED_FIELDS <= set(row.keys()), total
        assert isinstance(row["attack"], dict) and "name" in row["attack"] \
            and "damage" in row["attack"], total


def test_band_0_1_identical_rows():
    assert followers.RECRUIT_TABLE[0] == followers.RECRUIT_TABLE[1]
    assert followers.RECRUIT_TABLE[0]["name"] == "Herta"


def test_keys_0_and_1_are_distinct_objects():
    # Mutating one must not bleed into the other.
    assert followers.RECRUIT_TABLE[0] is not followers.RECRUIT_TABLE[1]


# ------------------------------------------------------------ banded columns
# Bands read off the image's cell borders (not assumed even splits):
# LEVEL/HP: 0-10 L0/1HP | 11-15 L1/4HP | 16-25 L2/8HP | 26-30 L3/12HP
# AV:       0-10 -> 10  | 11-20 -> 11  | 21-30 -> 12
# ML:       0-5 +0 | 6-10 +1 | 11-15 +2 | 16-20 +3 | 21-25 +4 | 26-30 +5

@pytest.mark.parametrize("total,level,hp", [
    (0, 0, 1), (5, 0, 1), (10, 0, 1),       # level-0 band incl. both edges
    (11, 1, 4), (13, 1, 4), (15, 1, 4),     # level-1 band edges
    (16, 2, 8), (20, 2, 8), (25, 2, 8),     # level-2 band edges
    (26, 3, 12), (28, 3, 12), (30, 3, 12),  # level-3 band edges
])
def test_level_hp_bands(total, level, hp):
    row = followers.RECRUIT_TABLE[total]
    assert row["level"] == level
    assert row["hp"] == hp


@pytest.mark.parametrize("total,av", [
    (0, 10), (10, 10),    # AV 10 band edges
    (11, 11), (20, 11),   # AV 11 band edges
    (21, 12), (30, 12),   # AV 12 band edges
])
def test_av_bands(total, av):
    assert followers.RECRUIT_TABLE[total]["av"] == av


@pytest.mark.parametrize("total,ml", [
    (0, 0), (5, 0),
    (6, 1), (10, 1),
    (11, 2), (15, 2),
    (16, 3), (20, 3),
    (21, 4), (25, 4),
    (26, 5), (30, 5),
])
def test_ml_bands(total, ml):
    assert followers.RECRUIT_TABLE[total]["ml"] == ml


def test_av_band_is_not_aligned_with_level_band():
    # The image shows AV 11 spanning 11-20 while Level 2 starts at 16:
    # totals 16-20 are Level 2 but still AV 11.
    row = followers.RECRUIT_TABLE[18]
    assert row["level"] == 2 and row["av"] == 11


# ------------------------------------------------------------ attack parsing

def test_plain_d4_attack_has_no_extras():
    attack = followers.RECRUIT_TABLE[4]["attack"]  # Wellet, Heavy Stick (d4)
    assert attack == {"name": "Heavy Stick", "damage": "d4"}


def test_volt_baton_electrical():
    attack = followers.RECRUIT_TABLE[24]["attack"]
    assert attack["name"] == "Volt Baton"
    assert attack["damage"] == "d6"
    assert attack["damage_type"] == "electrical"
    assert "tags" not in attack and "note" not in attack


def test_grenades_blast_with_note():
    attack = followers.RECRUIT_TABLE[29]["attack"]
    assert attack["name"] == "3 Ancient Grenades"
    assert attack["damage"] == "d8"
    assert attack["tags"] == ["blast"]
    assert attack["note"] == "50% chance won't detonate"


def test_lasrifle_beam():
    attack = followers.RECRUIT_TABLE[30]["attack"]
    assert attack["name"] == "Lasrifle"
    assert attack["damage"] == "d8"
    assert attack["damage_type"] == "beam"


def test_apostrophe_names_are_ascii():
    assert followers.RECRUIT_TABLE[18]["attack"]["name"] == "Shepherd's Staff"
    assert followers.RECRUIT_TABLE[28]["attack"]["name"] == "Nomad's Rifle"
    for row in followers.RECRUIT_TABLE.values():
        for value in (row["name"], row["description"], row["attack"]["name"]):
            value.encode("ascii")  # raises if non-ASCII slipped in


# -------------------------------------------------------------- roll_recruit

def test_roll_recruit_clamps_low():
    total, row = followers.roll_recruit(lambda a, b: 1, -5)
    assert total == 0
    assert row == followers.RECRUIT_TABLE[0]


def test_roll_recruit_clamps_high():
    total, row = followers.roll_recruit(lambda a, b: 20, 15)
    assert total == 30
    assert row["name"] == "Audrew"


def test_roll_recruit_plain_sum():
    total, row = followers.roll_recruit(lambda a, b: 14, 2)
    assert total == 16
    assert row["name"] == "Longdream"


def test_roll_recruit_none_ego_treated_as_zero():
    total, row = followers.roll_recruit(lambda a, b: 7, None)
    assert total == 7
    assert row["name"] == "Lusaki"


# ------------------------------------------------------- follower_level_cap

def _roster():
    return {
        "mira": {"abilities": {"EGO": {"current": 3, "base": 3}}},
        "kess": {"abilities": {"EGO": 2}},  # int-shaped EGO
        "herta": {"type": "follower", "leader": "mira", "level": 1},
        "abrax": {"type": "follower", "leader": "mira", "level": 2},
        "teleo": {"type": "follower", "leader": "kess", "level": 0},
        "npc": {"type": "npc", "leader": "mira", "level": 5},   # wrong type
        "stray": {"type": "follower", "leader": "kess", "level": 1},
    }


def test_cap_dict_shaped_ego_and_used_sum():
    cap, used = followers.follower_level_cap(_roster(), "mira")
    assert cap == 3
    assert used == 3  # herta 1 + abrax 2; npc excluded despite leader match


def test_cap_int_shaped_ego_and_leader_filter():
    cap, used = followers.follower_level_cap(_roster(), "kess")
    assert cap == 2
    assert used == 1  # teleo 0 + stray 1; mira's followers excluded


def test_cap_missing_leader():
    cap, used = followers.follower_level_cap(_roster(), "nobody")
    assert cap == 0 and used == 0


def test_cap_leader_without_ego_key():
    cap, used = followers.follower_level_cap({"bare": {}}, "bare")
    assert cap == 0 and used == 0
