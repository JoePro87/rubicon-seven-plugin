"""Lorebook audit script — identity extraction and short context generation."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


# Pronoun patterns in priority order
_PAREN_PRONOUNS = re.compile(r"\((\w+/\w+(?:/\w+)*)\)")
_COLON_PRONOUNS = re.compile(r"[Pp]ronouns:\s*(\w+/\w+(?:/\w+)*)")
_STANDALONE_PRONOUNS = re.compile(r"\b(he/him|she/her|they/them)\b", re.IGNORECASE)
_GENDER_FALLBACK = re.compile(r"\b(male|female)\b", re.IGNORECASE)

# Species list ordered longest-first
_SPECIES = [
    "synthesis being",
    "arthropoda sapiens",
    "true-kin",
    "cacogen",
    "neobloom",
    "newbeast",
    "chattersnipe",
    "mantid",
    "synth",
    "faa",
    "crystalline",
    "automata",
    "planeyfolk",
    "windweird",
]


def extract_pronouns(context: str) -> str | None:
    """Extract pronouns from first 200 chars of context text."""
    text = context[:200]

    for pattern in (_PAREN_PRONOUNS, _COLON_PRONOUNS, _STANDALONE_PRONOUNS, _GENDER_FALLBACK):
        m = pattern.search(text)
        if m:
            return m.group(1).lower()

    return None


def extract_species(context: str) -> str | None:
    """Extract species from first 200 chars of context text."""
    text = context[:200].lower()

    for species in _SPECIES:
        if species in text:
            return species

    return None


def generate_short_context(context: str, max_chars: int = 450) -> str:
    """Truncate at sentence boundary if past 50% of budget, else word boundary."""
    if not context or len(context) <= max_chars:
        return context

    half = max_chars // 2

    # Try sentence boundary
    last_sentence = context.rfind(". ", half, max_chars)
    if last_sentence != -1:
        return context[: last_sentence + 1]

    # Word boundary fallback
    truncated = context[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]

    return truncated


def _write_report(
    report_path: Path,
    entries: list[dict],
    stats: dict,
    frequency_data: dict | None,
) -> None:
    """Write a markdown audit report."""
    lines = ["# Lorebook Audit Report\n"]

    # Section A: High-Traffic Entries
    lines.append("## Section A: High-Traffic Entries\n")
    freq = frequency_data or {}
    high_traffic = []
    for e in entries:
        kw = e["keywords"][0]
        f = freq.get(kw, 0)
        if f >= 3 and len(e.get("context", "")) > 500:
            high_traffic.append(e)
    if high_traffic:
        lines.append("| keyword | freq | ctx_len | pronouns | species | short_context |")
        lines.append("|---------|------|---------|----------|---------|---------------|")
        for e in high_traffic:
            kw = e["keywords"][0]
            sc = (e.get("short_context") or "")[:100]
            lines.append(f"| {kw} | {freq.get(kw, 0)} | {len(e.get('context', ''))} | {e.get('pronouns', '')} | {e.get('species', '')} | {sc} |")
    else:
        lines.append("No high-traffic entries found.\n")

    # Section B: Auto-Generated short_context
    lines.append("\n## Section B: Auto-Generated short_context\n")
    for kw in stats.get("auto_generated_short", []):
        entry = next((e for e in entries if e["keywords"][0] == kw), None)
        if entry:
            lines.append(f"- **{kw}**: {entry.get('short_context', '')}\n")

    # Section C: Identity Extraction Failures
    lines.append("\n## Section C: Identity Extraction Failures\n")
    failures = stats.get("identity_failures", [])
    if failures:
        lines.append("| keyword | missing |")
        lines.append("|---------|---------|")
        for f_entry in failures:
            lines.append(f"| {f_entry['keyword']} | {f_entry['missing']} |")
    else:
        lines.append("No identity extraction failures.\n")

    report_path.write_text("\n".join(lines))


def audit_lorebook(
    lorebook_path: Path,
    report_path: Path | None = None,
    frequency_data: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Run bulk audit: extract identity fields, generate short contexts, bump schema."""
    lorebook_path = Path(lorebook_path)
    data = json.loads(lorebook_path.read_text())
    entries = data.get("entries", [])

    stats = {
        "total": len(entries),
        "pronouns_added": 0,
        "species_added": 0,
        "short_context_generated": 0,
        "identity_failures": [],
        "auto_generated_short": [],
    }

    for entry in entries:
        cat = entry.get("category", "")
        ctx = entry.get("context", "")
        kw = entry["keywords"][0]

        # Identity extraction for people/npcs
        if cat in ("people", "npcs"):
            if "pronouns" not in entry:
                p = extract_pronouns(ctx)
                if p:
                    entry["pronouns"] = p
                    stats["pronouns_added"] += 1
                else:
                    stats["identity_failures"].append({"keyword": kw, "missing": "pronouns"})

            if "species" not in entry:
                s = extract_species(ctx)
                if s:
                    entry["species"] = s
                    stats["species_added"] += 1
                else:
                    stats["identity_failures"].append({"keyword": kw, "missing": "species"})

        # Short context generation for all entries
        sc = entry.get("short_context", "")
        if not sc and len(ctx) > 450:
            entry["short_context"] = generate_short_context(ctx, 450)
            stats["short_context_generated"] += 1
            stats["auto_generated_short"].append(kw)

    # Bump schema
    data["meta"]["version"] = 3
    data["meta"]["schema_notes"] = "v3 — identity fields + short_context audit"

    if not dry_run:
        shutil.copy2(lorebook_path, str(lorebook_path) + ".bak")
        lorebook_path.write_text(json.dumps(data, indent=2))

    if report_path:
        _write_report(Path(report_path), entries, stats, frequency_data)

    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Audit lorebook.json")
    parser.add_argument("--lorebook", type=Path, required=True, help="Path to lorebook.json")
    parser.add_argument("--frequency", type=Path, default=None, help="Path to frequency JSON")
    parser.add_argument("--report", type=Path, default=None, help="Path for output report")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    args = parser.parse_args()

    freq = None
    if args.frequency:
        freq = json.loads(args.frequency.read_text())

    stats = audit_lorebook(args.lorebook, report_path=args.report, frequency_data=freq, dry_run=args.dry_run)

    print(f"Total entries: {stats['total']}")
    print(f"Pronouns added: {stats['pronouns_added']}")
    print(f"Species added: {stats['species_added']}")
    print(f"Short contexts generated: {stats['short_context_generated']}")
    print(f"Identity failures: {len(stats['identity_failures'])}")


if __name__ == "__main__":
    main()
