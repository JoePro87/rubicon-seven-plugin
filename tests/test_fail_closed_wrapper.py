"""Tests for fail_closed_wrapper — the security-critical hook decorator.

Covers hooks/hook_utils.py:88. This decorator is the single point of
fail-closed security for the entire hook layer (classified gating,
check_canon / validate_prose enforcement). If a wrapped hook raises an
unexpected exception, the wrapper MUST block the tool (fail closed) rather
than let the call through. A regression that swallowed exceptions could
silently open gated tools and leak classified content, undetected.

Real interface (verified 2026-06-07 audit remediation):
    - block(msg) prints to stderr and calls sys.exit(EXIT_BLOCK) where
      EXIT_BLOCK == 2. So a wrapped function that raises Exception ends up
      raising SystemExit(2).
    - SystemExit raised inside the wrapped function (e.g. from block()/allow())
      is re-raised unchanged — its code is preserved.
    - The happy path returns the wrapped function's value untouched.
"""

import pytest

from hooks.hook_utils import fail_closed_wrapper, EXIT_BLOCK, EXIT_ALLOW


# (a) A wrapped function that raises -> wrapper fails closed (blocks).

def test_raising_function_fails_closed_with_block_exit_code():
    """An arbitrary exception must turn into a BLOCK exit, not pass through."""

    @fail_closed_wrapper
    def boom():
        raise RuntimeError("something went wrong inside the hook")

    with pytest.raises(SystemExit) as exc_info:
        boom()

    # block() exits with EXIT_BLOCK (2). It must NOT be a clean/allow exit.
    assert exc_info.value.code == EXIT_BLOCK
    assert EXIT_BLOCK == 2


def test_raising_function_does_not_return_a_value():
    """Fail-closed means the original (no-op/None) return is never produced;
    the call terminates via SystemExit instead of falling through."""

    sentinel_ran = []

    @fail_closed_wrapper
    def boom():
        raise ValueError("bad")
        sentinel_ran.append(True)  # unreachable

    with pytest.raises(SystemExit):
        boom()

    assert sentinel_ran == []  # body after raise never executed


def test_block_message_written_to_stderr(capsys):
    """The fail-closed path emits a HOOK ERROR message to stderr so the
    failure is observable (and the tool is blocked, not silently allowed)."""

    @fail_closed_wrapper
    def boom():
        raise KeyError("missing_key")

    with pytest.raises(SystemExit):
        boom()

    captured = capsys.readouterr()
    assert "HOOK ERROR" in captured.err
    assert "fail-closed" in captured.err
    # Includes the exception type name for diagnosis.
    assert "KeyError" in captured.err
    # Must not print to stdout (which a hook could misread as an allow message).
    assert captured.out == ""


def test_various_exception_types_all_fail_closed():
    """Any non-SystemExit exception type must fail closed identically."""

    for exc in (RuntimeError, ValueError, KeyError, TypeError, OSError):

        @fail_closed_wrapper
        def boom(_exc=exc):
            raise _exc("boom")

        with pytest.raises(SystemExit) as exc_info:
            boom()
        assert exc_info.value.code == EXIT_BLOCK


# (b) SystemExit propagates unchanged.

def test_systemexit_block_propagates_unchanged():
    """A SystemExit raised inside the wrapped function (as block() does)
    must propagate with its original code, NOT be re-wrapped."""

    @fail_closed_wrapper
    def explicit_block():
        raise SystemExit(EXIT_BLOCK)

    with pytest.raises(SystemExit) as exc_info:
        explicit_block()
    assert exc_info.value.code == EXIT_BLOCK


def test_systemexit_allow_propagates_unchanged():
    """A clean SystemExit (as allow() does, code 0) must pass through
    unchanged — the wrapper must not convert an intentional allow into a
    block or vice versa."""

    @fail_closed_wrapper
    def explicit_allow():
        raise SystemExit(EXIT_ALLOW)

    with pytest.raises(SystemExit) as exc_info:
        explicit_allow()
    assert exc_info.value.code == EXIT_ALLOW
    assert EXIT_ALLOW == 0


def test_systemexit_with_arbitrary_code_propagates_unchanged():
    """Any SystemExit code is preserved verbatim, confirming the wrapper
    re-raises rather than reconstructing it."""

    @fail_closed_wrapper
    def odd_exit():
        raise SystemExit(7)

    with pytest.raises(SystemExit) as exc_info:
        odd_exit()
    assert exc_info.value.code == 7


# (c) Happy path passes through untouched.

def test_happy_path_returns_value():
    """A normal function's return value is passed through unchanged."""

    @fail_closed_wrapper
    def ok():
        return "result"

    assert ok() == "result"


def test_happy_path_forwards_args_and_kwargs():
    """Positional and keyword arguments are forwarded untouched."""

    @fail_closed_wrapper
    def add(a, b, *, c=0):
        return a + b + c

    assert add(1, 2, c=3) == 6


def test_happy_path_preserves_function_metadata():
    """functools.wraps preserves the wrapped function's name/docstring."""

    @fail_closed_wrapper
    def documented():
        """A documented hook function."""
        return None

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "A documented hook function."


def test_happy_path_falsy_return_passes_through():
    """A legitimate falsy return (None/0/'') is not mistaken for failure."""

    @fail_closed_wrapper
    def returns_none():
        return None

    @fail_closed_wrapper
    def returns_zero():
        return 0

    assert returns_none() is None
    assert returns_zero() == 0
