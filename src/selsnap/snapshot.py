from __future__ import annotations

import json
from typing import Any

SNAPSHOT_JS = r"""
(() => {
  const MAX_NODES = __MAX_NODES__;
  const MAX_NAME = 120;
  const MAX_TEXT = 240;
  const MAX_VALUE = 80;
  const MAX_URL = 160;
  const SKIP_TAGS = new Set([
    "script", "style", "noscript", "template", "meta", "link", "head", "title", "base",
    "option", "br", "hr", "svg", "path", "circle", "rect", "g", "defs", "use", "symbol"
  ]);
  const STRUCTURAL = new Set([
    "document", "navigation", "main", "banner", "contentinfo", "complementary",
    "form", "list", "listitem", "table", "row", "cell", "dialog", "group"
  ]);
  const norm = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const clip = (value, limit) => {
    const text = norm(value);
    return text.length > limit ? text.slice(0, limit - 1) + "…" : text;
  };

  const rootEl = document.documentElement;
  let docId = rootEl.getAttribute("data-mcp-doc");
  if (!docId) {
    docId = "d" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    rootEl.setAttribute("data-mcp-doc", docId);
  }
  // 跨文档单调递增：新文档没有 counter 时从 REF_BASE 起编号，避免旧 ref 命中新元素
  const REF_BASE = __REF_BASE__;
  let refCounter = parseInt(
    rootEl.getAttribute("data-mcp-ref-counter") || String(REF_BASE), 10
  );
  let totalElements = 0;
  let visibleElements = 0;
  let included = 0;
  let truncated = false;

  const isVisible = (el, style) => {
    if (!el.getClientRects().length) return false;
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
    if (parseFloat(style.opacity || "1") <= 0.01) return false;
    return true;
  };

  const roleOf = (el) => {
    const explicit = (el.getAttribute("role") || "").trim().toLowerCase();
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : null;
    if (tag === "button") return "button";
    if (tag === "input") {
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "submit" || type === "button" || type === "reset" || type === "image") return "button";
      if (type === "file") return "file";
      if (type === "search") return "searchbox";
      if (type === "hidden") return null;
      return "textbox";
    }
    if (tag === "textarea") return "textbox";
    if (tag === "select") return el.multiple ? "listbox" : "combobox";
    if (tag === "img") return "img";
    if (/^h[1-6]$/.test(tag)) return "heading";
    if (tag === "nav") return "navigation";
    if (tag === "main") return "main";
    if (tag === "header") return "banner";
    if (tag === "footer") return "contentinfo";
    if (tag === "aside") return "complementary";
    if (tag === "form") return "form";
    if (tag === "ul" || tag === "ol") return "list";
    if (tag === "li") return "listitem";
    if (tag === "table") return "table";
    if (tag === "tr") return "row";
    if (tag === "td" || tag === "th") return "cell";
    if (tag === "dialog") return "dialog";
    if (tag === "iframe") return "iframe";
    if (tag === "canvas") return "canvas";
    if (tag === "summary") return "button";
    if (tag === "details") return "group";
    if (tag === "label") return "label";
    if (el.isContentEditable) return "textbox";
    return null;
  };

  const labelText = (el) => {
    const parts = [];
    const aria = el.getAttribute("aria-label");
    if (aria) parts.push(aria);
    const ids = el.getAttribute("aria-labelledby");
    if (ids) {
      for (const id of ids.split(/\s+/)) {
        const target = document.getElementById(id);
        if (target) parts.push(target.innerText || target.textContent || "");
      }
    }
    return clip(parts.join(" "), MAX_NAME);
  };

  const nameOf = (el, role) => {
    const labelled = labelText(el);
    if (labelled) return labelled;
    const tag = el.tagName.toLowerCase();
    if (tag === "img") return clip(el.getAttribute("alt") || "", MAX_NAME);
    if (tag === "input" || tag === "textarea" || tag === "select") {
      const placeholder = el.getAttribute("placeholder");
      if (placeholder) return clip(placeholder, MAX_NAME);
      if (el.id) {
        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (label) return clip(label.innerText || label.textContent || "", MAX_NAME);
      }
      const parentLabel = el.closest("label");
      if (parentLabel) return clip(parentLabel.innerText || parentLabel.textContent || "", MAX_NAME);
      return clip(el.getAttribute("name") || "", MAX_NAME);
    }
    const title = el.getAttribute("title");
    if (title) return clip(title, MAX_NAME);
    if (STRUCTURAL.has(role)) return "";
    return clip(el.innerText || el.textContent || "", MAX_NAME);
  };

  const attrsOf = (el, role) => {
    const attrs = {};
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (type) attrs.type = type;
      if (type === "password") {
        attrs.value = "•••";
      } else if (tag === "select") {
        const selected = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
        if (selected) attrs.value = clip(selected.textContent, MAX_VALUE);
      } else if (el.value) {
        attrs.value = clip(el.value, MAX_VALUE);
      }
      if (el.checked) attrs.checked = true;
      if (el.required) attrs.required = true;
      if (el.disabled) attrs.disabled = true;
    }
    if (tag === "a") {
      const href = el.getAttribute("href");
      if (href) attrs.href = clip(href, MAX_URL);
    }
    if (role === "heading") {
      const level = parseInt(tag.slice(1), 10);
      if (level) attrs.level = level;
    }
    if (tag === "iframe") {
      const src = el.getAttribute("src");
      if (src) attrs.src = clip(src, MAX_URL);
    }
    if (el.getAttribute("aria-expanded") !== null) {
      attrs.expanded = el.getAttribute("aria-expanded");
    }
    if (el.disabled) attrs.disabled = true;
    return attrs;
  };

  const refFor = (el) => {
    let ref = el.getAttribute("data-mcp-ref");
    if (!ref) {
      refCounter += 1;
      ref = "e" + refCounter;
      el.setAttribute("data-mcp-ref", ref);
    }
    return ref;
  };

  const walk = (el) => {
    if (!el || el.nodeType !== 1) return null;
    const tag = el.tagName.toLowerCase();
    if (SKIP_TAGS.has(tag)) return null;
    totalElements += 1;
    const style = window.getComputedStyle(el);
    if (!isVisible(el, style)) return null;
    if (el.getAttribute("aria-hidden") === "true") return null;
    visibleElements += 1;

    const role = roleOf(el);
    const meaningful = !!role || tag === "iframe" || tag === "canvas";
    // ref 先于子节点分配，保证编号大体按文档顺序
    let ref = "";
    if (meaningful) {
      if (included >= MAX_NODES) {
        truncated = true;
        return null;
      }
      included += 1;
      ref = refFor(el);
    }
    const children = [];
    const appendChild = (node) => {
      if (!node) return;
      if (node.type === "fragment") {
        for (const item of node.children) children.push(item);
      } else {
        children.push(node);
      }
    };
    const visitNodes = (parent) => {
      for (const child of parent.childNodes) {
        if (child.nodeType === 3) {
          const text = clip(child.nodeValue, MAX_TEXT);
          if (text) appendChild({ type: "text", text: text });
        } else if (child.nodeType === 1) {
          appendChild(walk(child));
        }
      }
    };

    if (el.shadowRoot) visitNodes(el.shadowRoot);
    visitNodes(el);

    if (!meaningful) {
      return children.length ? { type: "fragment", children: children } : null;
    }

    const elementChildren = children.filter((child) => child.type === "element");
    return {
      type: "element",
      role: role || tag,
      name: nameOf(el, role),
      ref: ref,
      attrs: attrsOf(el, role),
      children: elementChildren,
    };
  };

  let tree = null;
  if (document.body) {
    tree = walk(document.body);
    if (tree && tree.type === "fragment") {
      tree = {
        type: "element",
        role: "document",
        name: document.title || "",
        ref: "",
        attrs: {},
        children: tree.children,
      };
    }
  }
  rootEl.setAttribute("data-mcp-ref-counter", String(refCounter));
  return {
    doc_id: docId,
    url: location.href,
    title: document.title,
    stats: {
      total_elements: totalElements,
      visible_elements: visibleElements,
      included_nodes: included,
      max_nodes: MAX_NODES,
      truncated: truncated,
      ref_counter: refCounter,
    },
    tree: tree,
  };
})()
"""

