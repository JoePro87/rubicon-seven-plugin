import server


# Minimal VOICE.md mirroring the real file's structure: an L1 title, an
# always-include "Core Rules" L2, a per-character L2 ("VELA ..."), and a
# "BOND COMMUNICATION" L2. Note there is intentionally NO Creenash section —
# Creenash is the PC and is never voiced (Iron Law 5), so the real VOICE.md
# has no "## Creenash" header either.
SAMPLE_VOICE = """# VOICE GUIDE

## Core Rules
- Second person present tense.
- Mechanics are invisible.

## VELA (she/her) — Wife, Navigator, Maven
**Voice:** Dry, warm, matches humor blow-for-blow.

## BOND COMMUNICATION (Creenash <-> Vela)
Private telepathy, always. No NPC awareness.

## SAPHORA (she/her) — Ancient Engineer
**Voice:** Terse. "Hmm" over words.
"""


def _write_voice(isolate_campaign_dir):
    (isolate_campaign_dir / "VOICE.md").write_text(SAMPLE_VOICE, encoding="utf-8")


def test_voice_sections_returns_keyed_elements(isolate_campaign_dir):
    _write_voice(isolate_campaign_dir)
    els = server.load_voice_guide_sections_for(["Vela", "Saphora"])
    keys = [k for (_section, k, _content) in els]
    # Always-include foundational sections.
    assert "voice:core_rules" in keys
    assert "voice:bond" in keys
    # One keyed element per present character that has a section.
    assert any(k == "voice:Vela" for k in keys)
    assert any(k == "voice:Saphora" for k in keys)
    # every element is a (section, key, content) triple with non-empty content
    for section, key, content in els:
        assert section == "VOICE"
        assert key and content


def test_voice_sections_only_present_characters(isolate_campaign_dir):
    """A character not in the present list gets no element."""
    _write_voice(isolate_campaign_dir)
    els = server.load_voice_guide_sections_for(["Vela"])
    keys = [k for (_section, k, _content) in els]
    assert "voice:Vela" in keys
    assert "voice:Saphora" not in keys


def test_voice_sections_empty_for_no_characters():
    assert server.load_voice_guide_sections_for([]) == []


def test_relationship_element_keys_are_per_character():
    els = server._relationship_elements(
        ["Creenash", "Vela"],
        {"Creenash": "Creenash: Vela=HUSBAND", "Vela": "Vela: Creenash=WIFE"},
    )
    keys = {k for (_s, k, _c) in els}
    assert keys == {"rel:Creenash", "rel:Vela"}
    for section, _key, content in els:
        assert section == "RELATIONSHIPS"
        assert content


def test_rules_in_play_elements_key_per_rule():
    lorebook = {"entries": [
        {"category": "people", "keywords": ["creenash"], "rule_refs": ["r1", "r2"]},
    ]}
    rules_idx = {"r1": "Rule one text", "r2": "Rule two text"}
    els = server._rules_in_play_elements(["Creenash"], lorebook, rules_idx)
    keys = {k for (_s, k, _c) in els}
    assert keys == {"rules:r1", "rules:r2"}
    for section, _k, content in els:
        assert section == "RULES"
        assert content.startswith("- ")


def test_distillation_elements_key_per_entry():
    entries = [
        ("creenash_vela_relationship", "long text A"),
        ("look_home_history", "long text B"),
    ]
    els = server._distillation_elements(entries, section="DISTILLATIONS", prefix="distill")
    keys = {k for (_s, k, _c) in els}
    assert keys == {"distill:creenash_vela_relationship", "distill:look_home_history"}
    for section, _k, content in els:
        assert section == "DISTILLATIONS"
        assert content
