import time

import pytest

from selsnap.config import Settings
from selsnap.errors import ToolError
from selsnap.sessions import SessionActor


def make_actor(owner="agent-a"):
    settings = Settings(idle_timeout=0)
    return SessionActor("s1", "standard", True, settings, owner=owner)


def test_owner_has_full_access():
    actor = make_actor()
    assert actor.can_read("agent-a")
    assert actor.can_write("agent-a")


def test_share_read_and_write():
    actor = make_actor()
    actor.share("agent-b", "read")
    assert actor.can_read("agent-b")
    assert not actor.can_write("agent-b")
    actor.share("agent-b", "write")
    assert actor.can_read("agent-b")
    assert actor.can_write("agent-b")


def test_share_revoke():
    actor = make_actor()
    actor.share("agent-b", "read")
    result = actor.share("agent-b", "revoke")
    assert result["revoked"] is True
    assert not actor.can_read("agent-b")


def test_share_ttl_expires():
    actor = make_actor()
    actor.share("agent-b", "read", ttl=60)
    assert actor.can_read("agent-b")
    actor._grants["agent-b"]["expires_at"] = time.time() - 1
    assert not actor.can_read("agent-b")
    assert actor.grants() == []


def test_share_validation():
    actor = make_actor()
    with pytest.raises(ToolError):
        actor.share("bad agent", "read")
    with pytest.raises(ToolError):
        actor.share("agent-b", "admin")
    with pytest.raises(ToolError):
        actor.share("agent-b", "read", ttl=0)
    with pytest.raises(ToolError):
        actor.share("agent-b", "read", ttl=10**9)
    with pytest.raises(ToolError):
        actor.share("agent-a", "read")


def test_require_access_raises_forbidden():
    actor = make_actor()
    with pytest.raises(ToolError) as info:
        actor.require_access("agent-b", "write")
    assert info.value.code == "forbidden"
    assert info.value.details["owner"] == "agent-a"


def test_info_hides_grants_from_non_owner():
    actor = make_actor()
    actor.share("agent-b", "read")
    assert actor.info("agent-b").get("shared_with") is None
    assert actor.info("agent-a")["shared_with"][0]["agent"] == "agent-b"


def test_next_mode_order():
    actor = make_actor()
    actor.mode = "standard"
    assert actor.next_mode() == "uc"
    actor.mode = "uc"
    assert actor.next_mode() == "cdp"
    actor.mode = "cdp"
    assert actor.next_mode() is None
