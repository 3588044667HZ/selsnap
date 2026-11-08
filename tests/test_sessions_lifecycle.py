from selsnap.config import Settings
from selsnap.errors import ToolError
from selsnap.sessions import SessionActor


class FakeBackend:
    def __init__(self):
        self.opened = 0
        self.quit_count = 0
        self.url = ""
        self.mode = "standard"
        self.browser_path = ""
        self.headless = True
        self.page_load_timeout = 30.0
        self.profile_dir = ""

    def open(self):
        self.opened += 1
        return "fake-1"

    def quit(self):
        self.quit_count += 1

    def navigate(self, url):
        self.url = url

    @property
    def current_url(self):
        return self.url or "about:blank"

    def snapshot(self, max_nodes, max_chars, ref_base=0):
        return {
            "doc_id": "d1",
            "url": self.url or "about:blank",
            "title": "Fake",
            "snapshot": '- button "Go" [e1]',
            "stats": {"ref_counter": ref_base + 1},
            "tree": None,
        }


def make_actor():
    settings = Settings(idle_timeout=0)
    actor = SessionActor("s", "standard", True, settings, owner="a")
    actor.backend = FakeBackend()
    actor.start()
    return actor


def test_call_updates_last_used_and_ref_counter():
    actor = make_actor()
    before = actor.last_used
    result = actor.call(lambda: actor.backend.snapshot(10, 1000, actor.next_ref_base))
    actor.record_snapshot(result)
    assert actor.ref_counter == 1
    assert actor.last_used >= before
    actor.close()


def test_suspend_and_resume():
    actor = make_actor()
    assert actor.suspend() is True
    assert actor.suspended is True
    assert actor.backend.quit_count == 1
    assert actor.resume() is True
    assert actor.suspended is False
    assert actor.backend.opened == 2
    actor.close()


def test_suspend_skips_when_not_idle_enough():
    actor = make_actor()
    assert actor.suspend(if_idle_for=3600) is False
    assert actor.suspended is False
    actor.close()


def test_call_auto_resumes_via_hook():
    actor = make_actor()
    actor.suspend()
    calls = {"n": 0}

    def hook():
        calls["n"] += 1
        actor.resume()

    actor._resume_hook = hook
    assert actor.call(lambda: 42) == 42
    assert calls["n"] == 1
    assert actor.suspended is False
    actor.close()


def test_call_without_hook_raises_when_suspended():
    actor = make_actor()
    actor.suspend()
    try:
        actor.call(lambda: 42)
    except ToolError as exc:
        assert exc.code == "session_suspended"
    else:
        raise AssertionError("expected session_suspended")
    actor.close()
