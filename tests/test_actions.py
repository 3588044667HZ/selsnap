import pytest

from selsnap.actions import (
    check_actionability,
    match_option,
    normalize_ref,
    parse_key_spec,
)
from selsnap.errors import ToolError
from selsnap.snapshot import diff_snapshots, flatten_refs, render_node_head


def test_normalize_ref_accepts_ref():
    assert normalize_ref("e12") == "e12"
    assert normalize_ref(" e3 ") == "e3"


@pytest.mark.parametrize("ref", ["", "12", "e", "e1a", "ref=e2", "[e2]"])
def test_normalize_ref_rejects_invalid(ref):
    with pytest.raises(ToolError) as info:
        normalize_ref(ref)
    assert info.value.code == "invalid_argument"


def test_parse_key_spec_single_char():
    parsed = parse_key_spec("a")
    assert parsed == {"modifiers": [], "main": {"char": "a"}}


def test_parse_key_spec_named_keys_are_case_insensitive():
    assert parse_key_spec("Enter")["main"] == {"name": "Enter"}
    assert parse_key_spec("esc")["main"] == {"name": "Escape"}
    assert parse_key_spec("arrowdown")["main"] == {"name": "ArrowDown"}
    assert parse_key_spec("f5")["main"] == {"name": "F5"}


def test_parse_key_spec_modifier_combos():
    parsed = parse_key_spec("Control+a")
    assert parsed["modifiers"] == ["Control"]
    assert parsed["main"] == {"char": "a"}

    parsed = parse_key_spec("Ctrl+Shift+Tab")
    assert parsed["modifiers"] == ["Control", "Shift"]
    assert parsed["main"] == {"name": "Tab"}


def test_parse_key_spec_literal_plus():
    assert parse_key_spec("+")["main"] == {"char": "+"}
    assert parse_key_spec("Ctrl++")["modifiers"] == ["Control"]
    assert parse_key_spec("Ctrl++")["main"] == {"char": "+"}


@pytest.mark.parametrize("keys", ["", "abc", "Control+Shift", "Control+a+b"])
def test_parse_key_spec_rejects_bad_input(keys):
    with pytest.raises(ToolError) as info:
        parse_key_spec(keys)
    assert info.value.code == "invalid_argument"


OPTIONS = [
    {"index": 0, "value": "25%", "text": "Set to 25%", "disabled": False},
    {"index": 1, "value": "50%", "text": "Set to 50%", "disabled": False},
    {"index": 2, "value": "", "text": "Empty", "disabled": False},
    {"index": 3, "value": "x", "text": "Disabled", "disabled": True},
]


def test_match_option_by_value():
    assert match_option("50%", OPTIONS)["index"] == 1


def test_match_option_by_text():
    assert match_option("Set to 25%", OPTIONS)["index"] == 0


def test_match_option_case_insensitive_and_whitespace():
    assert match_option("  set to 50% ", OPTIONS)["index"] == 1


def test_match_option_skips_disabled():
    with pytest.raises(ToolError) as info:
        match_option("Disabled", OPTIONS)
    assert info.value.code == "option_not_found"
    assert info.value.details["options"] == OPTIONS


def test_match_option_missing():
    with pytest.raises(ToolError) as info:
        match_option("nope", OPTIONS)
    assert info.value.code == "option_not_found"


def _probe(**overrides):
    base = {
        "found": True,
        "tag": "button",
        "visible": True,
        "in_viewport": True,
        "disabled": False,
        "covered": False,
        "editable": False,
    }
    base.update(overrides)
    return base


def test_actionability_ok_for_click():
    check_actionability(_probe(), "click")


def test_actionability_missing_ref():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(found=False), "click")
    assert info.value.code == "stale_ref"


def test_actionability_disabled():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(disabled=True), "click")
    assert info.value.code == "not_actionable"
    assert info.value.details["reason"] == "disabled"


def test_actionability_hidden():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(visible=False), "click")
    assert info.value.details["reason"] == "offscreen"


def test_actionability_covered():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(covered=True, cover_tag="div"), "click")
    assert info.value.details["reason"] == "covered"


def test_actionability_covered_ignored_for_type():
    check_actionability(_probe(tag="input", covered=True, editable=True), "type")


def test_actionability_type_requires_editable():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(tag="input", editable=False), "type")
    assert info.value.details["reason"] == "not_editable"


def test_actionability_select_requires_native_select():
    with pytest.raises(ToolError) as info:
        check_actionability(_probe(tag="div"), "select")
    assert info.value.code == "invalid_argument"


def test_flatten_refs_collects_elements_only():
    tree = {
        "type": "element",
        "role": "document",
        "ref": "",
        "children": [
            {
                "type": "element",
                "role": "button",
                "name": "Go",
                "ref": "e1",
                "attrs": {},
                "children": [],
            },
            {"type": "text", "text": "hello"},
        ],
    }
    refs = flatten_refs(tree)
    assert set(refs) == {"e1"}
    assert render_node_head(refs["e1"]) == '- button "Go" [e1]'


def test_diff_snapshots_reports_added_removed_updated():
    old = {
        "type": "element",
        "role": "document",
        "ref": "",
        "attrs": {},
        "children": [
            {
                "type": "element",
                "role": "textbox",
                "name": "Name",
                "ref": "e1",
                "attrs": {"value": ""},
                "children": [],
            },
            {
                "type": "element",
                "role": "link",
                "name": "Old",
                "ref": "e2",
                "attrs": {"href": "/old"},
                "children": [],
            },
        ],
    }
    new = {
        "type": "element",
        "role": "document",
        "ref": "",
        "attrs": {},
        "children": [
            {
                "type": "element",
                "role": "textbox",
                "name": "Name",
                "ref": "e1",
                "attrs": {"value": "hi"},
                "children": [],
            },
            {
                "type": "element",
                "role": "button",
                "name": "Go",
                "ref": "e3",
                "attrs": {},
                "children": [],
            },
        ],
    }

    diff = diff_snapshots(old, new)

    assert diff["changed"] is True
    assert diff["added"] == ['- button "Go" [e3]']
    assert diff["removed"] == ['- link "Old" [e2] href="/old"']
    assert diff["updated"] == ['- textbox "Name" [e1] value="hi"']
    assert diff["new_refs"] == ["e3"]
    assert diff["removed_refs"] == ["e2"]
    assert diff["updated_refs"] == ["e1"]
    assert diff["change_ratio"] == 1.0


def test_diff_snapshots_no_change():
    tree = {
        "type": "element",
        "role": "document",
        "ref": "",
        "attrs": {},
        "children": [
            {
                "type": "element",
                "role": "button",
                "name": "Go",
                "ref": "e1",
                "attrs": {},
                "children": [],
            }
        ],
    }
    diff = diff_snapshots(tree, tree)
    assert diff["changed"] is False
    assert diff["change_ratio"] == 0.0
