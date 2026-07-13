"""Regression guard: the tool-visibility gating system was torn out 2026-05-29.
These tests assert the machinery stays gone. Source-text assertions avoid the
heavy cost (and Ollama dependency) of importing server.py."""
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "server.py"
TOOL_TAGS = Path(__file__).resolve().parent.parent / "tool_tags.py"
GATE_CHECK = Path(__file__).resolve().parent.parent / "hooks" / "gate_check.py"


def test_visibility_filtering_removed_from_server():
    src = SERVER.read_text(encoding="utf-8")
    assert "def _apply_visibility_filtering" not in src
    assert "def _count_tools_by_visibility" not in src
    assert "_active_contexts" not in src
    assert "contexts: list[str] = Field" not in src
    assert "ADMIN_OPERATION_PATTERNS" not in src
    assert "get_tools_for_contexts" not in src
    assert "CONTEXT_CLUSTERS" not in src


def test_enforcement_middleware_removed():
    src = SERVER.read_text(encoding="utf-8")
    assert "class ToolEnforcementMiddleware" not in src
    assert "tool_enforcement" not in src
    assert "RALPH WIGGUM WARNING" not in src


def test_tool_tags_pruned():
    import importlib, tool_tags
    importlib.reload(tool_tags)
    assert not hasattr(tool_tags, "CONTEXT_CLUSTERS")
    assert not hasattr(tool_tags, "CORE_TOOLS_ALWAYS")
    assert not hasattr(tool_tags, "get_tools_for_contexts")
    assert not hasattr(tool_tags, "get_all_context_names")
    # stale entries for deleted tools are gone
    assert "explore" not in tool_tags.TOOL_TAGS
    assert "calculate_journey" not in tool_tags.TOOL_TAGS
    # unused safety level removed
    assert not hasattr(tool_tags.Safety, "DANGEROUS")


def test_gate_check_has_no_dangling_dangerous_reference():
    """Removing Safety.DANGEROUS left a live reference in the PreToolUse hook
    (gate_check.py:109). Because the hook is fail-closed, the AttributeError
    converted into a block on EVERY tool call — the game would brick on the
    next restart. Guard the consumer side, not just the enum definition."""
    src = GATE_CHECK.read_text(encoding="utf-8")
    assert "Safety.DANGEROUS" not in src, (
        "gate_check.py references Safety.DANGEROUS, which no longer exists — "
        "this fail-closed hook would block every tool call."
    )
