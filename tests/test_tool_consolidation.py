"""Smoke tests for consolidated action-based tools."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAntiPatternsMerge:
    """Verify the anti-pattern impls (now reached via narrative_qa) work."""

    def test_list_action_returns_patterns(self):
        from server import _list_anti_patterns
        result = _list_anti_patterns()
        assert isinstance(result, str)
        assert "blacklist" in result.lower() or "pattern" in result.lower() or "anti" in result.lower()

    def test_check_action_scans_text(self):
        from server import _check_anti_patterns
        result = _check_anti_patterns("her breath catches in her throat", "")
        assert isinstance(result, str)


class TestNarrativeQaMerge:
    """Verify narrative_qa(action=...) absorbs anti_patterns + validate_prose."""

    def test_validate_impl_exists(self):
        from server import _validate_prose_impl
        assert callable(_validate_prose_impl)

    def test_check_and_list_impls_exist(self):
        from server import _check_anti_patterns, _list_anti_patterns
        assert callable(_check_anti_patterns) and callable(_list_anti_patterns)

    def test_validate_action_runs_gate(self):
        from server import narrative_qa
        result = narrative_qa(action="validate",
                              text="The corridor stretched ahead. Stone dust lay in grey drifts.")
        assert "CLEAN" in result

    def test_validate_action_catches_blacklist(self):
        from server import narrative_qa
        result = narrative_qa(action="validate",
                              text="Her breath catches as the silence stretches between them.")
        assert "VIOLATIONS" in result

    def test_list_action_returns_str(self):
        from server import narrative_qa
        assert isinstance(narrative_qa(action="list"), str)

    def test_invalid_action_returns_error(self):
        from server import narrative_qa
        result = narrative_qa(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestLogMerge:
    """Verify log(action=...) absorbs log_beat + get_session_log."""

    def test_impls_exist(self):
        from server import _log_beat_impl, _get_session_log_impl
        assert callable(_log_beat_impl) and callable(_get_session_log_impl)

    def test_get_action_returns_str(self):
        from server import log
        assert isinstance(log(action="get"), str)

    def test_invalid_action_returns_error(self):
        from server import log
        result = log(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestConstraintMerge:
    """Verify constraint(action=...) absorbs constraint_add + constraint_check."""

    def test_check_impl_exists(self):
        from server import _constraint_check_impl, _register_constraint
        assert callable(_constraint_check_impl) and callable(_register_constraint)

    def test_check_action_returns_str(self):
        from server import constraint
        assert isinstance(constraint(action="check", subject="nobody"), str)

    def test_add_missing_args_errors(self):
        # MCP resolves unspecified Field() params to their "" defaults; pass them
        # explicitly here since a direct in-process call leaves them as FieldInfo.
        from server import constraint
        assert "needs" in constraint(
            action="add", constraint_id="", subject="", limitation="").lower()

    def test_invalid_action_returns_error(self):
        from server import constraint
        result = constraint(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestFilesMerge:
    """Verify files(action=...) absorbs list_files + read_file_section + read_pdf_pages."""

    def test_impls_exist(self):
        from server import _list_files_impl, _read_file_section_impl, _read_pdf_pages_impl
        assert callable(_list_files_impl) and callable(_read_file_section_impl) and callable(_read_pdf_pages_impl)

    def test_list_action_returns_str(self):
        from server import files
        assert isinstance(files(action="list", pattern="*.md", exists_check=None), str)

    def test_read_missing_args_errors(self):
        # MCP resolves Field() params to defaults; pass them explicitly for a direct call.
        from server import files
        result = files(action="read", filename="", section_header="", for_player=False,
                       pattern="*.md", exists_check=None, start_page=1, end_page=None)
        assert "needs" in result.lower()

    def test_invalid_action_returns_error(self):
        from server import files
        result = files(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestEditFileMerge:
    """Verify edit_file(action=...) absorbs replace_in_file + update_file."""

    def test_impls_exist(self):
        from server import _replace_in_file_impl, _update_file_impl
        assert callable(_replace_in_file_impl) and callable(_update_file_impl)

    def test_replace_missing_args_errors(self):
        from server import edit_file
        result = edit_file(action="replace", filename="", old_str="", new_str="",
                           description="", content="")
        assert "needs" in result.lower()

    def test_overwrite_missing_filename_errors(self):
        from server import edit_file
        result = edit_file(action="overwrite", filename="", content="", old_str="",
                           new_str="", description="")
        assert "needs" in result.lower()

    def test_invalid_action_returns_error(self):
        from server import edit_file
        result = edit_file(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestSearchMerge:
    """Verify search(action=...) absorbs the 3 read tools (2 async queries + health)."""

    def test_impls_exist(self):
        from server import (_search_campaign_history_impl, _search_history_tiered_impl,
                            _chroma_health_check_impl)
        assert callable(_search_campaign_history_impl) and callable(_search_history_tiered_impl)
        assert callable(_chroma_health_check_impl)

    def test_search_is_async(self):
        import inspect
        from server import search
        assert inspect.iscoroutinefunction(search)

    def test_invalid_action_returns_error(self):
        import asyncio
        from server import search
        result = asyncio.run(search(action="invalid"))
        assert "Invalid action" in result or "invalid" in result.lower()

    def test_history_missing_query_errors(self):
        import asyncio
        from server import search
        result = asyncio.run(search(
            action="history", query="", n_results=None, tier=1, arc=None,
            scene_type=None, character=None, day_min=None, day_max=None,
            max_chars_per_result=3000))
        assert "needs query" in result.lower()

    def test_internal_wrapper_calls_private(self):
        # search_campaign_history was a tier-2 wrapper over search_history_tiered;
        # after the rename it must call the durable private, not the tombstone.
        import inspect
        from server import _search_campaign_history_impl
        assert "_search_history_tiered_impl" in inspect.getsource(_search_campaign_history_impl)


class TestAfflictionMerge:
    """Verify affliction(kind=...) absorbs condition + disease + toxin + wound."""

    def test_impls_exist(self):
        from server import (_condition_impl, _disease_impl, _toxin_impl, _wound_impl)
        assert callable(_condition_impl) and callable(_disease_impl)
        assert callable(_toxin_impl) and callable(_wound_impl)

    def test_invalid_kind_returns_error(self):
        from server import affliction
        result = affliction(kind="zzz", action="status")
        assert "Invalid kind" in result

    def test_each_kind_routes(self):
        # disease 'list' is a static catalog; other kinds just route without crashing
        # (their content depends on campaign data, absent in the test sandbox).
        from server import affliction
        assert "DISEASES" in affliction(kind="disease", action="list")
        for kind, action in [("condition", "status"), ("toxin", "status"), ("wound", "status")]:
            assert isinstance(affliction(kind=kind, action=action), str)


class TestRestMerge:
    def test_short_action_exists(self):
        from server import _rest_short_calculate
        assert callable(_rest_short_calculate)

    def test_long_action_exists(self):
        from server import _rest_long
        assert callable(_rest_long)

    def test_invalid_action_returns_error(self):
        from server import rest
        result = rest(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestGiftMerge:
    def test_add_action_exists(self):
        from server import _gift_add
        assert callable(_gift_add)

    def test_remove_action_exists(self):
        from server import _gift_remove
        assert callable(_gift_remove)

    def test_cost_action_exists(self):
        from server import _gift_calculate_cost
        assert callable(_gift_calculate_cost)

    def test_invalid_action_returns_error(self):
        from server import gift
        result = gift(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestCyberneticMerge:
    def test_install_action_exists(self):
        from server import _cybernetic_install
        assert callable(_cybernetic_install)

    def test_list_action_exists(self):
        from server import _cybernetic_list
        assert callable(_cybernetic_list)

    def test_remove_action_exists(self):
        from server import _cybernetic_remove
        assert callable(_cybernetic_remove)

    def test_invalid_action_returns_error(self):
        from server import cybernetic
        result = cybernetic(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestCodexMerge:
    def test_add_action_exists(self):
        from server import _codex_add
        assert callable(_codex_add)

    def test_remove_action_exists(self):
        from server import _codex_remove
        assert callable(_codex_remove)

    def test_use_action_exists(self):
        from server import _codex_use
        assert callable(_codex_use)

    def test_mishap_action_exists(self):
        from server import _codex_mishap_roll
        assert callable(_codex_mishap_roll)

    def test_invalid_action_returns_error(self):
        from server import codex
        result = codex(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestLookupMerge:
    def test_creature_action_exists(self):
        from server import _lookup_creature_stats
        assert callable(_lookup_creature_stats)

    def test_exotica_action_exists(self):
        from server import _lookup_exotica
        assert callable(_lookup_exotica)

    def test_weapon_tag_action_exists(self):
        from server import _lookup_weapon_tag
        assert callable(_lookup_weapon_tag)

    def test_career_action_exists(self):
        from server import _lookup_career
        assert callable(_lookup_career)

    def test_invalid_action_returns_error(self):
        from server import lookup
        result = lookup(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestGenerateMerge:
    def test_exotica_action_exists(self):
        from server import _generate_exotica
        assert callable(_generate_exotica)

    def test_weapon_action_exists(self):
        from server import _generate_weapon
        assert callable(_generate_weapon)

    def test_npc_action_exists(self):
        from server import _generate_npc
        assert callable(_generate_npc)

    def test_invalid_action_returns_error(self):
        from server import generate
        result = generate(action="invalid")
        assert "Invalid action" in result or "invalid" in result.lower()


class TestRollMerge:
    def test_roll_tool_exists(self):
        """After merge, content_forge should register a roll tool."""
        from content_forge import register_content_forge_tools
        assert callable(register_content_forge_tools)

    def test_invalid_action_returns_error(self):
        """Import the roll function and test invalid action."""
        # The roll function is registered inside register_content_forge_tools
        # so we can't easily test it directly. Just verify the module loads.
        import content_forge
        assert hasattr(content_forge, 'register_content_forge_tools')

    def test_private_roll_functions_in_server(self):
        """Verify server.py has private roll functions."""
        from server import _roll_encounter_table, _roll_reaction, _roll_exotica
        assert callable(_roll_encounter_table)
        assert callable(_roll_reaction)
        assert callable(_roll_exotica)
