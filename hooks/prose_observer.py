#!/usr/bin/env python3
"""Fire-and-forget prose observer for narrative phrase discipline.

Invoked as a detached child process from consolidated_stop_check.py.
Reads session state + narrator response from a temp file (path as argv[1]),
calls the judge model (Haiku 4.5) via the anthropic SDK using a forced
tool-use schema, writes findings to catch_analytics.json.

The tool-use path is load-bearing: free-form JSON output from Haiku was
unreliable (643 consecutive parse failures in the pre-structured build).
A forced tool call returns structured input we can trust.

ALL failure modes exit 0 (fail-open). The observer is advisory — it must
never interfere with session flow.
"""

import json
import os
import sys
import time
from pathlib import Path

# Hooks directory on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks import analytics_utils
from hooks.hook_utils import temp_dir

# --- Paths and constants ----------------------------------------------------

HOOKS_DIR = Path(__file__).parent
JUDGE_PROMPT_FILE = HOOKS_DIR / "judge_prompt.txt"
from rubicon_paths import campaign_dir as _campaign_dir
STYLE_EXEMPLARS_FILE = _campaign_dir() / "docs" / "references" / "style-exemplars.md"
ERROR_LOG = HOOKS_DIR / "observer_errors.log"
API_KEY_FILE = Path.home() / ".rubicon-seven" / "api_key"
TEMP_FILE_PREFIX = "rubicon_observer_"
ORPHAN_AGE_SECONDS = 3600  # 1 hour
API_TIMEOUT_SECONDS = 30
MODEL = "claude-haiku-4-5-20251001"
MAX_OUTPUT_TOKENS = 1024

# Category enum — keep in sync with judge_prompt.txt.
VIOLATION_CATEGORIES = [
    "Reaction Shot",
    "Emotional Beat",
    "The Pause",
    "Transition",
    "Landing",
    "Characterization",
    "Negation-Correction",
    "Voice Modulation",
    "Travel Math",
    "Density Drift",
    "Synthesis Incoherence",
]

# Normalization map — Haiku sometimes returns the longer bolded label text from
# the prompt (e.g., "The Pause as actor") instead of the short enum name.
# This coerces known variants back to canonical short names so analytics stays tidy.
CATEGORY_NORMALIZATION = {
    "Reaction Shot defaults": "Reaction Shot",
    "Emotional Beat abstraction": "Emotional Beat",
    "The Pause as actor": "The Pause",
    "Transition duration-padding": "Transition",
    "The Landing — impact metaphor": "Landing",
    "The Landing - impact metaphor": "Landing",
    "Characterization shorthand": "Characterization",
    "Negation-correction": "Negation-Correction",
    "Voice modulation tags": "Voice Modulation",
    "Travel-math errors": "Travel Math",
}


# Case-fold lookup onto the canonical enum — Haiku returns e.g. "Density drift"
# where the enum key is "Density Drift", which otherwise split analytics into
# two buckets for one family.
_CANONICAL_BY_LOWER = {c.lower(): c for c in VIOLATION_CATEGORIES}


def _normalize_category(cat: str) -> str:
    """Coerce long-label categories to canonical short names, then case-fold to
    the canonical VIOLATION_CATEGORIES casing. Unknown categories pass through."""
    if not isinstance(cat, str):
        return "Unknown"
    mapped = CATEGORY_NORMALIZATION.get(cat.strip(), cat.strip())
    return _CANONICAL_BY_LOWER.get(mapped.lower(), mapped)


# Tool schema forces structured output — model must call this tool with
# a valid violations array (empty list when clean).
RECORD_VIOLATIONS_TOOL = {
    "name": "record_violations",
    "description": (
        "Record any phrase-family or structural anti-pattern violations found "
        "in the narrator's prose. Call with an empty violations list when the "
        "prose is clean. You MUST call this tool exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "violations": {
                "type": "array",
                "description": "List of violations found; empty list if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {
                            "type": "string",
                            "description": (
                                "The exact phrase or short passage from the "
                                "narrator's prose that violates the pattern."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "enum": VIOLATION_CATEGORIES,
                            "description": "Which Situation Strategy was violated.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": (
                                "high = unambiguous pattern hit. "
                                "medium = suggestive but defensible. "
                                "low = faint echo / drift only."
                            ),
                        },
                    },
                    "required": ["quote", "category", "confidence"],
                },
            }
        },
        "required": ["violations"],
    },
}


# --- Helpers ----------------------------------------------------------------

def _log_error(message: str) -> None:
    """Append an error entry to the observer error log. Never raises."""
    try:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{timestamp}  {message}\n")
    except Exception:
        pass


