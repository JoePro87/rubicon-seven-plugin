"""Tests for the who's-who cheat-sheet seed builder."""
from hooks.distillation_cache import DistillationCache
from hooks.canon_facts_seed import build_identity_entry, build_relationship_entry, seed_facts


def test_build_identity_entry_shape():
    e = build_identity_entry(name="Joss", learning="Joss is a navigator, Mira's father.",
                             key_facts=["navigator", "Mira's father"], session_id="seed")
    assert e["topic_key"] == "joss_identity"
    assert e["learning"].startswith("Joss is a navigator")
    assert "navigator" in e["key_facts"]
    assert e["ingested_at_session"] is None  # so it gets posted to Chroma later


def test_build_relationship_entry_key_is_sorted_pair():
    e = build_relationship_entry(["Mira", "Joss"], "Joss is Mira's father.", ["father"], "seed")
    assert e["topic_key"] == "joss_mira_relationship"  # normalize sorts participants


def test_seed_facts_writes_entries_to_cache(tmp_path):
    cache = DistillationCache(tmp_path / "c.json")
    facts = [
        {"kind": "identity", "name": "Joss",
         "learning": "Joss is a navigator, Mira's father.", "key_facts": ["navigator"]},
        {"kind": "relationship", "participants": ["Amara", "Brek"],
         "learning": "Amara is Brek's mother-in-law; she drugged him.",
         "key_facts": ["mother-in-law"]},
    ]
    n = seed_facts(facts, cache, session_id="seed")
    assert n == 2
    assert cache.get("joss_identity") is not None
    assert cache.get("amara_brek_relationship") is not None


def test_query_surfaces_present_char_identity(tmp_path, monkeypatch):
    import server
    from hooks.distillation_cache import DistillationCache
    cache = DistillationCache(tmp_path / "c.json")
    cache.put(build_identity_entry("Joss", "Joss is a navigator.", ["navigator"], "seed"))
    monkeypatch.setattr(server, "_get_distillation_cache", lambda: cache, raising=False)

    # Joss present but NOT mentioned in the input text → must still surface via identity scan.
    hits = server._query_distillation_cache(["Joss", "Mira"], input_lower="they sat down")
    assert any(h.get("topic_key") == "joss_identity" for h in hits)
