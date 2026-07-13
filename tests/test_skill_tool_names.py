"""Enforce that skill markdown only references registered MCP tools.

Skills push tool calls at the DM (PUSH rule, docs/DEVELOPMENT.md section 3).
A skill that names a retired or unknown tool sends a fresh post-compaction
Claude to a tool that does not exist. Two guards:

1. No retired tool names anywhere in skill markdown (call-style tokens).
2. Every action-style call token (``name(action=...)``) must be a tool
   currently registered on the MCP server.

Skills live in the CAMPAIGN repo (this engine repo is the "boiler room" and
carries no gameplay skills), so this guard scans the campaign repo's skill
folders, resolved by their fixed sibling location ``../rubicon-seven-campaign``.
If the campaign repo is not present (e.g. the engine repo cloned on its own),
the skill checks SKIP rather than fail.
"""
import ast
import asyncio
import inspect
import re
import textwrap
from pathlib import Path

import pytest

import server

# Tools that no longer exist on the server; skills must not push them.
RETIRED = {
    "generate_npc",
    "lookup_creature_stats",
    "roll_exotica",
    "lookup_exotica",
    "roll_encounter_table",
    "reveal",
    "location_enter_room",
    "dm_reveal",
}

# Curated false positives for the action-style check (python builtins in
# code blocks, prose). Add entries ONLY when observed as a real false positive.
ALLOWED_NON_TOOLS = set()

CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]{2,40})\(")
ACTION_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]{2,40})\(\s*action\s*=")
# Captures BOTH the tool name and the literal action value: name(action="X").
ACTION_VALUE_RE = re.compile(
    r"\b([a-z_][a-z0-9_]{2,40})\(\s*action\s*=\s*[\"']([a-z_][a-z0-9_]*)[\"']")


def _campaign_dir():
    """Locate the real campaign repo (sibling of this engine repo), or None.

    Deliberately does NOT consult RUBICON_CAMPAIGN_DIR: conftest.py redirects
    that var to a throwaway sandbox during the suite to keep tests off live
    play-state. Skills are source files that always live in the real repo, so
    we resolve it by its fixed sibling location instead.
    """
    sibling = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"
    return sibling if sibling.is_dir() else None


def _skill_roots():
    # Shipped plugin skills live in THIS engine repo (vaarn-start, content-forge);
    # they ship to every OSS campaign, so they must be guarded too — not just the
    # owner's campaign-repo skills. Both are scanned when present.
    roots = [Path(__file__).resolve().parents[1] / "skills"]
    camp = _campaign_dir()
    if camp is not None:
        roots += [camp / "content-forge", camp / ".claude" / "skills"]
    return [r for r in roots if r.is_dir()]


def _skill_files():
    files = []
    for root in _skill_roots():
        files.extend(sorted(root.rglob("*.md")))
    return files


def _require_campaign():
    if _campaign_dir() is None:
        pytest.skip(
            "campaign repo not found; set RUBICON_CAMPAIGN_DIR (or place it at "
            "../rubicon-seven-campaign) to enable the skill tool-name checks"
        )


def _registered_tool_names():
    tools = asyncio.run(server.mcp.list_tools())
    return {t.name for t in tools}


def test_skill_files_exist():
    _require_campaign()
    files = _skill_files()
    assert files, "No skill markdown found under the campaign skill folders"


def test_no_retired_tool_names_in_skills():
    _require_campaign()
    camp = _campaign_dir()
    hits = []
    for path in _skill_files():
        rel = path.relative_to(Path(__file__).resolve().parents[2])
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            for match in CALL_RE.finditer(line):
                name = match.group(1)
                if name in RETIRED:
                    hits.append(f"{rel}:{lineno}: {name}")
    assert not hits, (
        "Skill markdown references RETIRED tools (update the skill to the "
        "current consolidated tool):\n" + "\n".join(hits)
    )


def test_action_style_calls_are_registered_tools():
    _require_campaign()
    camp = _campaign_dir()
    registered = _registered_tool_names()
    bad = []
    for path in _skill_files():
        rel = path.relative_to(Path(__file__).resolve().parents[2])
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            for match in ACTION_CALL_RE.finditer(line):
                name = match.group(1)
                if name in registered or name in ALLOWED_NON_TOOLS:
                    continue
                bad.append(f"{rel}:{lineno}: {name}")
    assert not bad, (
        "Skill markdown pushes action-style calls to names that are not "
        "registered MCP tools:\n" + "\n".join(bad)
    )


# ---------------------------------------------------------------------------
# Guard 3: action VALUES must be real (not just the tool name).
#
# The two guards above check the tool NAME exists. This one checks the
# `action="X"` is an action that tool actually accepts — catching a valid tool
# pushed with a renamed/stale/typo'd action (e.g. npc(action="banish")). The
# valid-action vocab is harvested from the LIVE code (no curated map to rot):
# string literals compared to `action` (or a variable assigned from it),
# any VALID_*-style collection resolved from module globals, UNION the action
# param's pipe-enum Field description. If a tool's vocab can't be determined
# (empty harvest), its action-value check is SKIPPED — the name guard still
# applies, and the guard-the-guard test below proves the harvester has teeth.
# ---------------------------------------------------------------------------

def _action_param_enum(fn):
    """Actions declared in the `action` param's Field(description="a|b|c")."""
    try:
        param = inspect.signature(fn).parameters.get("action")
    except (TypeError, ValueError):
        return set()
    if param is None:
        return set()
    desc = getattr(param.default, "description", None) or ""
    out = set()
    for run in re.findall(r"[a-z_]+(?:\s*\|\s*[a-z_]+)+", desc):
        out.update(tok.strip() for tok in run.split("|") if tok.strip())
    return out


def _harvest_tool_actions(fn):
    """Best-effort set of action strings a dispatcher accepts, from the live code.
    Empty set means 'undetermined' -> caller skips the action-value check."""
    actions = set()
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        tree = None
    names = set()
    if tree is not None:
        aliases = {"action"}  # vars assigned from `action` (e.g. a = action.lower())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(n, ast.Name) and n.id == "action" for n in ast.walk(node.value)
            ):
                aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                parts = [node.left, *node.comparators]
                if any(isinstance(p, ast.Name) and p.id in aliases for p in parts):
                    for p in parts:
                        if isinstance(p, ast.Constant) and isinstance(p.value, str):
                            actions.add(p.value)
                        elif isinstance(p, (ast.Tuple, ast.List, ast.Set)):
                            actions.update(
                                e.value for e in p.elts
                                if isinstance(e, ast.Constant) and isinstance(e.value, str))
                        elif isinstance(p, ast.Name) and p.id not in aliases:
                            names.add(p.id)
    g = getattr(fn, "__globals__", {})
    for nm in names:
        val = g.get(nm)
        if isinstance(val, (list, set, tuple, frozenset)):
            actions.update(x for x in val if isinstance(x, str))
    actions |= _action_param_enum(fn)
    return actions


def _tool_fns():
    """Registered tool name -> underlying callable (FastMCP FunctionTool.fn)."""
    async def _collect():
        out = {}
        for t in await server.mcp.list_tools():
            try:
                out[t.name] = (await server.mcp.get_tool(t.name)).fn
            except Exception:
                pass
        return out
    return asyncio.run(_collect())


def test_action_style_calls_use_valid_actions():
    _require_campaign()
    camp = _campaign_dir()
    fns = _tool_fns()
    vocab = {}
    bad = []
    for path in _skill_files():
        rel = path.relative_to(Path(__file__).resolve().parents[2])
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            for match in ACTION_VALUE_RE.finditer(line):
                name, action = match.group(1), match.group(2)
                if name not in fns or name in ALLOWED_NON_TOOLS:
                    continue  # name guard (above) owns unregistered names
                if name not in vocab:
                    vocab[name] = _harvest_tool_actions(fns[name])
                valid = vocab[name]
                if valid and action not in valid:
                    bad.append(
                        f"{rel}:{lineno}: {name}(action=\"{action}\") "
                        f"-- not a valid action; tool accepts {sorted(valid)}")
    assert not bad, (
        "Skill markdown pushes action-style calls with actions the tool does NOT "
        "accept (renamed/stale/typo'd action):\n" + "\n".join(bad)
    )


