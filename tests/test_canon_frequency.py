"""Tests for check_canon frequency reduction logic."""
import pytest


class TestCanonRequiredDecision:
    """Test the canon_required decision logic from turn_reset.py."""

    def test_turn_1_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=1, scene_changed=False) is True

    def test_turn_2_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=2, scene_changed=False) is True

    def test_turn_3_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=3, scene_changed=False) is True

    def test_turn_4_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=4, scene_changed=False) is False

    def test_turn_5_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=5, scene_changed=False) is False

    def test_turn_6_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False) is True

    def test_turn_7_skips(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=7, scene_changed=False) is False

    def test_turn_9_requires(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=9, scene_changed=False) is True

    def test_scene_change_overrides_skip(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=4, scene_changed=True) is True

    def test_scene_change_on_required_turn(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=True) is True

    def test_high_turn_modulo_pattern(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=30, scene_changed=False) is True
        assert should_require_canon(turn_count=31, scene_changed=False) is False
        assert should_require_canon(turn_count=32, scene_changed=False) is False
        assert should_require_canon(turn_count=33, scene_changed=False) is True


class TestTurnResetIntegration:
    """Test that turn_reset.py writes canon_required to state correctly."""

    def test_state_dict_includes_canon_required_on_skip(self):
        """Verify the state dict shape when canon is not required."""
        from hooks.turn_reset import should_require_canon
        turn_count = 5
        scene_changed = False
        canon_required = should_require_canon(turn_count, scene_changed)
        state = {
            "canon_verified": False,
            "canon_succeeded": False,
            "canon_required": canon_required,
            "turn_count": turn_count,
        }
        assert state["canon_required"] is False
        assert state["canon_verified"] is False

    def test_state_dict_includes_canon_required_on_require(self):
        """Verify the state dict shape when canon IS required."""
        from hooks.turn_reset import should_require_canon
        turn_count = 6
        scene_changed = False
        canon_required = should_require_canon(turn_count, scene_changed)
        state = {
            "canon_verified": False,
            "canon_succeeded": False,
            "canon_required": canon_required,
            "turn_count": turn_count,
        }
        assert state["canon_required"] is True
        assert state["canon_verified"] is False


class TestConsolidatedStopCanonRequired:
    """Test that _check_canon respects canon_required flag."""

    def test_canon_not_required_passes(self):
        """When canon_required=False, response should not be blocked."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_required": False,
            "canon_verified": False,
            "session_type": "gameplay",
            "skip_canon_enforcement": False,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False

    def test_canon_required_and_verified_passes(self):
        """When canon_required=True and canon_verified=True, pass."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_required": True,
            "canon_verified": True,
            "session_type": "gameplay",
            "skip_canon_enforcement": False,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False

    def test_canon_required_and_not_verified_blocks(self):
        """When canon_required=True and canon_verified=False, the miss is logged
        but NOT hard-blocked. The stop hook was converted to soft-log-only
        (consolidated_stop_check.py:464-481 always returns (False,"",{}); commit
        6a7a862 "remove all blocking from stop hook"). Blocking caused visible
        rewrite-cycle artifacts; Claude self-corrects from the logged miss."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_required": True,
            "canon_verified": False,
            "session_type": "gameplay",
            "skip_canon_enforcement": False,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False

    def test_missing_canon_required_defaults_to_true(self):
        """If canon_required is missing from state, it still defaults to True
        (line 461), so the unverified branch is reached — but that branch now
        soft-logs instead of blocking (soft-log refactor). No hard block."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_verified": False,
            "session_type": "gameplay",
            "skip_canon_enforcement": False,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False

    def test_maintenance_bypass_still_works(self):
        """skip_canon_enforcement=True bypasses regardless of canon_required."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_required": True,
            "canon_verified": False,
            "session_type": "gameplay",
            "skip_canon_enforcement": True,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False

    def test_development_mode_still_bypasses(self):
        """session_type != gameplay bypasses regardless of canon_required."""
        from hooks.consolidated_stop_check import _check_canon
        state = {
            "canon_required": True,
            "canon_verified": False,
            "session_type": "development",
            "skip_canon_enforcement": False,
            "approved_hooks": [],
        }
        hook_input = {}
        blocked, reason, updates = _check_canon(hook_input, state)
        assert blocked is False


class TestAdminMessageBypass:
    """Test that admin messages skip canon requirement."""

    def test_confirm_save_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="confirm save") is False

    def test_save_game_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="save the game") is False

    def test_set_active_prep_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="set active prep CERULINE_ARCOLOGY_PREP.md") is False

    def test_toggle_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="toggle canon enforcement") is False

    def test_narrative_message_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="Creenash walks to the garden") is True

    def test_empty_message_requires_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="") is True

    def test_admin_on_skip_turn_still_skips(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=4, scene_changed=False, user_message="confirm save") is False

    def test_scene_change_overrides_admin(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=4, scene_changed=True, user_message="confirm save") is True

    def test_end_session_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="end session") is False

    def test_reload_prep_skips_canon(self):
        from hooks.turn_reset import should_require_canon
        assert should_require_canon(turn_count=6, scene_changed=False, user_message="reload prep") is False
