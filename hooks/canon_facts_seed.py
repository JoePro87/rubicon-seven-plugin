"""Seed the distillation cache with who's-who facts (identities + relationships).

Entries use the existing distillation-cache shape and topic-key scheme so that
check_canon's injection (_query_distillation_cache) surfaces them automatically.
The seed is idempotent: re-running updates entries in place via cache.put().
"""

try:
    from hooks.hook_utils import normalize_topic_key
except ImportError:
    from hook_utils import normalize_topic_key


def _base(topic_key, learning, key_facts, session_id):
    return {
        "topic_key": topic_key,
        "learning": learning,
        "key_facts": list(key_facts),
        "source_pointers": ["seed:canon_facts"],
        "verified_against": {},
        "created_turn": 0,
        "created_session": session_id,
        "refined_turn": 0,
        "refined_count": 1,
        "ingested_at_session": None,
    }


def build_identity_entry(name, learning, key_facts, session_id):
    return _base(normalize_topic_key([name], "identity"), learning, key_facts, session_id)


def build_relationship_entry(participants, learning, key_facts, session_id):
    return _base(normalize_topic_key(participants, "relationship"), learning, key_facts, session_id)


def seed_facts(facts, cache, session_id="seed"):
    """Write a list of fact dicts into the cache. Returns count written.

    Each fact dict:
      {"kind": "identity", "name": str, "learning": str, "key_facts": [str]}
      {"kind": "relationship", "participants": [str], "learning": str, "key_facts": [str]}
    """
    n = 0
    for f in facts:
        if f["kind"] == "identity":
            entry = build_identity_entry(f["name"], f["learning"], f.get("key_facts", []), session_id)
        elif f["kind"] == "relationship":
            entry = build_relationship_entry(f["participants"], f["learning"], f.get("key_facts", []), session_id)
        else:
            continue
        cache.put(entry)
        n += 1
    return n
