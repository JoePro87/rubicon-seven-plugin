"""C14 — generate(action="story_seed"): the book's d100 Story Seeds generator
(CH pp.87-89) is ingested but was unrollable. It now mirrors the exotica
generator: four INDEPENDENT d100s (WHO/WHAT/WITH/WHY) read from the engine
rulebook data, an optional reroll_column, and crystallization batons.
"""
import json
import re

import generators
import server
import engine_core


def test_table_present_in_rulebook_data():
    data = json.loads(engine_core.read_rules_data("rulebook/tables.json"))
    t = next(x for x in data["rolling_tables"] if x["id"] == "table-story-seeds")
    assert t["die"] == "d100"
    assert len(t["entries"]) == 100
    assert t["columns"] == ["who", "what", "with", "why"]


def test_generate_story_seed_has_four_columns():
    out = generators._generate_story_seed(reroll_column=None)
    for col in ("WHO", "WHAT", "WITH", "WHY"):
        assert re.search(rf"\| {col} \| \d+ \|", out), col


def test_independent_rolls_can_differ():
    # Over several generations the four column rolls should not be locked together.
    seen = set()
    for _ in range(20):
        out = generators._generate_story_seed(reroll_column=None)
        rolls = tuple(int(m) for m in re.findall(r"\| (?:WHO|WHAT|WITH|WHY) \| (\d+) \|", out))
        seen.add(len(set(rolls)))
    assert max(seen) > 1  # at least once, the four rolls were not all identical


def test_invalid_column_rejected():
    out = generators._generate_story_seed(reroll_column="bogus")
    assert "invalid column" in out.lower()


def test_pushes_crystallization_batons():
    out = generators._generate_story_seed(reroll_column=None)
    assert 'thread(action="add"' in out
    assert 'antagonist(action="add_seed"' in out
    assert 'character(action="register"' in out


def test_registered_in_generate_dispatcher():
    fn = server.generate.fn if hasattr(server.generate, "fn") else server.generate
    out = fn(action="story_seed")
    assert "STORY SEEDS GENERATOR" in out
    # unknown action still errors and now lists story_seed
    bad = fn(action="nonsense")
    assert "story_seed" in bad
