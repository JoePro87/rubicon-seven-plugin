"""Day-130 play report: narrative_qa(validate) hard-blocked any canonical NPC who
entered a scene mid-session (not in the frozen Present roster), and the advertised
verification (lorebook/npc/check_canon) never cleared it — unsatisfiable. The check
only ever scanned names already in npc_states.json, so it caught zero fabrication
while blocking legitimate, recorded NPCs. Softened: a canonical NPC is paintable.
"""
import json

import server


def _write_npcs(campaign_dir, names):
    data = {"npcs": {n.lower(): {"name": n} for n in names}}
    (campaign_dir / "npc_states.json").write_text(json.dumps(data), encoding="utf-8")


def test_canonical_npc_entering_scene_is_not_flagged(isolate_campaign_dir):
    """A recorded NPC who walks into a scene (absent from Present, never 'verified'
    this turn) must NOT be flagged by the validate NPC scan."""
    _write_npcs(isolate_campaign_dir, ["Brant", "Neshet"])
    # No Present roster, no verified_npcs in hook state — the exact mid-session arrival.
    draft = "Brant kneels by the wake, fingers to the cooling skin. Across the flat, Neshet watches."
    assert server._vp_check_npc_mentions(draft) == []


def test_softened_scan_returns_nothing_even_with_empty_store(isolate_campaign_dir):
    """The scan no longer hard-blocks on NPC mentions regardless of store state."""
    assert server._vp_check_npc_mentions("Some prose naming Mira and a stranger.") == []
