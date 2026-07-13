def test_server_source_registers_social_tools():
    src = open("server.py", encoding="utf-8").read()
    assert "register_social_tools" in src
    assert "from social_system import register_social_tools" in src
