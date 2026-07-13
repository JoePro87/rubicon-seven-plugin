"""D3 Mercenaries - certified d20+EGO recruit table (CH printed p.64).

Spec: docs/superpowers/specs/2026-06-13-d3-mercenaries-design.md
Ground truth: docs/superpowers/plans/data/merc_pages/VERIFICATION_NOTES.md
(image+position-verified) and merc-table.png.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mercenaries as merc
import followers as fol


class TestMercTablePins:
    def test_all_totals_0_30_present(self):
        assert sorted(merc.RECRUIT_TABLE) == list(range(0, 31))

    def test_zero_one_band_identical(self):
        assert merc.RECRUIT_TABLE[0] == merc.RECRUIT_TABLE[1]
        assert merc.RECRUIT_TABLE[0]["name"] == "Ekateria"

    def test_level_hp_bands(self):
        # L2/8 0-4 | L3/12 5-8 | L4/16 9-12 | L5/20 13-16 | L6/24 17-20
        # L7/28 21-24 | L8/32 25-28 | L9/36 29-30  (VERIFICATION_NOTES)
        def lh(t):
            r = merc.RECRUIT_TABLE[t]
            return (r["level"], r["hp"])
        assert lh(0) == (2, 8) and lh(4) == (2, 8)
        assert lh(5) == (3, 12) and lh(8) == (3, 12)
        assert lh(9) == (4, 16) and lh(12) == (4, 16)
        assert lh(13) == (5, 20) and lh(16) == (5, 20)
        assert lh(17) == (6, 24) and lh(20) == (6, 24)
        assert lh(21) == (7, 28) and lh(24) == (7, 28)
        assert lh(25) == (8, 32) and lh(28) == (8, 32)
        assert lh(29) == (9, 36) and lh(30) == (9, 36)

    def test_av_bands_misalign_with_level(self):
        # AV 12:0-5, 13:6-10, 14:11-15, 15:16-20, 16:21-25, 17:26-28, 18:29, 19:30
        for t, av in [(0, 12), (5, 12), (6, 13), (10, 13), (11, 14), (15, 14),
                      (16, 15), (20, 15), (21, 16), (25, 16), (26, 17),
                      (28, 17), (29, 18), (30, 19)]:
            assert merc.RECRUIT_TABLE[t]["av"] == av, t

    def test_ml_bands(self):
        # +5:0-5, +6:6-10, +7:11-15, +8:16-20, +9:21-25, +10:26-30
        for t, ml in [(0, 5), (5, 5), (6, 6), (10, 6), (11, 7), (15, 7),
                      (16, 8), (20, 8), (21, 9), (25, 9), (26, 10), (30, 10)]:
            assert merc.RECRUIT_TABLE[t]["ml"] == ml, t

    def test_verbatim_attack_tags(self):
        t = merc.RECRUIT_TABLE
        assert t[4]["attack"]["name"] == "Laspistol"
        assert t[4]["attack"]["damage_type"] == "beam"
        assert t[6]["attack"]["name"] == "Venomous Knife"
        assert "TOX" in t[6]["attack"].get("tags", [])
        assert t[24]["attack"]["name"] == "Tesla Cannon"
        assert "auto-hit" in (t[24]["attack"].get("note") or "").lower()
        assert t[25]["attack"]["damage"] == "d12"
        assert "piercing" in t[25]["attack"].get("tags", [])
        assert t[27]["attack"]["damage"] == "2d10"           # Nano-edged Greatsword
        assert "hypergeometric" in t[30]["attack"].get("tags", [])

    def test_band_coverage_no_gaps(self):
        # every total 0-30 has level 2-9, av 12-19, ml 5-10
        for total, row in merc.RECRUIT_TABLE.items():
            assert 2 <= row["level"] <= 9
            assert 12 <= row["av"] <= 19
            assert 5 <= row["ml"] <= 10
            assert isinstance(row["attack"]["damage"], str)


class TestRollAndCap:
    def test_roll_clamps(self):
        assert merc.roll_recruit(lambda a, b: 1, -10)[0] == 0
        assert merc.roll_recruit(lambda a, b: 20, 50)[0] == 30
        total, row = merc.roll_recruit(lambda a, b: 10, 5)
        assert total == 15 and row is merc.RECRUIT_TABLE[15]

    def test_mercenary_cap_counts_only_mercs(self):
        chars = {
            "leader": {"abilities": {"EGO": {"current": 4}}},
            "m1": {"type": "mercenary", "leader": "leader", "level": 2},
            "f1": {"type": "follower", "leader": "leader", "level": 3},
        }
        cap, used = merc.mercenary_level_cap(chars, "leader")
        assert cap == 4
        assert used == 2          # the follower's Level 3 does NOT count

    def test_separate_pools_followers_unaffected(self):
        chars = {
            "leader": {"abilities": {"EGO": {"current": 4}}},
            "m1": {"type": "mercenary", "leader": "leader", "level": 4},
            "f1": {"type": "follower", "leader": "leader", "level": 3},
        }
        assert merc.mercenary_level_cap(chars, "leader")[1] == 4
        assert fol.follower_level_cap(chars, "leader")[1] == 3   # unchanged

    def test_cap_int_ego_shape(self):
        chars = {"leader": {"abilities": {"EGO": 3}}}
        assert merc.mercenary_level_cap(chars, "leader") == (3, 0)
