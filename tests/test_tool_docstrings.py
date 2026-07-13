"""Enforce the Reflex Layer docstring convention (spec 2026-06-10, Component 1).

Every registered MCP tool's description must LEAD with a trigger line:
    Reach for this WHEN <situation>.
PULL backstop of the "How does Claude find the right tool?" rule
(docs/DEVELOPMENT.md section 3). All 61 tools comply; new tools must comply at birth.
"""
import asyncio
import re

import server

TRIGGER_RE = re.compile(r"^Reach for this WHEN \S.{9,}")


def _tools():
    return asyncio.run(server.mcp.list_tools())


def test_every_tool_leads_with_trigger_line():
    bad = []
    for t in _tools():
        first = (t.description or "").strip().splitlines()[0] if t.description else ""
        if not TRIGGER_RE.match(first):
            bad.append(f"{t.name}: {first!r}")
    assert not bad, (
        "Tools missing the 'Reach for this WHEN ...' trigger first line "
        "(docs/DEVELOPMENT.md section 3):\n" + "\n".join(bad)
    )
