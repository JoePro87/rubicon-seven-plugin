"""Attributed-claim gate (canon gate hardening spec §F.3, 2026-07-24).

The worst fabrication class: DM invention laundered through a trusted NPC's
mouth. It borrows their authority and the player has no way to audit it.
"""
import glob
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.attributed_claim_gate import scan_attributed_claims  # noqa: E402

NPCS = {"thresh", "kess", "vela", "creenash", "tessith", "petros", "bugsie"}

THE_2026_07_24_STRING = (
    "Thresh told you the keeper is fair, that the price is not fixed in "
    "advance, and that a caravan pays more than a pilgrim."
)
CANON_BLOB = "thresh said it will likely deal fair"


# --- must block ------------------------------------------------------------

def test_the_verbatim_2026_07_24_string_blocks():
    hits = scan_attributed_claims(THE_2026_07_24_STRING, NPCS, CANON_BLOB, [])
    assert hits and "Thresh" in hits[0]


def test_unsupported_attribution_with_empty_blob_blocks():
    hits = scan_attributed_claims(
        "Kess confirmed that the crossing opens at the eleventh bell.",
        NPCS, "", [])
    assert hits and "Kess" in hits[0]


def test_block_message_offers_the_honest_exit():
    """The composed block reason must always leave the DM a legal way out that
    is not invention. Without it the gate gets routed around."""
    from hooks.attributed_claim_gate import block_tail
    hits = scan_attributed_claims(THE_2026_07_24_STRING, NPCS, CANON_BLOB, [])
    reason = "\n".join(hits) + block_tail()
    assert "not established" in reason, "the gate must never force invention"
    assert "Nobody told you" in reason


# --- must pass -------------------------------------------------------------

@pytest.mark.parametrize("tool", ["search", "check_canon", "npc", "lorebook"])
def test_source_in_turn_waives(tool):
    assert scan_attributed_claims(THE_2026_07_24_STRING, NPCS, CANON_BLOB, [tool]) == []


def test_content_in_record_waives():
    blob = ("thresh told you the keeper is fair and that the price is not fixed "
            "in advance and that a caravan pays more than a pilgrim")
    assert scan_attributed_claims(THE_2026_07_24_STRING, NPCS, blob, []) == []


def test_dialogue_tag_is_not_testimony():
    assert scan_attributed_claims('"Go," she said.', NPCS, "", []) == []


def test_dialogue_introduction_is_not_testimony():
    assert scan_attributed_claims(
        'Kess says, flat, to no one: "Of course it does."', NPCS, "", []) == []


@pytest.mark.parametrize("text", [
    "Kess said nothing.",
    "Vela said it quietly.",
])
def test_no_claim_body_passes(text):
    assert scan_attributed_claims(text, NPCS, "", []) == []


def test_negated_attribution_passes():
    assert scan_attributed_claims(
        "Thresh never told you what it charges.", NPCS, "", []) == []


def test_modal_attribution_passes():
    assert scan_attributed_claims(
        "Thresh would tell you that the fold is dangerous.", NPCS, "", []) == []


def test_reversal_guard_passes():
    assert scan_attributed_claims(
        "You told Thresh about the fold and the keeper on the far side.",
        NPCS, "", []) == []


def test_passive_recipient_passes():
    assert scan_attributed_claims(
        "Saphora is waiting to be told whether she is measuring the light.",
        NPCS, "", []) == []


def test_unknown_speaker_is_not_a_canon_authority_launder():
    assert scan_attributed_claims(
        "Bartholomew told you that the price is not fixed in advance.",
        NPCS, "", []) == []


def test_no_npc_names_fails_open():
    assert scan_attributed_claims(THE_2026_07_24_STRING, set(), "", []) == []


# --- corpus regression: this number gated the ship decision ----------------

FIXTURE = Path(__file__).parent / "fixtures" / "prose_window_200.jsonl"


def _live_blob_and_names():
    from conftest import REAL_CAMPAIGN_DIR
    camp = REAL_CAMPAIGN_DIR
    parts = []
    try:
        from hooks.distillation_cache import DistillationCache
        for entry in DistillationCache(camp / ".canon_distillations.json").all_entries():
            parts += [str(f) for f in (entry.get("key_facts") or [])]
            learning = entry.get("learning") or entry.get("learnings")
            if isinstance(learning, str):
                parts.append(learning)
            elif isinstance(learning, list):
                parts += [str(x) for x in learning]
    except Exception:
        pass
    for mp in glob.glob(str(camp / "maps" / "*.json")):
        if ".bak" in mp or ".pre-" in mp:
            continue
        try:
            data = json.loads(Path(mp).read_text(encoding="utf-8"))
        except Exception:
            continue
        parts += [(e.get("fact") or "") for e in (data.get("revealed_ledger") or [])][-60:]

    names = set()
    try:
        data = json.loads((camp / "npc_states.json").read_text(encoding="utf-8"))
        for key, entry in (data.get("npcs") or {}).items():
            names.add(str(key).replace("_", " ").lower())
            if isinstance(entry, dict) and entry.get("name"):
                names.add(str(entry["name"]).lower().split()[0])
    except Exception:
        pass
    names |= NPCS
    return " | ".join(parts).lower(), {n for n in names if len(n) >= 3}


@pytest.mark.skipif(not FIXTURE.exists(), reason="live-prose corpus fixture not shipped")
def test_corpus_arm_rate_supports_the_blocking_ship_decision():
    """MEASURED 2026-07-24 over 200 real turns: 14/200 = 7.0%.

    Spec §B.5 gates the ship decision on this number: <=10% ships BLOCKING,
    >10% ships advisory pending a retune. 7.0% -> shipped blocking. The
    ceiling below is 10% of 200 turns; drift past it must fail loudly and
    force the gate back to advisory rather than ride into live play.
    """
    blob, names = _live_blob_and_names()
    if not blob or not names:
        pytest.skip("live campaign answer key unavailable")

    armed = 0
    total = 0
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        if scan_attributed_claims(json.loads(line).get("text", ""), names, blob, []):
            armed += 1
    assert total == 200
    assert armed <= 20, (
        f"attributed-claim arm rate regressed to {armed}/200 "
        f"({armed / 2:.1f}%) — over the 10% blocking threshold (spec B.5)")
