import social_system as ss
from tests.test_social_parley_parser import SAMPLE


def test_blocks_for_npc_in_open_parley(tmp_path):
    parsed = ss.parse_parley_block(SAMPLE)
    ss.open_parley(tmp_path, parsed["slug"], title="Outer Reach Accord", day=131, parsed=parsed)
    blocks = ss.parley_blocks_for_npc(tmp_path, "She-Who-Keeps")
    assert len(blocks) == 1
    b = blocks[0]
    assert "🤝" in b and "wary" in b and "gated reveals: 2" in b and "parley(" in b


def test_blocks_empty_when_no_parley(tmp_path):
    assert ss.parley_blocks_for_npc(tmp_path, "She-Who-Keeps") == []


def test_blocks_empty_when_closed(tmp_path):
    parsed = ss.parse_parley_block(SAMPLE)
    ss.open_parley(tmp_path, parsed["slug"], title="OR", day=131, parsed=parsed)
    data = ss.load_parleys(tmp_path); data[parsed["slug"]]["status"] = "closed"
    ss.save_parleys(tmp_path, data)
    assert ss.parley_blocks_for_npc(tmp_path, "She-Who-Keeps") == []


def test_server_calls_parley_blocks():
    src = open("server.py", encoding="utf-8").read()
    assert "parley_blocks_for_npc" in src
