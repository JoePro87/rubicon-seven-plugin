from pathlib import Path

import ceruline_reader as cr

_CAMP = Path(__file__).resolve().parent.parent.parent / "rubicon-seven-campaign"

FIXTURE = """# CERULINE ARCOLOGY — Player Reference

## TIER 1: FOUNDATION LEVEL

### Root Garden
Cathedral-like chambers.

**NPCs:**
- **Verdant-Reaches-Stone (Reaches)** — Neobloom elder, 17-year tenure.
- **Saphora** — Lives here since Day 42.

## TIER 2: CULTIVATION DISTRICT

### Garden Hall
Botanical courtyard.

**NPCs:**
- **Ted (VL5 "Architect-Prime")** — Primary custodian
- **Jim, Melinda, Bear** — Other custodians

## TIER 10: NOBLE QUARTER / UPPER RESIDENTIAL

### House Vane Tower
Eastern quarter tower.

**Residents:** Matriarch Amara Vane (Executrix)

### House Azure Estate
Blue-veined marble.

**Representative:** Scholar Tiberius (converted Day 74)

### Herbed Bread Bakery
Corner eatery.

**Proprietor:** Four-armed cacogen (30+ years)

## KEY NPCS

### Master Surgeon Brant
**Location:** Surgeon's Guild (Tier 11)

Professional demeanor.
"""


def test_tiers_parsed_in_order():
    tiers = cr.parse_ceruline(FIXTURE)
    nums = [t["num"] for t in tiers]
    assert nums == [1, 2, 10, 11]  # 11 created by the KEY-NPCS (Tier 11) assignment


def test_short_labels():
    by_num = {t["num"]: t["short"] for t in cr.parse_ceruline(FIXTURE)}
    assert by_num[2] == "Cultivation"
    assert by_num[10] == "Noble Quarter"


def test_npc_bullets_capture_name_and_location():
    tiers = cr.parse_ceruline(FIXTURE)
    t1 = next(t for t in tiers if t["num"] == 1)
    people = {p["name"]: p["location"] for p in t1["people"]}
    assert people["Verdant-Reaches-Stone"] == "Root Garden"
    assert people["Saphora"] == "Root Garden"


def test_bullet_name_strips_trailing_parenthetical():
    tiers = cr.parse_ceruline(FIXTURE)
    t2 = next(t for t in tiers if t["num"] == 2)
    names = [p["name"] for p in t2["people"]]
    assert "Ted" in names                    # "(VL5 ...)" stripped
    assert "Jim, Melinda, Bear" in names     # comma-group kept as one lean line


def test_role_lines_capture_named_people():
    t10 = {p["name"]: p["location"] for t in cr.parse_ceruline(FIXTURE) if t["num"] == 10 for p in t["people"]}
    assert t10["Matriarch Amara Vane"] == "House Vane Tower"
    assert t10["Scholar Tiberius"] == "House Azure Estate"


def test_role_line_descriptor_without_proper_name_skipped():
    tiers = cr.parse_ceruline(FIXTURE)
    t10 = [p["name"] for t in tiers if t["num"] == 10 for p in t["people"]]
    assert not any("cacogen" in n.lower() for n in t10)  # "Four-armed cacogen" not a roster entry


def test_key_npcs_assigned_to_parenthetical_tier():
    tiers = cr.parse_ceruline(FIXTURE)
    t11 = next(t for t in tiers if t["num"] == 11)
    people = {p["name"]: p["location"] for p in t11["people"]}
    assert people["Master Surgeon Brant"] == "Surgeon's Guild"


def test_tier_list_lean():
    tiers = cr.parse_ceruline(FIXTURE)
    out = cr.tier_list(tiers)
    assert "which tier?" in out
    assert "Cultivation" in out and "Noble Quarter" in out


def test_resolve_focus_by_short_label():
    tiers = cr.parse_ceruline(FIXTURE)
    assert cr.match_tier("Cultivation", tiers)["num"] == 2
    assert cr.match_tier("noble quarter", tiers)["num"] == 10


def test_resolve_focus_by_number():
    tiers = cr.parse_ceruline(FIXTURE)
    assert cr.match_tier("10", tiers)["num"] == 10
    assert cr.match_tier("T10", tiers)["num"] == 10
    assert cr.match_tier("tier 1", tiers)["num"] == 1