def test_action_validator_has_teeth():
    """Guard-the-guard: prove the harvester resolves a real tool's vocab and would
    reject a bogus action, so the test above can never silently degrade to a no-op."""
    _require_campaign()
    npc_actions = _harvest_tool_actions(_tool_fns()["npc"])
    assert "record_death" in npc_actions  # a real npc action is found
    assert "banish" not in npc_actions    # a bogus one is correctly absent


# ---------------------------------------------------------------------------
# Guard 4: pushed KEYWORD ARGUMENT names must be real params on the tool.
#
# Guards 2/3 confirm the tool NAME and the action VALUE are real. Neither
# catches a keyword typo/rename on the call itself -- real shipped bugs were
# `roll(stat=...)` where the tool's param is `ability=`, and a positional
# `lorebook(view, "x")` where `view` reads as a keyword-argument-shaped param.
# Vocab is harvested from the LIVE signature (`inspect.signature`), same
# no-curated-map philosophy as the action-vocab guard above.
#
# Scope limits (documented, not bugs):
# - Only calls whose parens close on the SAME LINE are checked -- multi-line
#   pushes don't occur in this project's skills (single-line push is the
#   convention), and CALL_KWARG_RE simply won't match a call split across
#   lines, so this is a silent (intentional) skip, not a crash.
# - Kwarg tokens are extracted after stripping quoted-string spans, so a
#   value like `reason="a=b"` can't be mistaken for a `b` kwarg.
# - A tool whose signature can't be resolved -> skipped (undetermined,
#   mirrors the action-vocab guard's skip philosophy).
# - POSITIONAL (no `=`) arguments are never checked -- the positional
#   `lorebook(view, "x")` bug class cited above MOTIVATED this guard but is
#   NOT covered by it; that gap remains open.
# ---------------------------------------------------------------------------

CALL_KWARG_RE = re.compile(r"\b([a-z_][a-z0-9_]{2,40})\(([^)]*)\)")
KWARG_NAME_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*=(?!=)")

# Curated (tool, kwarg) false positives for the kwarg-name check. Add entries
# ONLY for an observed false positive, each with a one-line comment saying
# where/why it's a false positive (not a real defect).
ALLOWED_KWARG_FALSE_POSITIVES = set()


def _strip_quoted(body):
    """Drop the contents of quoted string literals so a value that happens to
    contain `word=` (e.g. a prose placeholder) can't be mistaken for a kwarg."""
    body = re.sub(r'"[^"]*"', '""', body)
    body = re.sub(r"'[^']*'", "''", body)
    return body


def test_pushed_call_kwargs_are_real_params():
    _require_campaign()
    camp = _campaign_dir()
    registered = _registered_tool_names()
    fns = _tool_fns()
    param_cache = {}
    bad = []
    for path in _skill_files():
        rel = path.relative_to(Path(__file__).resolve().parents[2])
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            for match in CALL_KWARG_RE.finditer(line):
                name, body = match.group(1), match.group(2)
                if name not in registered or name not in fns:
                    continue  # name guard (above) owns unregistered names
                if name not in param_cache:
                    try:
                        param_cache[name] = set(inspect.signature(fns[name]).parameters)
                    except (TypeError, ValueError):
                        param_cache[name] = None  # undetermined -> skip
                params = param_cache[name]
                if not params:
                    continue
                for kwmatch in KWARG_NAME_RE.finditer(_strip_quoted(body)):
                    kwarg = kwmatch.group(1)
                    if kwarg in params or (name, kwarg) in ALLOWED_KWARG_FALSE_POSITIVES:
                        continue
                    bad.append(
                        f"{rel}:{lineno}: {name}(...{kwarg}=...) "
                        f"-- not a real param; tool accepts {sorted(params)}")
    assert not bad, (
        "Skill markdown pushes calls with keyword arguments that are not real "
        "parameters on the tool (renamed/stale/typo'd kwarg):\n" + "\n".join(bad)
    )


