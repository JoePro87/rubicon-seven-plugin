import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from server import _filter_dm_only_content, _read_file_section_impl as read_file_section


# =============================================================================
# Tests for _filter_dm_only_content()
# =============================================================================

def test_filter_dm_block_with_structure():
    """Pattern 1: ⛔ DM ONLY ⛔ blocks should be replaced with placeholder."""
    content = """
## Room Description

This is the entrance hall.

⛔ DM ONLY ⛔
The guardian has 18 HP and attacks at +3.
It guards the secret vault key.
⛔ END DM ONLY ⛔

The walls are carved with ancient symbols.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    assert "⛔ DM ONLY ⛔" not in result
    assert "18 HP" not in result
    assert "secret vault key" not in result
    assert "[DM content removed]" in result
    assert "entrance hall" in result
    assert "ancient symbols" in result


def test_filter_dm_block_without_structure():
    """Pattern 1: DM blocks removed entirely when preserve_structure=False."""
    content = """
## Room Description

⛔ DM ONLY ⛔
Secret monster stats here.
⛔ END DM ONLY ⛔

Visible description.
"""

    result = _filter_dm_only_content(content, preserve_structure=False)

    assert "⛔ DM ONLY ⛔" not in result
    assert "Secret monster stats" not in result
    assert "[DM content removed]" not in result
    assert "Visible description" in result


def test_filter_dm_only_secret():
    """Pattern 2: Secrets with dm_only scope should be filtered."""
    content = """
## SECRETS

### SECRET: hidden_passage

**Scope:** dm_only

**Truth:** There's a hidden passage behind the north tapestry that leads to the treasure vault.

**Reveal Trigger:** DC 14 INT save to notice draft

### SECRET: obvious_clue

**Scope:** party_known

**Truth:** The bloodstains lead toward the eastern corridor.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # dm_only secret should be filtered
    assert "hidden_passage" not in result or "[Secret content removed]" in result
    assert "treasure vault" not in result

    # party_known secret should remain
    assert "obvious_clue" in result
    assert "bloodstains" in result
    assert "eastern corridor" in result


def test_filter_party_known_secret_preserved():
    """Pattern 2: party_known secrets should NOT be filtered."""
    content = """
### SECRET: discovered_fact

**Scope:** party_known

**Truth:** The party knows the cult meets on new moons.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    assert "discovered_fact" in result
    assert "cult meets on new moons" in result
    assert "[Secret content removed]" not in result


def test_filter_npc_dm_state():
    """Pattern 3: **State (dm_only):** subsections should be filtered."""
    content = """
## NPCs

### Zara the Merchant

**Description:** A weathered cacogen trader with brass augments.

**State (dm_only):** Zara knows the vault code but won't share it. She's actually a syndicate spy.

**Wants:** Safe passage to Gnomon
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    assert "Zara the Merchant" in result
    assert "weathered cacogen" in result
    assert "Safe passage to Gnomon" in result

    # dm_only state should be filtered
    assert "vault code" not in result
    assert "syndicate spy" not in result
    assert "[DM state removed]" in result or "State (dm_only)" not in result


def test_filter_inline_dm_only_markers():
    """Pattern 4: Lines with (dm_only) or [dm_only] markers should be filtered."""
    content = """
## Room Features

- Ancient murals on the walls
- A locked chest [dm_only]
- Strange glowing crystals
- Hidden trapdoor (dm_only)
- Dusty shelves with scrolls
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # Visible content preserved
    assert "Ancient murals" in result
    assert "Strange glowing crystals" in result
    assert "Dusty shelves" in result

    # dm_only lines filtered
    assert "locked chest" not in result or "[DM note removed]" in result
    assert "Hidden trapdoor" not in result or "[DM note removed]" in result


def test_filter_inline_markers_case_insensitive():
    """Pattern 4: (DM_ONLY) and [DM_Only] should also be filtered."""
    content = """
- Visible item
- Secret treasure (DM_ONLY)
- Another visible item
- Hidden passage [DM_Only]
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    assert "Visible item" in result
    assert "Another visible item" in result
    assert "Secret treasure" not in result or "[DM note removed]" in result
    assert "Hidden passage" not in result or "[DM note removed]" in result


def test_filter_whitespace_cleanup():
    """Filtered content should have cleaned-up whitespace."""
    content = """
## Section

Paragraph 1.

⛔ DM ONLY ⛔
DM secret.
⛔ END DM ONLY ⛔



Paragraph 2.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # Should not have 3+ consecutive blank lines
    assert "\n\n\n" not in result
    # Should have double newlines between elements
    assert "\n\n" in result


def test_filter_multiple_patterns_combined():
    """All 4 filter patterns working together."""
    content = """
## The Chamber

The room is vast and echoing.

⛔ DM ONLY ⛔
Guardian: 22 HP, attacks at +4
⛔ END DM ONLY ⛔

- Ancient machinery
- Control panel (dm_only)