def test_resolve_focus_unknown_returns_none():
    assert cr.match_tier("Atlantis", cr.parse_ceruline(FIXTURE)) is None


def test_card_lean_one_line_per_person():
    tiers = cr.parse_ceruline(FIXTURE)
    card = cr.build_tier_card(next(t for t in tiers if t["num"] == 10))
    assert "CERULINE — Noble Quarter (T10) — REFERENCE roster" in card
    assert "Matriarch Amara Vane — House Vane Tower" in card
    assert "Scholar Tiberius — House Azure Estate" in card
    # lean: no role/standing tail on the person lines
    assert "Executrix" not in card and "converted" not in card


def test_card_dead_overlay_marks_person():
    tiers = cr.parse_ceruline(FIXTURE)
    card = cr.build_tier_card(next(t for t in tiers if t["num"] == 10),
                              npc_overlay={"Scholar Tiberius": {"status": "DEAD", "day": 91}})
    assert "Scholar Tiberius — †dead since Day 91" in card


def test_is_ceruline():
    assert cr.is_ceruline("Ceruline")
    assert cr.is_ceruline("the arcology")
    assert cr.is_ceruline("ceruline arcology")
    assert not cr.is_ceruline("Tessik Well")


def test_who_card_dispatch(tmp_path):
    (tmp_path / cr.CERULINE_FILE).write_text(FIXTURE, encoding="utf-8")
    no_focus = cr.who_card(tmp_path, focus=None)
    assert "which tier?" in no_focus
    one = cr.who_card(tmp_path, focus="Noble Quarter")
    assert "(T10)" in one
    miss = cr.who_card(tmp_path, focus="Atlantis")
    assert 'No tier "Atlantis"' in miss


def test_trade_summary(tmp_path):
    body = FIXTURE + "\n## TRADE & ECONOMICS\n**Token Economy:** Water tokens standard.\n"
    (tmp_path / cr.CERULINE_FILE).write_text(body, encoding="utf-8")
    out = cr.trade_summary(tmp_path)
    assert "Water tokens" in out


def test_identity_key_strips_all_leading_titles_iteratively():
    # Public single source of truth; iterative strip handles stacked titles.
    assert cr.identity_key("Master Surgeon Brant") == "brant"
    assert cr.identity_key("Matriarch Amara Vane") == "amara vane"
    assert cr.identity_key("Amara Vane") == "amara vane"
    assert cr.identity_key("Scholar Tiberius") == "tiberius"
    # A bare name with no title is just normalized/lowered.
    assert cr.identity_key("Harlow") == "harlow"
    # Apostrophe normalization still applies.
    assert cr.identity_key("Lady O’Hare") == "o'hare"
    # Back-compat alias resolves to the same function.
    assert cr._identity_key is cr.identity_key


# ---------------------------------------------------------------------------
# Staleness / as-of-day honesty (reference is a frozen snapshot, not live truth)
# ---------------------------------------------------------------------------

def test_reference_as_of_returns_max_day():
    content = "Lives here since Day 42.\nConverted Day 94.\nold note Day 17."
    assert cr.reference_as_of(content) == 94


def test_reference_as_of_none_when_absent():
    assert cr.reference_as_of("No date stamps anywhere here.") is None


def test_build_tier_card_staleness_with_current_day():
    tiers = cr.parse_ceruline(FIXTURE)
    t10 = next(t for t in tiers if t["num"] == 10)
    card = cr.build_tier_card(t10, as_of_day=94, current_day=140)
    assert "as of Day 94" in card
    assert "now Day 140" in card
    assert "46d on" in card


def test_build_tier_card_staleness_without_current_day():
    tiers = cr.parse_ceruline(FIXTURE)
    t10 = next(t for t in tiers if t["num"] == 10)
    card = cr.build_tier_card(t10, as_of_day=94, current_day=None)
    assert "as of Day 94" in card
    assert "now Day" not in card


def test_tier_list_staleness_warning():
    tiers = cr.parse_ceruline(FIXTURE)
    out = cr.tier_list(tiers, as_of_day=94)
    assert "as of Day 94" in out
    assert "may be stale/incomplete" in out