def test_kwarg_validator_has_teeth():
    """Guard-the-guard: prove the harvester resolves a real tool's params and
    would reject a bogus kwarg, so the test above can never silently degrade
    to a no-op."""
    _require_campaign()
    roll_params = set(inspect.signature(_tool_fns()["roll"]).parameters)
    assert "ability" in roll_params   # roll's real param is found
    assert "stat" not in roll_params  # a renamed/bogus one is correctly absent


# ---------------------------------------------------------------------------
# Guard 5: allowed-tools frontmatter must cover every registered tool the
# SKILL.md pushes in its body.
#
# A skill that pushes `parley(...)` but omits `mcp__rubicon-seven__parley`
# from its own `allowed-tools:` frontmatter silently blocks the DM from
# following that push (a known project leftover, deferred until this guard).
# Skills with NO `allowed-tools:` line are unrestricted -- skipped, not
# failed. Scan scope is SKILL.md ONLY (not sibling reference/prompt files --
# those are agent prompts and reference material, not skill execution
# context the frontmatter needs to cover). Each SKILL.md is checked against
# its OWN frontmatter, including the campaign forks.
# ---------------------------------------------------------------------------

FRONTMATTER_ALLOWED_TOOLS_RE = re.compile(
    r"^allowed-tools:[ \t]*(.+(?:\n[ \t]+\S.*)*)", re.MULTILINE)
MCP_TOOL_TOKEN_RE = re.compile(r"mcp__rubicon-seven__([a-z_][a-z0-9_]*)")

# (skill dir name, tool name) pairs where the call token names a tool in
# PROSE to say it is NOT called (a negative mention), not an actual push.
# Curated because "no separate X() call is needed" phrasing can't be told
# apart from a real push by a generic regex without over-fitting one-off
# wording. Add entries ONLY for an observed negative-mention false positive.
ALLOWED_UNPUSHED_MENTIONS = {
    # session-start/SKILL.md: "no separate load_last_session() call is
    # needed" -- full_session_startup() already returns the checkpoint.
    ("session-start", "load_last_session"),
}


def _skill_md_files():
    return [p for p in _skill_files() if p.name == "SKILL.md"]


def _frontmatter_block(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:i])
    return ""


def test_allowed_tools_covers_pushed_tools():
    _require_campaign()
    camp = _campaign_dir()
    registered = _registered_tool_names()
    bad = []
    for path in _skill_md_files():
        rel = path.relative_to(Path(__file__).resolve().parents[2])
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = _frontmatter_block(text)
        m = FRONTMATTER_ALLOWED_TOOLS_RE.search(fm)
        if not m:
            continue  # no allowed-tools line -> unrestricted, skip
        allowed = set(MCP_TOOL_TOKEN_RE.findall(m.group(1)))
        pushed_first_line = {}
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in CALL_RE.finditer(line):
                name = match.group(1)
                if name in registered and name not in pushed_first_line:
                    pushed_first_line[name] = lineno
        skill_id = path.parent.name
        for name, lineno in pushed_first_line.items():
            if name in allowed or (skill_id, name) in ALLOWED_UNPUSHED_MENTIONS:
                continue
            bad.append(
                f"{rel}: pushes '{name}(' at line {lineno} but "
                f"'mcp__rubicon-seven__{name}' is missing from allowed-tools")
    assert not bad, (
        "SKILL.md pushes a registered tool call that its own allowed-tools "
        "frontmatter does not declare (the DM would be blocked from "
        "following the push):\n" + "\n".join(bad)
    )