### SECRET: vault_access

**Scope:** dm_only

**Truth:** The control panel opens the vault if you enter the code.

### SECRET: visible_clue

**Scope:** party_known

**Truth:** Scorch marks suggest recent energy weapon fire.

**NPC State (dm_only):** The engineer sabotaged the system before fleeing.

South exit leads to the archives.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # Visible content preserved
    assert "vast and echoing" in result
    assert "Ancient machinery" in result
    assert "South exit" in result
    assert "visible_clue" in result
    assert "Scorch marks" in result

    # DM-only content filtered
    assert "22 HP" not in result
    assert "Control panel" not in result or "[DM note removed]" in result
    assert "vault_access" not in result or "[Secret content removed]" in result
    assert "engineer sabotaged" not in result


def test_filter_empty_content():
    """Empty string should return empty string."""
    result = _filter_dm_only_content("", preserve_structure=True)
    assert result == ""


def test_filter_no_dm_content():
    """Content with no DM markers should pass through unchanged."""
    content = """
## Ordinary Section

This is completely visible to players.

- Item 1
- Item 2

Nothing secret here.
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # Should be identical (modulo whitespace trimming)
    assert "Ordinary Section" in result
    assert "completely visible to players" in result
    assert "Item 1" in result
    assert "Item 2" in result
    assert "Nothing secret" in result


# =============================================================================
# Tests for read_file_section() integration
# =============================================================================

def test_read_file_section_backward_compatibility(tmp_path):
    """read_file_section() without for_player should work as before."""
    # Create test file
    test_file = tmp_path / "test_prep.md"
    test_file.write_text("""
## Introduction

Welcome to the vault.

⛔ DM ONLY ⛔
Secret DM notes here.
⛔ END DM ONLY ⛔

## Room 1

First room description.
""", encoding='utf-8')

    # Call with explicit for_player=False (testing backward compatibility)
    result = read_file_section(filename=str(test_file), section_header="Introduction", for_player=False)

    # Should include DM content when for_player=False
    assert "Welcome to the vault" in result
    assert "Secret DM notes here" in result
    assert "⛔ DM ONLY ⛔" in result


def test_read_file_section_for_player_true(tmp_path):
    """read_file_section() with for_player=True should filter DM content."""
    test_file = tmp_path / "test_prep.md"
    test_file.write_text("""
## The Entrance

You enter a grand hall.

⛔ DM ONLY ⛔
The guardian has 18 HP.
⛔ END DM ONLY ⛔

Murals cover the walls.
""", encoding='utf-8')

    # Call with for_player=True
    result = read_file_section(
        filename=str(test_file),
        section_header="The Entrance",
        for_player=True
    )

    # Should filter DM content
    assert "grand hall" in result
    assert "Murals cover the walls" in result
    assert "18 HP" not in result
    assert "⛔ DM ONLY ⛔" not in result
    assert "[DM content removed]" in result


def test_read_file_section_for_player_false(tmp_path):
    """read_file_section() with for_player=False should NOT filter."""
    test_file = tmp_path / "test_prep.md"
    test_file.write_text("""
## The Vault

Main description.

⛔ DM ONLY ⛔
Trap: DC 16 DEX save or 2d6 damage.
⛔ END DM ONLY ⛔
""", encoding='utf-8')

    result = read_file_section(
        filename=str(test_file),
        section_header="The Vault",
        for_player=False
    )

    # Should include everything
    assert "Main description" in result
    assert "Trap: DC 16 DEX save" in result
    assert "⛔ DM ONLY ⛔" in result


def test_read_file_section_filters_secrets(tmp_path):
    """read_file_section() with for_player=True filters dm_only secrets."""
    test_file = tmp_path / "test_prep.md"
    test_file.write_text("""
## Secrets Section

### SECRET: hidden_truth

**Scope:** dm_only

**Truth:** The artifact is a fake planted by the syndicate.

### SECRET: known_fact

**Scope:** party_known

**Truth:** The party knows about the cult's meeting place.
""")

    result = read_file_section(
        filename=str(test_file),
        section_header="Secrets Section",
        for_player=True
    )

    # dm_only secret filtered
    assert "artifact is a fake" not in result

    # party_known secret preserved
    assert "known_fact" in result
    assert "cult's meeting place" in result


def test_read_file_section_nonexistent_file():
    """read_file_section() with nonexistent file should raise error."""
    with pytest.raises(Exception):
        read_file_section(
            filename="/nonexistent/file.md",
            section_header="Any Section",
            for_player=True
        )


def test_read_file_section_missing_header(tmp_path):
    """read_file_section() with missing section should return error string."""
    test_file = tmp_path / "test_prep.md"
    test_file.write_text("""
## Existing Section

Content here.
""")

    result = read_file_section(
        filename=str(test_file),
        section_header="Nonexistent Section",
        for_player=True
    )

    # Should return error message, not raise exception
    assert result.startswith("Error:")
    assert "not found" in result
