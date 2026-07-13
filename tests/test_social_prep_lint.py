# tests/test_social_prep_lint.py
import social_system as ss
from tests.test_social_parley_parser import SAMPLE


def test_clean_block_no_warnings():
    assert ss.lint_parley_block(SAMPLE) == []


def test_legacy_prep_without_block_warns():
    legacy = "# Prep\n\n## VICTORY CONDITIONS\n\n### Path A: The Alliance\n"
    warns = ss.lint_parley_block(legacy)
    assert any("legacy" in w.lower() for w in warns)


def test_bad_needle_and_unknown_gate_tier():
    bad = SAMPLE.replace("**Needle:** wary", "**Needle:** grumpy").replace("tier>=accord OR", "tier>=friendship OR")
    warns = ss.lint_parley_block(bad)
    assert any("needle" in w for w in warns)
    assert any("unknown tier" in w for w in warns)


def test_no_block_no_legacy_is_silent():
    assert ss.lint_parley_block("# Plain dungeon prep\n## ROOM: a\n") == []


def test_validate_prep_file_calls_lint():
    src = open("server.py", encoding="utf-8").read()
    assert "lint_parley_block" in src
