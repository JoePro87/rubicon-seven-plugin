#!/usr/bin/env python3
"""
Save verification agent.
Compares proposed save fields against gameplay transcript.
Corrects any claims that can't be verified.

Usage:
    python verify_save_agent.py --transcript <path> --fields <json>

Output (JSON):
    {
        "corrections_made": bool,
        "corrected_fields": {...},
        "change_log": "description of changes"
    }
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# Fields that contain narrative content needing verification
NARRATIVE_FIELDS = [
    "session_summary",
    "narrative_log",
    "last_beat",
    "tension_mood",
    "next_expected",
    "arc_summary",
    "arc_tension",
]

# Fields that are structural/factual - verify but handle differently
FACTUAL_FIELDS = [
    "day",
    "scene_location",
    "characters_present",
    "last_speaker",
    "current_arc",
]

# Minimum token overlap ratio to consider a claim verified
VERIFICATION_THRESHOLD = 0.80


def main():
    parser = argparse.ArgumentParser(description="Verify save content against transcript")
    parser.add_argument("--transcript", required=True, help="Path to transcript JSON")
    parser.add_argument("--fields", required=True, help="Proposed save fields as JSON")
    args = parser.parse_args()

    # Load transcript
    try:
        transcript_path = Path(args.transcript)
        if not transcript_path.exists():
            output_error(f"Transcript not found: {transcript_path}")
            return

        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)
    except Exception as e:
        output_error(f"Failed to load transcript: {e}")
        return

    # Parse proposed fields
    try:
        proposed_fields = json.loads(args.fields)
    except json.JSONDecodeError as e:
        output_error(f"Invalid fields JSON: {e}")
        return

    # Build searchable corpus from transcript
    corpus = build_corpus(transcript)

    if not corpus:
        output_error("Could not extract content from transcript")
        return

    # Verify and correct each field
    corrected_fields = {}
    changes = []

    for field_name, field_value in proposed_fields.items():
        if field_value is None:
            corrected_fields[field_name] = None
            continue

        if field_name in NARRATIVE_FIELDS:
            corrected, field_changes = verify_narrative_field(
                field_name, field_value, corpus
            )
            corrected_fields[field_name] = corrected
            changes.extend(field_changes)

        elif field_name == "emotional_states" and isinstance(field_value, dict):
            corrected, field_changes = verify_emotional_states(field_value, corpus)
            corrected_fields[field_name] = corrected
            changes.extend(field_changes)

        elif field_name in FACTUAL_FIELDS:
            # Factual fields - verify but don't genericize, just flag
            corrected, field_changes = verify_factual_field(
                field_name, field_value, corpus
            )
            corrected_fields[field_name] = corrected
            changes.extend(field_changes)

        else:
            # Pass through unchanged (npc_changes, inventory_changes, new_canon, etc.)
            corrected_fields[field_name] = field_value

    # Output result
    corrections_made = len(changes) > 0
    change_log = "\n".join(changes) if changes else "No corrections needed"

    result = {
        "corrections_made": corrections_made,
        "corrected_fields": corrected_fields,
        "change_log": change_log,
    }

    print(json.dumps(result))


def output_error(message: str):
    """Output an error result."""
    print(json.dumps({"error": message}))


def build_corpus(transcript: Any) -> str:
    """
    Extract all text content from transcript into a searchable corpus.

    Handles Claude Code transcript format:
    - List of message objects with 'role' and 'content'
    - Content can be string or list of content blocks
    """
    texts = []

    # Handle different transcript formats
    messages = []
    if isinstance(transcript, list):
        messages = transcript
    elif isinstance(transcript, dict):
        messages = transcript.get("messages", transcript.get("conversation", []))

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # Extract content
        content = msg.get("content", "")

        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            # Content blocks format
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        # Include tool outputs
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str):
                            texts.append(tool_content)
                        elif isinstance(tool_content, list):
                            for tc in tool_content:
                                if isinstance(tc, dict) and tc.get("type") == "text":
                                    texts.append(tc.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)

    return "\n".join(texts)


# Common irregular verbs mapped to base form
IRREGULAR_VERBS = {
    "ate": "eat", "eaten": "eat", "eating": "eat",
    "was": "be", "were": "be", "been": "be", "being": "be",
    "sat": "sit", "sitting": "sit",
    "had": "have", "having": "have",
    "went": "go", "going": "go", "gone": "go",
    "said": "say", "saying": "say",
    "made": "make", "making": "make",
    "took": "take", "taking": "take", "taken": "take",
    "came": "come", "coming": "come",
    "saw": "see", "seeing": "see", "seen": "see",
    "knew": "know", "knowing": "know", "known": "know",
    "got": "get", "getting": "get", "gotten": "get",
    "gave": "give", "giving": "give", "given": "give",
    "found": "find", "finding": "find",
    "thought": "think", "thinking": "think",
    "told": "tell", "telling": "tell",
    "felt": "feel", "feeling": "feel",
    "left": "leave", "leaving": "leave",
    "held": "hold", "holding": "hold",
    "stood": "stand", "standing": "stand",
    "heard": "hear", "hearing": "hear",
    "watched": "watch", "watching": "watch",
}


def normalize_word(word: str) -> str:
    """Basic word normalization - strip common suffixes for matching."""
    word = word.lower()

    # Check irregular verbs first
    if word in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[word]

    # Strip common verb endings
    if word.endswith("ing") and len(word) > 4:
        return word[:-3]  # eating -> eat
    if word.endswith("ed") and len(word) > 3:
        return word[:-2]  # watched -> watch
    if word.endswith("s") and len(word) > 2 and not word.endswith("ss"):
        return word[:-1]  # checks -> check
    return word


def tokenize(text: str) -> set:
    """Convert text to a set of normalized lowercase word tokens."""
    # Remove punctuation, lowercase, split on whitespace
    words = re.findall(r"\b[a-zA-Z]+(?:'[a-zA-Z]+)?\b", text.lower())
    return set(normalize_word(w) for w in words)


def token_overlap_ratio(claim_tokens: set, corpus_tokens: set) -> float:
    """Calculate what fraction of claim tokens appear in corpus."""
    if not claim_tokens:
        return 1.0  # Empty claim is trivially verified

    overlap = claim_tokens & corpus_tokens
    return len(overlap) / len(claim_tokens)


def extract_specific_claims(text: str) -> list[tuple[str, str]]:
    """
    Extract specific claims from narrative text.

    Returns list of (claim_text, claim_type) tuples.
    claim_type: 'object', 'description', 'action', 'quantity'
    """
    claims = []

    # Extract quoted speech
    quotes = re.findall(r'"([^"]+)"', text)
    for q in quotes:
        if len(q.split()) > 2:  # Skip very short quotes
            claims.append((q, "speech"))

    # Extract specific objects (noun phrases with adjectives)
    # Pattern: adjective(s) + noun, e.g., "rice porridge", "grey pallor"
    object_patterns = [
        r"\b([a-z]+-[a-z]+)\s+([a-z]+)\b",  # compound-adjective noun
        r"\b([a-z]+)\s+(porridge|honey|rice|bread|meat|water|wine)\b",  # food items
        r"\b([a-z]+)\s+(pallor|complexion|skin|eyes|hair)\b",  # physical descriptions
    ]

    for pattern in object_patterns:
        matches = re.findall(pattern, text.lower())
        for match in matches:
            claim = " ".join(match) if isinstance(match, tuple) else match
            claims.append((claim, "object"))

    # Extract location references with "from the X"
    from_locations = re.findall(r"from the ([A-Z][a-zA-Z\s]+)", text)
    for loc in from_locations:
        claims.append((loc.strip(), "location_source"))

    return claims


def verify_claim_in_corpus(claim: str, corpus: str, corpus_tokens: set) -> bool:
    """Check if a claim can be verified in the corpus."""
    # First try exact substring match (case-insensitive)
    if claim.lower() in corpus.lower():
        return True

    # Fall back to token overlap
    claim_tokens = tokenize(claim)
    ratio = token_overlap_ratio(claim_tokens, corpus_tokens)
    return ratio >= VERIFICATION_THRESHOLD


# Stop words to ignore when matching sentences
STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "by",
    "from", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "can", "this", "that", "these",
    "those", "it", "its", "he", "she", "they", "him", "her", "them",
    "his", "their", "my", "your", "our", "who", "what", "which", "when",
    "where", "how", "why", "very", "just", "also", "now", "then", "so",
}


def get_content_words(text: str) -> set:
    """Get normalized content words (excluding stop words)."""
    tokens = tokenize(text)
    return {t for t in tokens if t not in STOP_WORDS and len(t) > 2}


def find_closest_transcript_sentence(sentence: str, corpus: str) -> str | None:
    """
    Find the closest matching sentence in the transcript.
    Returns None if no reasonable match found.
    """
    # Split corpus into sentences (handle newlines as boundaries too)
    corpus_sentences = re.split(r"(?<=[.!?])\s+|\n+", corpus)
    corpus_sentences = [s.strip() for s in corpus_sentences if s.strip()]

    # Use content words (not stop words) for matching
    sentence_content = get_content_words(sentence)
    if not sentence_content:
        return None

    best_match = None
    best_score = 0.0

    for corpus_sent in corpus_sentences:
        corpus_content = get_content_words(corpus_sent)
        if not corpus_content:
            continue

        # Calculate overlap of content words
        overlap = sentence_content & corpus_content

        if not overlap:
            continue

        # Score by: how many content words overlap / size of smaller set
        # This way we favor sentences about the same subject
        smaller_size = min(len(sentence_content), len(corpus_content))
        score = len(overlap) / smaller_size

        if score > best_score:
            best_score = score
            best_match = corpus_sent

    # Require at least 30% content word overlap
    if best_score >= 0.3:
        return best_match

    return None


def genericize_sentence(sentence: str, unverified_claims: list, corpus: str) -> str:
    """
    Replace a sentence containing unverified claims with the closest transcript match,
    or a stripped-down version if no match found.
    """
    # First, try to find a matching sentence in the transcript
    match = find_closest_transcript_sentence(sentence, corpus)

    if match:
        return match

    # No good match - strip specific details aggressively
    result = sentence

    # Remove food specifics
    result = re.sub(
        r"\b(rice|porridge|honey|bread|meat|stew|soup)\b",
        "",
        result,
        flags=re.IGNORECASE,
    )

    # Remove "with X" phrases
    result = re.sub(r"\s+with\s+\w+", "", result, flags=re.IGNORECASE)

    # Remove "from the X" location sourcing
    result = re.sub(r"\s+from the [A-Z][a-zA-Z\s]+", "", result, flags=re.IGNORECASE)

    # Clean up double spaces and weird punctuation
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+\.", ".", result)
    result = re.sub(r"\s+,", ",", result)

    return result.strip()


def verify_narrative_field(
    field_name: str, field_value: str, corpus: str
) -> tuple[str, list[str]]:
    """
    Verify a narrative field against corpus.
    Returns (corrected_value, list_of_changes).
    """
    if not field_value:
        return field_value, []

    corpus_tokens = tokenize(corpus)
    changes = []

    # Split into sentences for granular verification
    sentences = re.split(r"(?<=[.!?])\s+", field_value)
    corrected_sentences = []

    for sentence in sentences:
        # Extract claims from this sentence
        claims = extract_specific_claims(sentence)

        # Find which claims are unverified
        unverified_claims = []
        for claim_text, claim_type in claims:
            if not verify_claim_in_corpus(claim_text, corpus, corpus_tokens):
                unverified_claims.append((claim_text, claim_type))

        if unverified_claims:
            # Sentence has unverified content - replace with transcript version or strip
            corrected_sentence = genericize_sentence(sentence, unverified_claims, corpus)

            if corrected_sentence != sentence:
                claim_list = ", ".join([f"'{c[0]}'" for c in unverified_claims])
                changes.append(
                    f"[{field_name}] Sentence corrected (unverified: {claim_list}): '{sentence}' -> '{corrected_sentence}'"
                )

            corrected_sentences.append(corrected_sentence)
        else:
            # Sentence is verified, keep as-is
            corrected_sentences.append(sentence)

    corrected_value = " ".join(corrected_sentences)

    # Clean up any double spaces or trailing issues
    corrected_value = re.sub(r"\s+", " ", corrected_value).strip()

    return corrected_value, changes


def verify_emotional_states(
    emotional_states: dict, corpus: str
) -> tuple[dict, list[str]]:
    """
    Verify emotional states against corpus.
    Emotional states should trace to actual dialogue or narrated reactions.
    """
    corpus_tokens = tokenize(corpus)
    corrected = {}
    changes = []

    for character, state in emotional_states.items():
        if not state:
            corrected[character] = state
            continue

        # Check if the emotional state description appears in corpus
        state_tokens = tokenize(state)
        ratio = token_overlap_ratio(state_tokens, corpus_tokens)

        if ratio >= VERIFICATION_THRESHOLD:
            corrected[character] = state
        else:
            # Check if at least the emotion word appears
            emotion_words = ["anxious", "hopeful", "worried", "happy", "sad", "angry",
                          "fearful", "curious", "protective", "guarded", "relieved",
                          "tense", "calm", "focused", "distracted", "exhausted"]

            state_lower = state.lower()
            found_emotion = None
            for emotion in emotion_words:
                if emotion in state_lower and emotion in corpus.lower():
                    found_emotion = emotion
                    break

            if found_emotion:
                # Keep just the verified emotion, drop the unverified context
                corrected[character] = found_emotion
                changes.append(
                    f"[emotional_states.{character}] Reduced to verified emotion: '{found_emotion}' (was: '{state}')"
                )
            else:
                # Can't verify any part - remove this emotional state
                changes.append(
                    f"[emotional_states.{character}] Removed unverified state: '{state}'"
                )

    return corrected, changes


def verify_factual_field(
    field_name: str, field_value: Any, corpus: str
) -> tuple[Any, list[str]]:
    """
    Verify factual fields (day, location, characters, etc.)
    These should appear somewhere in the transcript.
    """
    changes = []

    if field_name == "day" and isinstance(field_value, int):
        # Check if this day number appears in transcript
        day_patterns = [f"Day {field_value}", f"day {field_value}"]
        found = any(p in corpus for p in day_patterns)
        if not found:
            changes.append(
                f"[{field_name}] Warning: Day {field_value} not found in transcript"
            )
        # Still return the value - day is critical

    elif isinstance(field_value, str):
        # Check if the value appears in corpus
        if field_value.lower() not in corpus.lower():
            # Try tokenized match
            value_tokens = tokenize(field_value)
            corpus_tokens = tokenize(corpus)
            ratio = token_overlap_ratio(value_tokens, corpus_tokens)

            if ratio < VERIFICATION_THRESHOLD:
                changes.append(
                    f"[{field_name}] Warning: '{field_value}' not well-verified in transcript ({ratio:.0%} token overlap)"
                )
        # Still return - these are important structural fields

    return field_value, changes


if __name__ == "__main__":
    main()
