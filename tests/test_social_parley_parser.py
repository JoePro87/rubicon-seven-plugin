# tests/test_social_parley_parser.py
import social_system as ss

SAMPLE = """# Some Prep

## PARLEY: outer_reach_accord

**Stakes:** Ceruline wants the brokerage dead; the clan wants survival.
**Failure state:** Combat — Path D triggers only.

### TIERS
1. contact — party states purpose
2. assessment — the other side tests the party | check: EGO DC 15
   - state purpose before sitting
   - answer the council's questions
3. accord — terms sealed

### PARTIES
#### NPC: She-Who-Keeps
**Needle:** wary
**Lever:** the cubs' future
**Pressure:** sways toward accord if security is credible
**Victory:** stands down the warband

### REVEALS
- matriarch_true_name | gate: tier>=accord OR EGO DC 18
- secondary_cache | gate: tier>=accord

### TEXTURE (d8)
| 1 | Wall-weather shift builds on the ridge. |
| 2 | Cubs peer around a corner at the party. |

## NEXT SECTION
ignored
"""

def test_parse_returns_none_without_block():
    assert ss.parse_parley_block("# Prep\nno block here") is None

def test_parse_slug_stakes_failure():
    p = ss.parse_parley_block(SAMPLE)
    assert p["slug"] == "outer_reach_accord"
    assert "brokerage" in p["stakes"]
    assert p["failure_state"].startswith("Combat")

def test_parse_tiers_checks_and_beats():
    p = ss.parse_parley_block(SAMPLE)
    names = [t["name"] for t in p["tiers"]]
    assert names == ["contact", "assessment", "accord"]
    assert p["tiers"][0]["check"] is None
    assert p["tiers"][1]["check"] == {"stat": "EGO", "dc": 15}
    beats = p["tiers"][1]["beats"]
    assert len(beats) == 2 and beats[0]["id"] == "assessment_b1"

def test_parse_parties_needle_validated():
    p = ss.parse_parley_block(SAMPLE)
    npc = p["parties"][0]
    assert npc["name"] == "She-Who-Keeps"
    assert npc["needle"] == "wary"
    assert "cubs" in npc["lever"]

def test_parse_reveals_gates():
    p = ss.parse_parley_block(SAMPLE)
    r = {x["label"]: x["gate"] for x in p["reveals"]}
    assert r["matriarch_true_name"] == {"tier": "accord", "check": {"stat": "EGO", "dc": 18}}
    assert r["secondary_cache"] == {"tier": "accord", "check": None}

def test_parse_texture_table():
    p = ss.parse_parley_block(SAMPLE)
    assert p["texture"][0] == {"roll": 1, "text": "Wall-weather shift builds on the ridge."}
    assert len(p["texture"]) == 2

def test_parse_gate_single_clauses():
    assert ss.parse_gate("tier>=trust") == {"tier": "trust", "check": None}
    assert ss.parse_gate("EGO DC 18") == {"tier": None, "check": {"stat": "EGO", "dc": 18}}

def test_block_ends_at_next_h2():
    p = ss.parse_parley_block(SAMPLE)
    assert "ignored" not in str(p)

def test_parse_needle_strips_trailing_html_comment():
    text = """## PARLEY: comment_check

**Stakes:** test
**Failure state:** test

### PARTIES
#### NPC: Someone
**Needle:** wary            <!-- hostile | wary | neutral | warm | allied -->
**Lever:** x
**Pressure:** x
**Victory:** x
"""
    p = ss.parse_parley_block(text)
    assert p["parties"][0]["needle"] == "wary"
