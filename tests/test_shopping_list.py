"""Tests for check_canon context shopping list (needs parameter)."""

import pytest

VALID_BLOCKS = {
    'voice', 'relationships', 'prep', 'npc_knowledge',
    'threads', 'history', 'characters', 'lorebook_full',
}
VALID_PREFIXED_BLOCKS = {'prep_npcs'}


def test_valid_blocks_defined():
    from server import CANON_BLOCKS
    assert CANON_BLOCKS == VALID_BLOCKS


def test_prefixed_blocks_defined():
    from server import CANON_PREFIXED_BLOCKS
    assert CANON_PREFIXED_BLOCKS == VALID_PREFIXED_BLOCKS


def test_resolve_needs_empty_returns_empty():
    from server import _resolve_canon_needs
    result = _resolve_canon_needs(needs=[], regex_blocks=set())
    assert result == set()


def test_resolve_needs_union():
    from server import _resolve_canon_needs
    result = _resolve_canon_needs(
        needs=['voice', 'relationships'],
        regex_blocks={'prep', 'voice', 'characters'}
    )
    assert result == {'voice', 'relationships', 'prep', 'characters'}


def test_resolve_needs_invalid_block_ignored():
    from server import _resolve_canon_needs
    result = _resolve_canon_needs(
        needs=['voice', 'INVALID_BLOCK', 'not_real'],
        regex_blocks=set()
    )
    assert result == {'voice'}


def test_resolve_needs_prefixed_block():
    from server import _resolve_canon_needs
    result = _resolve_canon_needs(
        needs=['prep_npcs:Drewe', 'voice'],
        regex_blocks=set()
    )
    assert result == {'prep_npcs:Drewe', 'voice'}


def test_resolve_needs_prefixed_block_invalid_prefix():
    from server import _resolve_canon_needs
    result = _resolve_canon_needs(
        needs=['fake_prefix:something'],
        regex_blocks=set()
    )
    assert result == set()


# ---- Regex-to-blocks mapping ----

REGEX_BLOCK_MAP_EXPECTED = {
    'scene_change': {'prep', 'voice', 'relationships', 'npc_knowledge', 'characters'},
    'session_start': VALID_BLOCKS,
    'scene_recall': {'history', 'lorebook_full', 'prep'},
    'intimate': {'voice', 'relationships', 'lorebook_full'},
    'lore_question': {'lorebook_full', 'history', 'threads'},
    'high_match_count': {'lorebook_full', 'threads', 'prep'},
    'explicit': VALID_BLOCKS,
}


def test_regex_block_map_exists():
    from server import REGEX_BLOCK_MAP
    assert REGEX_BLOCK_MAP == REGEX_BLOCK_MAP_EXPECTED


def test_regex_block_map_scene_change():
    from server import REGEX_BLOCK_MAP
    assert REGEX_BLOCK_MAP['scene_change'] == {'prep', 'voice', 'relationships', 'npc_knowledge', 'characters'}


def test_regex_block_map_intimate():
    from server import REGEX_BLOCK_MAP
    assert REGEX_BLOCK_MAP['intimate'] == {'voice', 'relationships', 'lorebook_full'}


def test_regex_block_map_session_start_is_all():
    from server import REGEX_BLOCK_MAP, CANON_BLOCKS
    assert REGEX_BLOCK_MAP['session_start'] == CANON_BLOCKS


def test_build_regex_blocks_scene_change():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': True, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='hello',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert 'prep' in result
    assert 'voice' in result
    assert 'scene_change' in reasons


def test_build_regex_blocks_intimate():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': False, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='i kiss her',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert 'voice' in result
    assert 'relationships' in result
    assert 'intimate' in reasons


def test_build_regex_blocks_lore_question():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': False, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='what do we know about the archive',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert 'lorebook_full' in result
    assert 'history' in result
    assert 'lore_question' in reasons


def test_build_regex_blocks_high_match_count():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': False, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='hello',
        scene_recall_triggered=False,
        lorebook_match_count=5,
    )
    assert 'lorebook_full' in result
    assert 'threads' in result
    assert 'high_match_count' in reasons


def test_build_regex_blocks_session_start():
    from server import _build_regex_blocks, CANON_BLOCKS
    hook_state = {'scene_changed': False, 'turn_count': 1}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='hello',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert result == CANON_BLOCKS
    assert 'session_start' in reasons


def test_build_regex_blocks_multiple_triggers_union():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': True, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='i kiss her',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert 'prep' in result
    assert 'lorebook_full' in result
    assert 'scene_change' in reasons
    assert 'intimate' in reasons


def test_build_regex_blocks_no_triggers():
    from server import _build_regex_blocks
    hook_state = {'scene_changed': False, 'turn_count': 5}
    result, reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower='hello',
        scene_recall_triggered=False,
        lorebook_match_count=0,
    )
    assert result == set()
    assert reasons == []