_ATTR_ORDER = (
    "level",
    "value",
    "type",
    "checked",
    "disabled",
    "required",
    "expanded",
    "href",
    "src",
)


def _attrs_text(attrs: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _ATTR_ORDER:
        if key not in attrs:
            continue
        value = attrs[key]
        if isinstance(value, bool):
            if value:
                parts.append(key)
        elif key == "level" and isinstance(value, int):
            parts.append(f"{key}={value}")
        elif value is not None and str(value) != "":
            parts.append(f"{key}={json.dumps(str(value), ensure_ascii=False)}")
    return (" " + " ".join(parts)) if parts else ""



def render_node_head(node: dict[str, Any]) -> str:
    role = node.get("role") or "element"
    name = node.get("name") or ""
    ref = node.get("ref") or ""
    head = f"- {role}"
    if name:
        head += " " + json.dumps(name, ensure_ascii=False)
    if ref:
        head += f" [{ref}]"
    head += _attrs_text(node.get("attrs") or {})
    return head


def render_snapshot(data: dict[str, Any], max_chars: int = 16000) -> tuple[str, dict[str, Any]]:
    tree = data.get("tree")
    if not isinstance(tree, dict):
        return "", {"rendered_nodes": 0, "truncated": False, "chars": 0}

    lines: list[str] = []
    size = 0
    rendered = 0
    truncated = False

    def add(line: str) -> bool:
        nonlocal size, truncated
        if truncated:
            return False
        if size + len(line) + 1 > max_chars:
            truncated = True
            return False
        lines.append(line)
        size += len(line) + 1
        return True

    def emit(node: dict[str, Any], depth: int) -> None:
        nonlocal rendered
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        indent = "  " * depth
        if kind == "fragment":
            for child in node.get("children") or []:
                emit(child, depth)
            return
        if kind == "text":
            text = node.get("text") or ""
            if add(f"{indent}- text {json.dumps(text, ensure_ascii=False)}"):
                rendered += 1
            return

        head = indent + render_node_head(node)
        children = node.get("children") or []
        if children:
            if not add(head + ":"):
                return
            rendered += 1
            for child in children:
                emit(child, depth + 1)
        else:
            if add(head):
                rendered += 1

    emit(tree, 0)
    if truncated:
        lines.append(f"- [truncated: rendered {rendered} nodes, max_chars={max_chars}]")
    return "\n".join(lines), {"rendered_nodes": rendered, "truncated": truncated, "chars": size}


def flatten_refs(tree: Any) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        if kind == "element":
            ref = node.get("ref")
            if ref:
                nodes[ref] = node
        if kind in ("element", "fragment"):
            for child in node.get("children") or []:
                walk(child)

    walk(tree)
    return nodes


def ref_order(ref: str) -> int:
    try:
        return int(ref[1:])
    except (TypeError, ValueError):
        return 0


_ref_order = ref_order


def diff_snapshots(old_tree: Any, new_tree: Any) -> dict[str, Any]:
    old = flatten_refs(old_tree)
    new = flatten_refs(new_tree)
    added_refs = sorted(new.keys() - old.keys(), key=_ref_order)
    removed_refs = sorted(old.keys() - new.keys(), key=_ref_order)
    updated_refs = sorted(
        (
            ref
            for ref in new.keys() & old.keys()
            if render_node_head(old[ref]) != render_node_head(new[ref])
        ),
        key=_ref_order,
    )
    added = [render_node_head(new[ref]) for ref in added_refs]
    removed = [render_node_head(old[ref]) for ref in removed_refs]
    updated = [render_node_head(new[ref]) for ref in updated_refs]
    changed_count = len(added) + len(removed) + len(updated)
    base = max(len(old), len(new), 1)
    return {
        "changed": changed_count > 0,
        "added": added,
        "removed": removed,
        "updated": updated,
        "new_refs": added_refs,
        "removed_refs": removed_refs,
        "updated_refs": updated_refs,
        "change_ratio": round(min(1.0, changed_count / base), 3),
    }
