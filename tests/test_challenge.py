from selsnap.backend import score_challenge


def test_detects_cloudflare_like_challenge():
    data = {
        "title": "Just a moment...",
        "url": "https://example.com/?__cf_chl_tk=x",
        "text": "Checking your browser before accessing",
        "signals": ["#challenge-form"],
    }
    result = score_challenge(data, "standard")
    assert result["detected"] is True
    assert result["suggested_mode"] == "uc"
    assert "just a moment" in result["signals"]


def test_clean_page_is_not_challenge():
    result = score_challenge(
        {"title": "Demo Page", "url": "https://example.com", "text": "hello"},
        "standard",
    )
    assert result["detected"] is False
    assert result["signals"] == []


def test_cdp_has_no_suggested_mode():
    result = score_challenge(
        {"title": "Attention Required! | Cloudflare", "url": "", "text": ""},
        "cdp",
    )
    assert result["detected"] is True
    assert result["suggested_mode"] is None
