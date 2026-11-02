import pytest

from selsnap.errors import ToolError
from selsnap.server import _normalize_url


def test_adds_https_scheme():
    assert _normalize_url("example.com") == "https://example.com"


def test_host_with_port():
    assert _normalize_url("example.com:8080/path") == "https://example.com:8080/path"


def test_keeps_http():
    assert _normalize_url("http://example.com/a?b=1") == "http://example.com/a?b=1"


def test_protocol_relative():
    assert _normalize_url("//example.com/x") == "https://example.com/x"


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/x",
        "javascript:alert(1)",
        "data:text/html,x",
        "mailto:a@b.c",
        "about:blank",
    ],
)
def test_blocks_schemes(url):
    with pytest.raises(ToolError) as info:
        _normalize_url(url)
    assert info.value.code == "policy_blocked"


def test_blocks_credentials():
    with pytest.raises(ToolError) as info:
        _normalize_url("http://user:pass@example.com")
    assert info.value.code == "policy_blocked"


def test_empty_url():
    with pytest.raises(ToolError) as info:
        _normalize_url("  ")
    assert info.value.code == "invalid_argument"
