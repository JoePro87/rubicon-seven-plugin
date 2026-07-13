import social_system as ss
from tests.test_social_parley_parser import SAMPLE


def test_briefing_zero_safe(tmp_path):
    assert ss.parley_briefing_lines(tmp_path) == []


def test_briefing_lists_open_parleys(tmp_path):
    parsed = ss.parse_parley_block(SAMPLE)
    ss.open_parley(tmp_path, parsed["slug"], title="Outer Reach Accord", day=131, parsed=parsed)
    lines = ss.parley_briefing_lines(tmp_path)
    assert lines[0].startswith("🤝")
    assert any("Outer Reach Accord" in l and "contact" in l for l in lines)


def test_session_tools_wires_the_section():
    src = open("session_tools.py", encoding="utf-8").read()
    assert "parley_briefing_lines" in src and "parley_briefing_lines" in src.split("_INJECTED")[1][:2000]
