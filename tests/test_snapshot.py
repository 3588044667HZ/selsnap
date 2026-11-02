from selsnap.snapshot import render_snapshot


def test_renders_elements_text_and_attributes():
    data = {
        "tree": {
            "type": "element",
            "role": "document",
            "name": "",
            "ref": "",
            "attrs": {},
            "children": [
                {
                    "type": "element",
                    "role": "heading",
                    "name": "Welcome",
                    "ref": "e1",
                    "attrs": {"level": 1},
                    "children": [],
                },
                {
                    "type": "element",
                    "role": "link",
                    "name": "Home",
                    "ref": "e2",
                    "attrs": {"href": "/home"},
                    "children": [],
                },
                {"type": "text", "text": "hello world"},
            ],
        }
    }

    text, stats = render_snapshot(data, max_chars=4000)

    assert '- heading "Welcome" [e1] level=1' in text
    assert '- link "Home" [e2] href="/home"' in text
    assert '- text "hello world"' in text
    assert stats["truncated"] is False
    assert stats["rendered_nodes"] == 4


def test_renders_nested_children_with_indentation():
    data = {
        "tree": {
            "type": "element",
            "role": "document",
            "name": "",
            "ref": "",
            "attrs": {},
            "children": [
                {
                    "type": "element",
                    "role": "list",
                    "name": "",
                    "ref": "e1",
                    "attrs": {},
                    "children": [
                        {
                            "type": "element",
                            "role": "listitem",
                            "name": "",
                            "ref": "e2",
                            "attrs": {},
                            "children": [
                                {
                                    "type": "element",
                                    "role": "link",
                                    "name": "Item",
                                    "ref": "e3",
                                    "attrs": {},
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }

    text, _ = render_snapshot(data, max_chars=4000)

    assert '- list [e1]:' in text
    assert '  - listitem [e2]:' in text
    assert '    - link "Item" [e3]' in text


def test_quotes_are_escaped():
    data = {
        "tree": {
            "type": "element",
            "role": "button",
            "name": 'He said "hi"',
            "ref": "e1",
            "attrs": {"value": 'a"b'},
            "children": [],
        }
    }

    text, _ = render_snapshot(data, max_chars=4000)

    assert '- button "He said \\"hi\\"" [e1] value="a\\"b"' in text


def test_truncates_at_char_budget():
    children = [
        {
            "type": "element",
            "role": "link",
            "name": f"item-{index}",
            "ref": f"e{index}",
            "attrs": {},
            "children": [],
        }
        for index in range(1, 50)
    ]
    data = {
        "tree": {
            "type": "element",
            "role": "document",
            "name": "",
            "ref": "",
            "attrs": {},
            "children": children,
        }
    }

    text, stats = render_snapshot(data, max_chars=300)

    assert stats["truncated"] is True
    assert "[truncated: rendered" in text
    assert len(text) < 400


def test_empty_tree_returns_empty_text():
    text, stats = render_snapshot({"tree": None}, max_chars=4000)

    assert text == ""
    assert stats["rendered_nodes"] == 0
    assert stats["truncated"] is False
