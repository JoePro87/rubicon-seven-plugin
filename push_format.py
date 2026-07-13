"""The one formatter for in-band tool-call pushes ("NEXT: ..." lines).

Reflex Layer Component 2 (spec docs/superpowers/specs/2026-06-10-reflex-layer-design.md).
Values are ALWAYS double-quoted, so names carrying apostrophes (Death's Door,
Kronophage's Echo) can never break the rendered call — the recurring
single-quote push bug is impossible by construction.
"""


class raw(str):
    """A value rendered verbatim, no quoting (e.g. raw('"pass"|"fail"'))."""


def push_call(tool: str, **kwargs) -> str:
    parts = []
    for k, v in kwargs.items():
        parts.append(f"{k}={v}" if isinstance(v, raw) else f'{k}="{v}"')
    return f"{tool}({', '.join(parts)})"


def next_block(*calls: str, label: str = "") -> str:
    calls = [c for c in calls if c]
    if not calls:
        return ""
    head = f"NEXT ({label}): " if label else "NEXT: "
    return head + " | ".join(calls)
