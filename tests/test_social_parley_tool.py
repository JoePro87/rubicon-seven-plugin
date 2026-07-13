# tests/test_social_parley_tool.py
import social_system as ss
from tests.test_social_parley_parser import SAMPLE

class FakeMCP:
    def __init__(self):
        self.tools = {}
    def tool(self, *a, **k):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco

def make_tool(tmp_path, day=131):
    mcp = FakeMCP()
    ss.register_social_tools(mcp, tmp_path, get_day=lambda: day)
    return mcp.tools["parley"]

def test_open_from_prep_file(tmp_path):
    (tmp_path / "X_PREP.md").write_text(SAMPLE, encoding="utf-8")
    parley = make_tool(tmp_path)
    out = parley(action="open", slug="outer_reach_accord", prep="X_PREP.md", title="Outer Reach Accord")
    assert "contact" in out and "NEXT" in out
    assert "outer_reach_accord" in ss.load_parleys(tmp_path)

def test_status_shows_tier_needles_gates(tmp_path):
    (tmp_path / "X_PREP.md").write_text(SAMPLE, encoding="utf-8")
    parley = make_tool(tmp_path)
    parley(action="open", slug="outer_reach_accord", prep="X_PREP.md", title="OR")
    out = parley(action="status", slug="outer_reach_accord")
    assert "contact" in out
    assert "She-Who-Keeps" in out and "wary" in out
    assert "matriarch_true_name" in out and "GATED" in out
    assert "NEXT" in out

def test_status_never_prints_reveal_content(tmp_path):
    # spoiler-safety: labels only — gate internals (DC, tier threshold) exist in state
    # but must never render, even though the reveal itself is legitimately named.
    (tmp_path / "X_PREP.md").write_text(SAMPLE, encoding="utf-8")
    parley = make_tool(tmp_path)
    parley(action="open", slug="outer_reach_accord", prep="X_PREP.md", title="OR")
    out = parley(action="status", slug="outer_reach_accord")
    assert "DC 18" not in out
    assert "tier>=" not in out

def test_list_zero_safe(tmp_path):
    parley = make_tool(tmp_path)
    out = parley(action="list")
    assert "no open parleys" in out.lower()

def test_unknown_action_names_vocab(tmp_path):
    parley = make_tool(tmp_path)
    out = parley(action="bogus")
    assert "open" in out and "status" in out and "close" in out
    assert "parley(" in out  # pushed orientation call on the error path

def test_status_no_open_parleys_pushes_list(tmp_path):
    parley = make_tool(tmp_path)
    out = parley(action="status")
    assert "no open parleys" in out.lower()
    assert "parley(" in out  # pushed orientation call on the no-open-parley error path

def test_open_from_site_key(tmp_path):
    prep_text = "<!-- SITE: key=test_site scene=vault_exploration -->\n" + SAMPLE
    (tmp_path / "TESTSITE_PREP.md").write_text(prep_text, encoding="utf-8")
    parley = make_tool(tmp_path)
    out = parley(action="open", slug="outer_reach_accord", site="test_site", title="Outer Reach Accord")
    assert "contact" in out and "NEXT" in out
    assert "outer_reach_accord" in ss.load_parleys(tmp_path)

def test_open_unknown_site_key_errors_with_push(tmp_path):
    parley = make_tool(tmp_path)
    out = parley(action="open", slug="whatever", site="no_such_site", title="X")
    assert "no_such_site" in out
    assert "parley(" in out
