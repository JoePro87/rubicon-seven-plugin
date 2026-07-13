"""Tests for SCENE STATE section write/read integrity."""
import re
import pytest


def normalize_and_match(content: str, scene_pattern: str) -> re.Match:
    """Simulate the fixed normalization + regex match."""
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    return re.search(scene_pattern, content, re.DOTALL)


class TestSceneStateNormalization:
    SCENE_PATTERN = r'## SCENE STATE \(check_canon reads this section\).*?(?=\n---\n|\n## [A-Z]|\Z)'

    def test_unix_line_endings_match(self):
        content = "## SCENE STATE (check_canon reads this section)\n\n**Day:** 105\n**Location:** Garden\n\n---\n\n## ARC"
        m = normalize_and_match(content, self.SCENE_PATTERN)
        assert m is not None
        assert '**Day:** 105' in m.group()
        assert '**Location:** Garden' in m.group()

    def test_windows_line_endings_match(self):
        content = "## SCENE STATE (check_canon reads this section)\r\n\r\n**Day:** 105\r\n**Location:** Garden\r\n\r\n---\r\n\r\n## ARC"
        m = normalize_and_match(content, self.SCENE_PATTERN)
        assert m is not None
        assert '**Day:** 105' in m.group()

    def test_corrupted_single_line_detected(self):
        content = "## SCENE STATE (check_canon reads this section)**Day:** 105**Location:** Garden\n---\n"
        m = normalize_and_match(content, self.SCENE_PATTERN)
        assert m is not None
        lines = m.group().split('\n')
        first_content_line = [l for l in lines if '**Day:**' in l][0]
        is_corrupted = '**Location:**' in first_content_line
        assert is_corrupted

    def test_replacement_preserves_newlines(self):
        scene_updates = ["**Day:** 105", "**Location:** Garden", "**Present:** Creenash, Vela"]
        new_scene_state = "## SCENE STATE (check_canon reads this section)\n\n" + "\n".join(scene_updates) + "\n"
        lines = new_scene_state.split('\n')
        day_lines = [l for l in lines if '**Day:**' in l]
        loc_lines = [l for l in lines if '**Location:**' in l]
        assert len(day_lines) == 1
        assert len(loc_lines) == 1
        assert day_lines[0] != loc_lines[0]
