"""push_format: the ONE way tool output names the next tool call.
Apostrophe-safe by construction (the recurring single-quote push bug
becomes impossible at the formatter level)."""
import push_format as pf


def test_push_call_double_quotes_all_values():
    s = pf.push_call("usage", action="reload", character="Vela", weapon="Railgun")
    assert s == 'usage(action="reload", character="Vela", weapon="Railgun")'


def test_push_call_apostrophe_safe():
    s = pf.push_call("wound", action="heal", character="Kess", wound="Death's Door")
    assert 'wound="Death\'s Door"' in s
    assert "'Death" not in s.replace('"Death\'s Door"', "")  # no single-quoted value delimiters


def test_push_call_raw_token_passthrough():
    s = pf.push_call("wound", action="ko_save", character="Petros",
                     result=pf.raw('"pass"|"fail"'))
    assert s == 'wound(action="ko_save", character="Petros", result="pass"|"fail")'


def test_next_block_single():
    s = pf.next_block('usage(action="reload", character="Vela", weapon="Railgun")')
    assert s == 'NEXT: usage(action="reload", character="Vela", weapon="Railgun")'


def test_next_block_multiple_options():
    s = pf.next_block(
        'usage(action="reload", character="Vela", weapon="Railgun")',
        'usage(action="feed", character="Vela", weapon="Railgun")',
        label="reload or feed",
    )
    assert s == ('NEXT (reload or feed): '
                 'usage(action="reload", character="Vela", weapon="Railgun")'
                 ' | usage(action="feed", character="Vela", weapon="Railgun")')


def test_next_block_empty_returns_empty():
    assert pf.next_block() == ""
