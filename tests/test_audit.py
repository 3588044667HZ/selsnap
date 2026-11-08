import json

from selsnap.audit import AuditLogger, sanitize_arguments


def test_sanitize_type_text_is_hashed():
    args = sanitize_arguments("type", {"session": "s", "ref": "e1", "text": "hunter2"})
    assert args["text"]["len"] == 7
    assert len(args["text"]["sha256"]) == 16
    assert "hunter2" not in json.dumps(args)


def test_sanitize_sensitive_keys():
    args = sanitize_arguments(
        "navigate", {"url": "https://x", "token": "abc", "password": "p"}
    )
    assert args["token"] == "***"
    assert args["password"] == "***"
    assert args["url"] == "https://x"


def test_sanitize_truncates_long_strings():
    args = sanitize_arguments("navigate", {"url": "x" * 3000})
    assert args["url"].endswith("…")
    assert len(args["url"]) == 2001


def test_audit_logger_writes_jsonl(tmp_path):
    logger = AuditLogger(str(tmp_path), enabled=True)
    logger.record({"agent": "agent-a", "tool": "click", "ok": True})

    files = list(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert payload["agent"] == "agent-a"
    assert payload["tool"] == "click"
    assert payload["ok"] is True
    assert "ts" in payload


def test_audit_logger_disabled_writes_nothing(tmp_path):
    logger = AuditLogger(str(tmp_path), enabled=False)
    logger.record({"agent": "a"})
    assert list(tmp_path.glob("audit-*.jsonl")) == []
