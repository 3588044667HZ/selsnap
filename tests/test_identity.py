import json

import pytest

from selsnap.identity import build_token_map


def test_build_token_map_from_json():
    mapping = build_token_map(
        None, json.dumps({"tok-1": "agent-a", "tok-2": "agent-b"}), "local"
    )
    assert mapping == {"tok-1": "agent-a", "tok-2": "agent-b"}


def test_build_token_map_single_token_uses_default_agent():
    assert build_token_map("secret-token", None, "local") == {
        "secret-token": "local"
    }


def test_build_token_map_merges_sources():
    mapping = build_token_map("tok-1", json.dumps({"tok-2": "agent-b"}), "local")
    assert mapping == {"tok-1": "local", "tok-2": "agent-b"}


def test_build_token_map_rejects_bad_agent_name():
    with pytest.raises(ValueError):
        build_token_map(None, json.dumps({"tok": "bad agent"}), "local")
    with pytest.raises(ValueError):
        build_token_map("tok", None, "bad agent")


def test_build_token_map_rejects_bad_json():
    with pytest.raises(ValueError):
        build_token_map(None, "not-json", "local")
    with pytest.raises(ValueError):
        build_token_map(None, json.dumps(["a"]), "local")
    with pytest.raises(ValueError):
        build_token_map(None, json.dumps({"": "a"}), "local")