def _get_api_key():
    """Resolve API key from env var, then fallback file. None if unavailable."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        if API_KEY_FILE.exists():
            return API_KEY_FILE.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    return None


def _load_judge_prompt() -> str:
    """Load the static system prompt. Returns empty string on failure."""
    try:
        content = JUDGE_PROMPT_FILE.read_text(encoding="utf-8")
        if not content.strip():
            _log_error("judge_prompt.txt loaded but is empty/whitespace-only")
        return content
    except Exception as e:
        _log_error(f"Failed to load judge_prompt.txt: {e}")
        return ""


def _load_style_exemplars() -> str:
    """Load style exemplars. Returns empty string on failure (observer still runs)."""
    try:
        return STYLE_EXEMPLARS_FILE.read_text(encoding="utf-8")
    except Exception as e:
        _log_error(f"Failed to load style-exemplars.md (observer running without exemplar anchor): {e}")
        return ""


def _clean_orphan_temp_files() -> None:
    """Remove temp files older than ORPHAN_AGE_SECONDS. Best-effort."""
    try:
        tmp_dir = Path(temp_dir())
        now = time.time()
        for path in tmp_dir.glob(f"{TEMP_FILE_PREFIX}*.json"):
            try:
                if now - path.stat().st_mtime > ORPHAN_AGE_SECONDS:
                    path.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _call_judge_raw(api_key: str, system_prompt: str, user_text: str):
    """Call the judge model with forced tool-use. Returns raw response object."""
    import anthropic  # imported here so missing package doesn't break module load
    client = anthropic.Anthropic(api_key=api_key, timeout=API_TIMEOUT_SECONDS)
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_text}],
        tools=[RECORD_VIOLATIONS_TOOL],
        tool_choice={"type": "tool", "name": "record_violations"},
    )


def _call_judge(api_key: str, system_prompt: str, user_text: str) -> dict:
    """Call the judge and return the parsed verdict dict.

    With tool_choice forced to record_violations, the response is guaranteed
    to contain a tool_use block whose input matches the schema. We extract
    that input directly — no json.loads, no markdown-fence stripping, no
    empty-text failure mode.

    Raises on unexpected response shapes so the caller can log and swallow.
    """
    response = _call_judge_raw(api_key, system_prompt, user_text)
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "record_violations":
            payload = getattr(block, "input", None)
            if isinstance(payload, dict):
                return payload
            # SDK sometimes surfaces this as a pydantic model — coerce.
            try:
                return dict(payload)
            except Exception:
                pass
    raise ValueError("response contained no record_violations tool_use block")


# --- Main entry point -------------------------------------------------------

def run(input_file_path: str) -> int:
    """Run the observer against the input file. Always returns 0 (fail-open).

    Args:
        input_file_path: Path to the temp JSON file the parent hook wrote.
                         Must contain {session_id, turn_id, response_text}.

    Returns:
        0 in all cases. Errors are logged and swallowed.
    """
    input_path = Path(input_file_path)

    # Best-effort orphan cleanup at startup
    _clean_orphan_temp_files()

    # Read input
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        session_id = payload["session_id"]
        turn_id = int(payload["turn_id"])
        response_text = payload["response_text"]
        scene_type = payload.get("scene_type", "unknown")
    except Exception as e:
        _log_error(f"Failed to read input file {input_file_path}: {e}")
        try:
            input_path.unlink()
        except Exception:
            pass
        return 0

    # Resolve API key
    api_key = _get_api_key()
    if not api_key:
        _log_error("No API key in env or fallback file — skipping observer call")
        try:
            input_path.unlink()
        except Exception:
            pass
        return 0

    # Build prompt
    judge_prompt = _load_judge_prompt()
    if not judge_prompt:
        try:
            input_path.unlink()
        except Exception:
            pass
        return 0

    exemplars = _load_style_exemplars()
    system_prompt = judge_prompt
    if exemplars:
        system_prompt += "\n\n---\n\nSTYLE EXEMPLARS REFERENCE:\n\n" + exemplars

    # Call judge and parse verdict
    try:
        verdict = _call_judge(api_key, system_prompt, response_text)
    except Exception as e:
        _log_error(f"Judge call failed session={session_id} turn={turn_id}: {type(e).__name__}: {e}")
        try:
            input_path.unlink()
        except Exception:
            pass
        return 0

    # Write violations to analytics
    if not isinstance(verdict, dict):
        _log_error(f"Unexpected verdict type {type(verdict).__name__} session={session_id} turn={turn_id}")
    violations = verdict.get("violations", []) if isinstance(verdict, dict) else []
    for v in violations:
        try:
            analytics_utils.log_semantic_catch(
                quote=v.get("quote", ""),
                category=_normalize_category(v.get("category", "Unknown")),
                confidence=v.get("confidence", "low"),
                session_id=session_id,
                turn_id=turn_id,
                scene_type=scene_type,
            )
        except Exception as e:
            _log_error(f"Failed to log semantic catch: {e}")

    # Clean up temp file
    try:
        input_path.unlink()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _log_error("prose_observer invoked without input file path argument")
        sys.exit(0)
    sys.exit(run(sys.argv[1]))
