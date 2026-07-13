"""Owner pin (Joe 2026-07-03): the generator's template and the engine's parser
are ONE format. This test parses the template text straight out of the forge
skill; if either side drifts, this fails."""
import re
from pathlib import Path

import social_system as ss


def _skill_text():
    path = Path(__file__).resolve().parents[1] / "skills" / "content-forge" / "SKILL.md"
    if not path.exists():
        raise AssertionError(f"content-forge SKILL.md not found at {path}")
    return path.read_text(encoding="utf-8")


def test_forge_template_parses_to_full_state():
    text = _skill_text()
    m = re.search(r"```markdown\n(## PARLEY:.*?)```", text, re.DOTALL)
    assert m, "forge skill carries no PARLEY template code block"
    parsed = ss.parse_parley_block(m.group(1))
    assert parsed and parsed["tiers"] and parsed["parties"] and parsed["reveals"]
    assert ss.lint_parley_block(m.group(1)) == []


def test_forge_template_pushes_the_opener():
    text = _skill_text()
    assert 'parley(action="open"' in text
