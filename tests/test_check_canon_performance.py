"""Stress test check_canon for token efficiency.

Run from project root:
    python -m tests.test_check_canon_performance
"""
import sys
import time
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock Context for testing
@dataclass
class MockContext:
    """Mock MCP Context for testing check_canon."""
    pass

# Import after path setup
import server


TEST_INPUTS = {
    "simple_action": "I walk forward",
    "combat": "I attack the ghoul with my blade",
    "dialogue": "What does Vela say?",
    "exploration": "I search the room for secrets",
    "lore_question": "Tell me about the Titans",
    "intimate": "I kiss her gently",
    "npc_mention": "Kess checks the door",
    "location_mention": "We head to Ceruline",
}


def count_sections(output: str) -> dict:
    """Count which sections appear in output."""
    sections = {
        "lorebook_matches": "**CONTEXT" in output or "[PEOP]" in output or "[PLAC]" in output,
        "location": "LOCATION" in output,
        "characters_present": "CHARACTERS PRESENT" in output or "CHARACTER:" in output,
        "emotional_states": "EMOTIONAL" in output,
        "relationships": "RELATIONSHIP" in output,
        "active_threads": "ACTIVE THREADS" in output or "THREAD" in output,
        "tool_recommendations": "REQUIRED TOOLS" in output or "⚠️" in output,
        "dm_secrets": "SECRETS" in output,
        "prep_overview": "PREP" in output,
    }
    return {k: v for k, v in sections.items() if v}


def measure_output(input_type: str, user_input: str, light: bool = False) -> dict:
    """Measure check_canon output for a given input."""
    ctx = MockContext()

    # light=True maps to needs=[] (auto-detect, minimal context)
    # light=False maps to needs=[] (auto-detect, same default behavior)
    start = time.time()
    result = server.check_canon(
        ctx=ctx,
        user_input=user_input,
        needs=[]
    )
    elapsed = time.time() - start

    return {
        "type": input_type,
        "input": user_input,
        "light_mode": light,
        "output_chars": len(result),
        "output_tokens": len(result) // 4,  # rough estimate (4 chars per token)
        "time_ms": int(elapsed * 1000),
        "sections": count_sections(result),
    }


def run_baseline_tests():
    """Run baseline tests and print results."""
    print("=" * 60)
    print("CHECK_CANON STRESS TEST - BASELINE MEASUREMENTS")
    print("=" * 60)
    print()

    results = []

    # Test full context mode
    print("FULL CONTEXT MODE:")
    print("-" * 40)
    for input_type, user_input in TEST_INPUTS.items():
        result = measure_output(input_type, user_input, light=False)
        results.append(result)
        print(f"{input_type:20s} | {result['output_tokens']:5d} tokens | {result['time_ms']:4d}ms | sections: {list(result['sections'].keys())}")

    print()

    # Test light mode
    print("LIGHT MODE:")
    print("-" * 40)
    for input_type, user_input in TEST_INPUTS.items():
        result = measure_output(input_type, user_input, light=True)
        results.append(result)
        print(f"{input_type:20s} | {result['output_tokens']:5d} tokens | {result['time_ms']:4d}ms | sections: {list(result['sections'].keys())}")

    print()

    # Summary statistics
    full_results = [r for r in results if not r['light_mode']]
    light_results = [r for r in results if r['light_mode']]

    avg_full = sum(r['output_tokens'] for r in full_results) / len(full_results)
    avg_light = sum(r['output_tokens'] for r in light_results) / len(light_results)

    print("=" * 60)
    print("SUMMARY:")
    print(f"  Average tokens (full mode):  {avg_full:.0f}")
    print(f"  Average tokens (light mode): {avg_light:.0f}")
    print(f"  Token savings with light:    {avg_full - avg_light:.0f} ({((avg_full - avg_light) / avg_full * 100):.1f}%)")
    print("=" * 60)

    return results


def run_section_analysis():
    """Analyze which sections contribute most tokens."""
    print()
    print("=" * 60)
    print("SECTION-BY-SECTION ANALYSIS")
    print("=" * 60)
    print()

    # Run a representative input
    ctx = MockContext()
    result = server.check_canon(
        ctx=ctx,
        user_input="Vela says something to Kess about the journey to Ceruline",
        needs=[]
    )

    # Split by section markers
    lines = result.split('\n')
    current_section = "HEADER"
    section_chars = {}

    for line in lines:
        if line.startswith('**') and line.endswith(':**'):
            current_section = line.strip('*:').strip()
        if current_section not in section_chars:
            section_chars[current_section] = 0
        section_chars[current_section] += len(line) + 1

    # Sort by size
    sorted_sections = sorted(section_chars.items(), key=lambda x: x[1], reverse=True)

    total_chars = sum(section_chars.values())
    print(f"Total output: {total_chars} chars (~{total_chars // 4} tokens)")
    print()
    print("Section breakdown:")
    for section, chars in sorted_sections:
        tokens = chars // 4
        pct = (chars / total_chars) * 100
        print(f"  {section:30s} | {tokens:5d} tokens | {pct:5.1f}%")

    return section_chars


if __name__ == "__main__":
    # Fix Windows console encoding
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    print("Starting check_canon performance tests...")
    print()

    try:
        baseline_results = run_baseline_tests()
        section_analysis = run_section_analysis()

        # Save results to JSON for later comparison
        output_path = Path(__file__).parent / "check_canon_baseline.json"
        with open(output_path, 'w') as f:
            json.dump({
                "baseline": baseline_results,
                "sections": section_analysis,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }, f, indent=2, default=str)
        print(f"\nResults saved to: {output_path}")

    except Exception as e:
        print(f"Error running tests: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
