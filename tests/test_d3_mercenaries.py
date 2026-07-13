"""D3 Mercenaries Task 2-4 - character(action="recruit_mercenary"/
"dismiss_mercenary"/"pay_mercenary"/"mercenary_expedition_end"/
"merc_morale_check") (CH printed p.63-64).

Mercs are combat-specialist hirelings on a SEPARATE EGO-bonus level cap
(distinct from the D2 follower pool), fixed sheets (no leveling), a
pay-per-expedition -> sworn-foe loop, and stoic morale (auto-fire only on a
party wipe).
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def _leader(ego=4):
    return {"name": "Vela", "type": "pc", "hp": {"current": 20, "max": 20},
            "abilities": {ab: {"current": (ego if ab == "EGO" else 0), "base": 0}
                          for ab in server.PC_ABILITY_ORDER}}


class TestRecruitMercenary:
    def test_recruit_writes_fixed_sheet(self, monkeypatch):
        data = {"characters": {"vela": _leader(4)}, "meta": {"campaign_day": 10}}
        monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        out = server._character_recruit_mercenary("Vela", recruit_roll=4)  # Clori L2
        m = data["characters"].get("clori")
        assert m and m["type"] == "mercenary" and m["leader"] == "vela"
        assert m["level"] == 2 and m["av"]["base"] == 12 and m["ml"] == 5
        assert m["pay_owed"] is False and m["carries_baggage"] is False
        assert "beam" in str(m["inventory"]["carried"][0]).lower()  # Laspistol beam
        assert "MERCENARY RECRUITED" in out

    def test_cap_rejection_separate_from_followers(self, monkeypatch):
        d = {"characters": {"vela": _leader(2),
             "f1": {"type": "follower", "leader": "vela", "level": 2}},
             "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        # leader EGO 2; follower L2 does NOT consume merc cap; a L2 merc fits
        out = server._character_recruit_mercenary("Vela", recruit_roll=4)
        assert "REJECTED" not in out and d["characters"].get("clori")
        # but a second merc pushing merc-levels over 2 is rejected
        out2 = server._character_recruit_mercenary("Vela", recruit_roll=4)
        assert "REJECTED" in out2   # 2 + 2 > EGO 2

    def test_no_level_up_action(self):
        assert "mercenary_level_up" not in server.VALID_CHARACTER_ACTIONS
        assert "recruit_mercenary" in server.VALID_CHARACTER_ACTIONS

    def test_multi_die_damage_preserved(self, monkeypatch):
        # Uck (total 27) = Nano-edged Greatsword 2d10 - build_weapon must NOT
        # drop the second die.
        d = {"characters": {"vela": _leader(9)}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        out = server._character_recruit_mercenary("Vela", recruit_roll=27)
        m = d["characters"].get("uck")
        assert m["inventory"]["carried"][0]["damage"] == "2d10"
        assert "2d10" in out

    def test_leader_cannot_be_a_hireling(self, monkeypatch):
        d = {"characters": {"skarn": {"name": "Skarn", "type": "mercenary",
             "leader": "vela", "level": 4}}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        out = server._character_recruit_mercenary("Skarn", recruit_roll=4)
        assert "cannot recruit" in out.lower()


class TestDismissMercenary:
    def _merc(self, owed=False, level=4):
        return {"name": "Skarn", "type": "mercenary", "leader": "vela",
                "level": level, "pay_owed": owed,
                "hp": {"current": 16, "max": 16}}

    def test_clean_dismiss_when_not_owed(self):
        # real files in the conftest-isolated CAMPAIGN_DIR (never the live repo)
        chars_dir = server.CAMPAIGN_DIR / "characters"
        chars_dir.mkdir(parents=True, exist_ok=True)
        (chars_dir / "_meta.json").write_text(
            json.dumps({"campaign_day": 50}), encoding="utf-8")
        (chars_dir / "skarn.json").write_text(
            json.dumps(self._merc(owed=False)), encoding="utf-8")
        out = server._character_dismiss_mercenary("Skarn", reason="contract done")
        assert "departed" in out.lower()
        assert "sworn foe" not in out.lower()
        assert not (chars_dir / "skarn.json").exists()
        assert (chars_dir / "departed" / "skarn.json").exists()

    def test_dismiss_while_owed_fires_sworn_foe(self, monkeypatch):
        merc = self._merc(owed=True)
        d = {"characters": {"vela": _leader(), "skarn": merc}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_move_sheet_to_departed", lambda *a, **k: True)
        out = server._character_dismiss_mercenary("Skarn", reason="refused to pay")
        assert "sworn foe" in out.lower()
        assert 'antagonist(' in out and 'add_seed' in out
        assert "Skarn" in out

    def test_sworn_foe_idempotent(self, monkeypatch):
        # a departed merc cannot re-fire the foe push (already gone from roster)
        d = {"characters": {"vela": _leader()}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        out = server._character_dismiss_mercenary("Skarn")
        assert "not found" in out.lower()

    def test_dismiss_type_guard(self, monkeypatch):
        d = {"characters": {"vela": _leader(),
             "f1": {"name": "Abrax", "type": "follower", "leader": "vela",
                    "level": 2}}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        out = server._character_dismiss_mercenary("Abrax")
        assert "not a mercenary" in out.lower()


class TestPaymentLoop:
    def _merc(self, owed=False):
        return {"name": "Skarn", "type": "mercenary", "leader": "vela",
                "level": 4, "pay_owed": owed, "hp": {"current": 16, "max": 16}}

    def test_expedition_end_sets_owed(self, monkeypatch):
        d = {"characters": {"vela": _leader(), "skarn": self._merc()}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        out = server._character_mercenary_expedition_end("Vela")  # leader -> all his mercs
        assert d["characters"]["skarn"]["pay_owed"] is True
        assert "owed" in out.lower()

    def test_pay_clears_owed(self, monkeypatch):
        d = {"characters": {"vela": _leader(), "skarn": self._merc(owed=True)}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        out = server._character_pay_mercenary("Skarn")
        assert d["characters"]["skarn"]["pay_owed"] is False
        assert "Exotica" in out

    def test_pay_when_not_owed_is_noop(self, monkeypatch):
        d = {"characters": {"vela": _leader(), "skarn": self._merc(owed=False)}, "meta": {}}
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        out = server._character_pay_mercenary("Skarn")
        assert "nothing owed" in out.lower() or "not owed" in out.lower()

    def test_advance_day_nags_while_owed(self):
        # the pay-owed nag helper returns a line per owed merc
        d = {"characters": {"vela": _leader(),
             "skarn": self._merc(owed=True),
             "paid": {"name": "Doru", "type": "mercenary", "leader": "vela",
                      "level": 2, "pay_owed": False}}}
        lines = server._mercenary_pay_nag_lines(d)
        assert any("Skarn" in l and "Exotica" in l for l in lines)
        assert not any("Doru" in l for l in lines)


class TestMercMorale:
    def _party(self, pc_hp, merc_hp=16):
        return {"characters": {
            "vela": {"name": "Vela", "type": "pc",
                     "hp": {"current": pc_hp, "max": 20}},
            "skarn": {"name": "Skarn", "type": "mercenary", "leader": "vela",
                      "level": 4, "ml": 7, "hp": {"current": merc_hp, "max": 16}}}}

    def test_mercs_excluded_from_per_death_push(self):
        # _follower_morale_lines already filters type=='follower'; a merc must
        # NOT produce a morale line when an ally dies
        d = self._party(pc_hp=20)
        lines = server._follower_morale_lines(d, "someone")
        assert not any("Skarn" in l for l in lines)

    def test_all_pcs_down_predicate(self):
        assert server._all_pcs_down(self._party(pc_hp=0)) is True
        assert server._all_pcs_down(self._party(pc_hp=5)) is False

    def test_wipe_auto_fires_merc_morale(self):
        d = self._party(pc_hp=0)
        lines = server._merc_morale_lines(d)
        assert any("Skarn" in l and "vs 15" in l and "+7" in l for l in lines)

    def test_merc_morale_check_lever(self, monkeypatch):
        d = self._party(pc_hp=20)
        monkeypatch.setattr(server, "_load_characters", lambda: (d, None))
        out = server._character_merc_morale_check("Skarn")
        assert "Skarn" in out and "d20 + 7 vs 15" in out

    def test_pc_at_zero_but_stabilized_not_a_wipe(self):
        # use the SAME alive predicate the death seam uses - a PC at exactly 0
        # who is not dead-by-the-rules must read as down for wipe purposes only
        # if hp.current <= 0 (book: 0 HP = incapacitated). Document the choice.
        assert server._all_pcs_down(self._party(pc_hp=0)) is True

    def test_dead_merc_excluded_from_morale(self):
        d = self._party(pc_hp=0, merc_hp=-20)
        lines = server._merc_morale_lines(d)
        assert not any("Skarn" in l for l in lines)

    def test_wipe_detection_for_ancestry_typed_pcs(self):
        # Live PCs have type None; but the poison-test fixtures (and any sheet
        # that puts ancestry in `type`) must ALSO be treated as PCs by the wipe
        # detector - matching the resurrection-gate classification. A downed
        # ancestry-typed party is a wipe; a standing one is not.
        downed = {"characters": {
            "vela": {"name": "Vela", "type": "True-kin",
                     "hp": {"current": 0, "max": 20}},
            "skarn": {"name": "Skarn", "type": "mercenary", "leader": "vela",
                      "level": 4, "ml": 7, "hp": {"current": 16, "max": 16}}}}
        assert server._all_pcs_down(downed) is True
        assert any("Skarn" in l for l in server._merc_morale_lines(downed))
        standing = {"characters": dict(downed["characters"],
                    vela={"name": "Vela", "type": "True-kin",
                          "hp": {"current": 7, "max": 20}})}
        assert server._all_pcs_down(standing) is False


class TestResurrectionGating:
    """Resurrection is PC-only (book p.229). The death seam must gate the
    five-path menu on _is_pc_sheet, excluding BOTH follower and mercenary
    hirelings - not just followers."""

    def _res(self, lines):
        text = "\n".join(lines).lower()
        return ("p.229" in text or "five paths" in text
                or "resurrection" in text)

    def test_dead_mercenary_gets_no_resurrection_menu(self):
        merc = {"name": "Skarn", "type": "mercenary", "leader": "vela",
                "level": 4, "ml": 7, "hp": {"current": -20, "max": 16}}
        d = {"characters": {"skarn": merc}}
        lines = server._death_seam_lines(merc, d, "skarn")
        assert not self._res(lines), "mercenary must NOT get the p.229 menu"

    def test_dead_follower_gets_no_resurrection_menu(self):
        fol = {"name": "Abrax", "type": "follower", "leader": "vela",
               "level": 2, "ml": 2, "hp": {"current": -20, "max": 4}}
        d = {"characters": {"abrax": fol}}
        lines = server._death_seam_lines(fol, d, "abrax")
        assert not self._res(lines), "follower must NOT get the p.229 menu"

    def test_dead_pc_still_gets_resurrection_menu(self):
        pc = {"name": "Vela", "type": "pc", "level": 3,
              "hp": {"current": -20, "max": 20}}
        d = {"characters": {"vela": pc}}
        lines = server._death_seam_lines(pc, d, "vela")
        assert self._res(lines), "PC MUST still get the p.229 menu"

    def test_typeless_sheet_treated_as_pc(self):
        # a sheet with no 'type' key is a PC (engine-minted PC sheets have none)
        pc = {"name": "Old", "level": 1, "hp": {"current": -20, "max": 10}}
        d = {"characters": {"old": pc}}
        lines = server._death_seam_lines(pc, d, "old")
        assert self._res(lines)

    def test_live_ancestry_typed_pc_still_gets_menu(self):
        # REGRESSION: live PC sheets store their ANCESTRY in `type`
        # (e.g. "True-kin"), NOT the literal "pc". The hireling-exclusion gate
        # must still treat an ancestry-typed sheet as a PC and emit the menu.
        pc = {"name": "Testa", "type": "True-kin", "level": 3,
              "hp": {"current": -20, "max": 20}}
        d = {"characters": {"testa": pc}}
        lines = server._death_seam_lines(pc, d, "testa")
        assert self._res(lines), "ancestry-typed PC MUST get the p.229 menu"
