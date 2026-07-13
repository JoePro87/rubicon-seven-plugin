"""Pure dice-chain primitive shared by the Toxin Die (and, later, the Usage Die).

The chain runs cured < d4 < d6 < d8 < d10 < d12 < d20. A die STEPS DOWN one rung
when it rolls a 1-2 (depletion); it ESCALATES up only to a strictly larger rung.
No game state lives here — callers own the current rung.
"""
import random

CHAIN = ["cured", "d4", "d6", "d8", "d10", "d12", "d20"]


def _norm(die):
    """Map None/unknown to 'cured'; pass through valid rungs."""
    return die if die in CHAIN else "cured"


def size(die) -> int:
    """Face count of a rung ('d8' -> 8). 'cured'/None -> 0."""
    die = _norm(die)
    return 0 if die == "cured" else int(die[1:])


def step_down(die) -> str:
    """Next-lower rung; 'd4' -> 'cured'; 'cured' stays 'cured'."""
    return CHAIN[max(0, CHAIN.index(_norm(die)) - 1)]


def escalate(current, new) -> str:
    """The larger of the two rungs (book: a new toxin only raises if bigger)."""
    return CHAIN[max(CHAIN.index(_norm(current)), CHAIN.index(_norm(new)))]


def roll(die, rng=random.randint) -> int:
    """Roll the rung's die (1..faces). 'cured'/None -> 0. rng injectable for tests."""
    n = size(die)
    return 0 if n == 0 else rng(1, n)
