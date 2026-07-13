"""Guard: rendered tool-call pushes must be apostrophe-safe.

The reflex layer renders copy-paste tool calls for the DM ("NEXT: tool(...)").
A value interpolated inside SINGLE quotes -- param='{var}' -- breaks the moment
the value carries an apostrophe (Death's Door, Rax'il, "Mira's father"). That is
the exact failure push_format (_pf) exists to make impossible: it double-quotes
every value by construction.

The discipline silently decayed once already (3 toxin sites in substances.py +
npc/map/lorebook hints shipped single-quoted), so a formatter that is merely
correct is not enough -- nothing prevented the bypass. This guard fails on any
NEW single-quoted interpolated kwarg in engine source, exactly like
test_tool_docstrings guards the trigger-line convention. To satisfy it: route
the push through _pf.push_call / _pf.next_block, or double-quote the value.

The ALLOWLIST holds reviewed NON-push matches (error echoes / human display
listings that never become a copy-paste tool call). Add to it only after
confirming a match is genuinely not a DM-facing call.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A single-quoted interpolated kwarg:  word='{ ... }'
_PATTERN = re.compile(r"\b\w+='\{")

# Reviewed NON-push matches: (path suffix, substring on the line). Each is an
# error echo or a display listing, NOT a tool call the DM copy-pastes.
_ALLOWLIST = [
    ("character_tools.py", "action='{action}' requires"),
    ("substances.py", "action='{action}' requires"),
    ("server.py", "SITE key='{"),
    ("hooks/gate_check.py", "(name='{slug}')"),
    ("hooks/phrase_reminder.py", "(name='{s}')"),
]


def _source_files():
    """Engine source: server.py + repo-root modules + hooks/ (never tests)."""
    candidates = [ROOT / "server.py"]
    candidates += sorted(ROOT.glob("*.py"))
    candidates += sorted((ROOT / "hooks").glob("*.py"))
    seen, out = set(), []
    for f in candidates:
        if f in seen or f.name.startswith("test_"):
            continue
        seen.add(f)
        out.append(f)
    return out


def _allowlisted(path, line):
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    return any(rel.endswith(suf) and sub in line for suf, sub in _ALLOWLIST)


def test_no_single_quoted_interpolated_push():
    """No engine-source line may interpolate a value inside single quotes in a
    rendered call (apostrophe-unsafe), unless reviewed onto the allowlist."""
    offenders = []
    for f in _source_files():
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _PATTERN.search(line) and not _allowlisted(f, line):
                offenders.append(
                    f"{f.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "Single-quoted interpolated value in a rendered call (apostrophe-unsafe). "
        "Route through _pf.push_call / next_block, double-quote the value, or "
        "add to the reviewed allowlist if it is genuinely not a DM-facing tool "
        "call:\n" + "\n".join(offenders))


def test_toxin_reroute_renders_apostrophe_name_double_quoted(monkeypatch):
    """End-to-end: an apostrophe-bearing target must render a syntactically
    intact (double-quoted) resolve call, never a broken single-quoted one."""
    import server
    pc = {"name": "Rax'il", "species": "Neobloom",
          "slot_capacity_total": 13, "wounds_slots_used": 0,
          "mystic_gifts": [], "codices": [], "inventory": {"carried": []}}
    data = {"meta": {}, "characters": {"Rax'il": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_attack_reroute(
        attacker=None, target="Rax'il", tox_die="d8", attacker_kind="enemy")
    assert 'target="Rax\'il"' in out          # double-quoted -> intact
    assert "target='Rax'il'" not in out       # never the broken single-quote form
