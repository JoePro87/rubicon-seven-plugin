"""Tests for lorebook audit script."""
import json
import tempfile
from pathlib import Path

import pytest


class TestExtractPronouns:
    def test_parens_format(self):
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Harlow (she/her). Cacogen mechanic.") == "she/her"

    def test_compound_parens(self):
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Kess (she/her/they/them). Cacogen veteran.") == "she/her/they/them"

    def test_pronouns_colon_format(self):
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Kessira Vek'thuun (Kess). Pronouns: she/her/they/them. Cacogen.") == "she/her/they/them"

    def test_standalone_pronouns_without_parens(self):
        """Standalone he/him in running text (no parens, no colon)."""
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Silas the Archivist: Synth philosopher, he/him.") == "he/him"

    def test_gender_fallback(self):
        """male/female as last resort when no pronoun slash-pairs found."""
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Reaches: Neobloom elder, male, vine-based.") == "male"

    def test_parens_wins_over_colon(self):
        """Parens format takes priority over colon format."""
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Name (he/him). Pronouns: they/them.") == "he/him"

    def test_no_pronouns_found(self):
        from scripts.audit_lorebook import extract_pronouns
        assert extract_pronouns("Petname: Brek → Mira.") is None

    def test_only_searches_first_200_chars(self):
        from scripts.audit_lorebook import extract_pronouns
        text = "A" * 201 + " (she/her)"
        assert extract_pronouns(text) is None


class TestExtractSpecies:
    def test_known_species(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Harlow (she/her). Cacogen mechanic.") == "cacogen"

    def test_true_kin(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Petros. True-kin, Varro's nephew.") == "true-kin"

    def test_synth(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Roscar (he/him). Synth chronicler, Level 4.") == "synth"

    def test_neobloom(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Brek. Neobloom, photosynthesizes.") == "neobloom"

    def test_synthesis_being(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Harbinger is a 1,698-year-old synthesis being.") == "synthesis being"

    def test_no_species_found(self):
        from scripts.audit_lorebook import extract_species
        assert extract_species("Petname: Brek → Mira.") is None

    def test_only_searches_first_200_chars(self):
        from scripts.audit_lorebook import extract_species
        text = "A" * 201 + " cacogen"
        assert extract_species(text) is None


class TestGenerateShortContext:
    def test_sentence_boundary_cut(self):
        from scripts.audit_lorebook import generate_short_context
        text = "First sentence. Second sentence. Third sentence that is quite long and goes on and on and on and on and on."
        result = generate_short_context(text, max_chars=60)
        assert result.endswith(".")
        assert len(result) <= 60

    def test_word_boundary_fallback(self):
        from scripts.audit_lorebook import generate_short_context
        text = "One very long sentence without any periods that just keeps going and going and going forever"
        result = generate_short_context(text, max_chars=50)
        assert not result.endswith(" ")
        assert len(result) <= 50

    def test_short_text_unchanged(self):
        from scripts.audit_lorebook import generate_short_context
        text = "Short text."
        assert generate_short_context(text, max_chars=450) == text

    def test_empty_text(self):
        from scripts.audit_lorebook import generate_short_context
        assert generate_short_context("", max_chars=450) == ""


SAMPLE_LOREBOOK = {
    "meta": {"version": 2, "last_updated": "2026-03-08", "description": "test", "schema_notes": "v2"},
    "entries": [
        {"keywords": ["harlow"], "category": "people", "status": "CANONICAL",
         "context": "Harlow (she/her). Cacogen mechanic, Arthropoda Sapiens. Chosen sister. " * 8,
         "short_context": "Existing short context."},
        {"keywords": ["echoe"], "category": "people", "status": "ESTABLISHED",
         "context": "Echoe. Pre-Collapse consciousness. Pronouns: she/her. Woke Day 103. " * 8,
         "short_context": ""},
        {"keywords": ["terrace garden"], "category": "places", "status": "ESTABLISHED",
         "context": "The Terrace Garden spans three tiers. " * 20,
         "short_context": ""},
        {"keywords": ["stupid"], "category": "continuity", "status": "ESTABLISHED",
         "context": "Running joke between Brek and Mira.", "short_context": ""},
    ]
}


class TestAuditLorebook:
    def _make_tmp(self):
        """Create a temp dir that persists until test cleanup."""
        d = tempfile.mkdtemp()
        return Path(d)

    def _run_audit(self, lorebook=None, frequency_data=None, dry_run=False, report=False):
        from scripts.audit_lorebook import audit_lorebook
        lb = lorebook or SAMPLE_LOREBOOK
        tmp = self._make_tmp()
        lb_path = tmp / "lorebook.json"
        lb_path.write_text(json.dumps(lb, indent=2))
        report_path = tmp / "report.md" if report else None
        stats = audit_lorebook(lb_path, report_path=report_path, frequency_data=frequency_data, dry_run=dry_run)
        result_data = json.loads(lb_path.read_text())
        return stats, result_data, tmp

    def test_adds_pronouns_to_people(self):
        stats, data, _ = self._run_audit()
        harlow = data["entries"][0]
        assert harlow["pronouns"] == "she/her"

    def test_adds_species_to_people(self):
        stats, data, _ = self._run_audit()
        harlow = data["entries"][0]
        assert harlow["species"] == "arthropoda sapiens"

    def test_generates_missing_short_context(self):
        stats, data, _ = self._run_audit()
        echoe = data["entries"][1]
        assert echoe["short_context"]
        assert len(echoe["short_context"]) <= 450

    def test_preserves_existing_short_context(self):
        stats, data, _ = self._run_audit()
        harlow = data["entries"][0]
        assert harlow["short_context"] == "Existing short context."

    def test_no_identity_fields_on_non_people(self):
        stats, data, _ = self._run_audit()
        garden = data["entries"][2]
        assert "pronouns" not in garden
        assert "species" not in garden

    def test_bumps_schema_version(self):
        stats, data, _ = self._run_audit()
        assert data["meta"]["version"] == 3

    def test_creates_backup(self):
        _, _, tmp = self._run_audit()
        assert (tmp / "lorebook.json.bak").exists()

    def test_generates_report(self):
        freq = {"harlow": 5, "echoe": 1}
        stats, _, tmp = self._run_audit(frequency_data=freq, report=True)
        report = (tmp / "report.md").read_text()
        assert "High-Traffic Entries" in report
        assert "Auto-Generated short_context" in report
        assert "Identity Extraction Failures" in report

    def test_idempotent(self):
        from scripts.audit_lorebook import audit_lorebook
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            lb_path = tmp / "lorebook.json"
            lb_path.write_text(json.dumps(SAMPLE_LOREBOOK, indent=2))
            audit_lorebook(lb_path)
            first = json.loads(lb_path.read_text())
            audit_lorebook(lb_path)
            second = json.loads(lb_path.read_text())
            assert first == second

    def test_short_entries_untouched(self):
        stats, data, _ = self._run_audit()
        stupid = data["entries"][3]
        assert stupid["context"] == "Running joke between Brek and Mira."
        assert stupid["short_context"] == ""
