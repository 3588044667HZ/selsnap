from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from .errors import ToolError
from .snapshot import diff_snapshots

if TYPE_CHECKING:
    from .backend import BrowserBackend
    from .config import Settings
    from .sessions import SessionActor

REF_RE = re.compile(r"^e[0-9]{1,9}$")

BUTTONS = ("left", "right")
CLICK_COUNTS = (1, 2)
MAX_TYPED_CHARS = 100_000
MAX_KEYS_LEN = 100
STABLE_TIMEOUT = 1.0
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.12
FULL_SNAPSHOT_RATIO = 0.5

PROBE_REF_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const root = document.documentElement;
  const docId = root ? (root.getAttribute("data-mcp-doc") || null) : null;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false, doc_id: docId};
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  const width = rect.width;
  const height = rect.height;
  const visible = width > 0 && height > 0
    && style.display !== "none"
    && style.visibility !== "hidden"
    && style.visibility !== "collapse"
    && parseFloat(style.opacity || "1") > 0.01;
  const vw = window.innerWidth || 0;
  const vh = window.innerHeight || 0;
  const inViewport = visible && rect.bottom > 0 && rect.right > 0
    && rect.top < vh && rect.left < vw;
  const tag = el.tagName.toLowerCase();
  const role = (el.getAttribute("role") || "").trim().toLowerCase() || tag;
  const disabled = el.disabled === true || el.getAttribute("aria-disabled") === "true";
  const readonly = el.readOnly === true || el.getAttribute("aria-readonly") === "true";
  const contentEditable = el.isContentEditable === true;
  const inputType = (el.getAttribute("type") || "text").toLowerCase();
  const editable = !disabled && !readonly && (
    tag === "textarea" || contentEditable
    || (tag === "input" && !/^(checkbox|radio|button|submit|reset|file|range|color|image|hidden)$/.test(inputType))
  );
  let checked = null;
  if (tag === "input" && (inputType === "checkbox" || inputType === "radio")) {
    checked = !!el.checked;
  }
  let covered = false;
  let coverTag = null;
  if (inViewport) {
    const cx = Math.min(Math.max(rect.left + width / 2, 0), Math.max(vw - 1, 0));
    const cy = Math.min(Math.max(rect.top + height / 2, 0), Math.max(vh - 1, 0));
    const top = document.elementFromPoint(cx, cy);
    if (!top) {
      covered = true;
    } else if (top !== el && !el.contains(top) && !top.contains(el)) {
      covered = true;
      coverTag = top.tagName.toLowerCase();
    }
  }
  return {
    found: true,
    doc_id: docId,
    tag: tag,
    role: role,
    rect: {x: rect.x, y: rect.y, width: width, height: height},
    visible: visible,
    in_viewport: inViewport,
    disabled: disabled,
    readonly: readonly,
    editable: editable,
    checked: checked,
    covered: covered,
    cover_tag: coverTag,
    value: (typeof el.value === "string" ? el.value.slice(0, 200) : null)
  };
})()
"""

SCROLL_REF_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false};
  try {
    el.scrollIntoView({block: "center", inline: "center", behavior: "instant"});
  } catch (error) {
    try { el.scrollIntoView(); } catch (ignored) {}
  }
  return {found: true};
})()
"""

FOCUS_REF_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false};
  try { el.focus({preventScroll: true}); } catch (error) { try { el.focus(); } catch (ignored) {} }
  return {found: true};
})()
"""

CLEAR_REF_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false};
  if (el.isContentEditable && !el.value) {
    el.textContent = "";
  }
  return {found: true};
})()
"""

SELECT_OPTIONS_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false};
  const tag = el.tagName.toLowerCase();
  if (tag !== "select") return {found: true, is_select: false, tag: tag};
  const options = Array.from(el.options || []).map((option, index) => ({
    index: index,
    value: option.value,
    text: (option.textContent || "").replace(/\s+/g, " ").trim(),
    disabled: !!option.disabled,
    selected: !!option.selected
  }));
  return {found: true, is_select: true, multiple: !!el.multiple, options: options};
})()
"""

SET_SELECT_JS = r"""
(() => {
  const REF = __REF_JSON__;
  const INDEX = __INDEX_JSON__;
  const el = document.querySelector('[data-mcp-ref="' + REF + '"]');
  if (!el) return {found: false, changed: false};
  if (el.tagName.toLowerCase() !== "select") return {found: true, changed: false, reason: "not_select"};
  const option = el.options[INDEX];
  if (!option) return {found: true, changed: false, reason: "missing_option"};
  el.selectedIndex = INDEX;
  option.selected = true;
  el.dispatchEvent(new Event("input", {bubbles: true}));
  el.dispatchEvent(new Event("change", {bubbles: true}));
  return {found: true, changed: true, value: el.value, text: (option.textContent || "").trim()};
})()
"""

SCROLL_BY_JS = r"""
(() => {
  const DY = __DY_JSON__;
  window.scrollBy(0, DY);
  return {x: window.scrollX, y: window.scrollY};
})()
"""

DOC_STATE_JS = r"""
(() => {
  const root = document.documentElement;
  return {
    ready: document.readyState,
    url: location.href,
    doc_id: root ? (root.getAttribute("data-mcp-doc") || null) : null
  };
})()
"""

SETTLE_JS = r"""
(async () => {
  const QUIET = __QUIET_MS__;
  const NET_QUIET = __NET_QUIET_MS__;
  const TIMEOUT = __TIMEOUT_MS__;
  const start = performance.now();
  let lastMutation = start;
  let mutationCount = 0;
  let observer = null;
  try {
    observer = new MutationObserver((records) => {
      mutationCount += records.length;
      lastMutation = performance.now();
    });
    if (document.documentElement) {
      observer.observe(document.documentElement, {
        subtree: true, childList: true, attributes: true, characterData: true
      });
    }
  } catch (error) {}
  const resourceCount = () => {
    try { return performance.getEntriesByType("resource").length; } catch (error) { return 0; }
  };
  let resources = resourceCount();
  let lastResource = start;
  let ready = document.readyState;
  let reason = "timeout";
  while (true) {
    if (performance.now() - start >= TIMEOUT) { reason = "timeout"; break; }
    await new Promise((resolve) => setTimeout(resolve, 100));
    ready = document.readyState;
    const count = resourceCount();
    const now = performance.now();
    if (count !== resources) {
      resources = count;
      lastResource = now;
    }
    const domQuiet = now - lastMutation >= QUIET;
    const netQuiet = now - lastResource >= NET_QUIET;
    const readyOk = ready === "complete" || ready === "interactive";
    if (domQuiet && netQuiet && readyOk) { reason = "quiet"; break; }
  }
  if (observer) observer.disconnect();
  return {
    settled: reason === "quiet",
    reason: reason,
    elapsed_ms: Math.round(performance.now() - start),
    mutations: mutationCount,
    ready_state: ready,
    resources: resources
  };
})()
"""

MODIFIER_NAMES = {
    "ctrl": "Control",
    "control": "Control",
    "shift": "Shift",
    "alt": "Alt",
    "meta": "Meta",
    "cmd": "Meta",
    "command": "Meta",
    "win": "Meta",
}

KEY_ALIASES = {
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "space": "Space",
    "arrowup": "ArrowUp",
    "up": "ArrowUp",
    "arrowdown": "ArrowDown",
    "down": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "left": "ArrowLeft",
    "arrowright": "ArrowRight",
    "right": "ArrowRight",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    **{f"f{index}": f"F{index}" for index in range(1, 13)},
}

CDP_KEY_DEFS = {
    "Enter": ("Enter", "Enter", 13, "\r"),
    "Tab": ("Tab", "Tab", 9, ""),
    "Escape": ("Escape", "Escape", 27, ""),
    "Backspace": ("Backspace", "Backspace", 8, ""),
    "Delete": ("Delete", "Delete", 46, ""),
    "Space": (" ", "Space", 32, " "),
    "ArrowUp": ("ArrowUp", "ArrowUp", 38, ""),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40, ""),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37, ""),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39, ""),
    "Home": ("Home", "Home", 36, ""),
    "End": ("End", "End", 35, ""),
    "PageUp": ("PageUp", "PageUp", 33, ""),
    "PageDown": ("PageDown", "PageDown", 34, ""),
    "Control": ("Control", "ControlLeft", 17, ""),
    "Shift": ("Shift", "ShiftLeft", 16, ""),
    "Alt": ("Alt", "AltLeft", 18, ""),
    "Meta": ("Meta", "MetaLeft", 91, ""),
    **{f"F{index}": (f"F{index}", f"F{index}", 111 + index, "") for index in range(1, 13)},
}

MODIFIER_MASK = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


def normalize_ref(ref: str | None) -> str:
    value = (ref or "").strip()
    if not REF_RE.match(value):
        raise ToolError(
            "invalid_argument",
            f"无效的 ref：{ref!r}",
            hint="ref 形如 e12，来自 snapshot 输出中的 [eN]",
        )
    return value


def parse_key_spec(keys: str) -> dict[str, Any]:
    spec = (keys or "").strip()
    if not spec:
        raise ToolError("invalid_argument", "keys 不能为空")
    if len(spec) > MAX_KEYS_LEN:
        raise ToolError("invalid_argument", f"keys 过长（上限 {MAX_KEYS_LEN} 字符）")
    if spec == "+":
        parts = ["+"]
    else:
        raw_parts = spec.split("+")
        parts = []
        for index, part in enumerate(raw_parts):
            if part:
                parts.append(part)
            elif index == len(raw_parts) - 1 and index > 0:
                # "Ctrl++" 表示 Ctrl 加“+”键
                parts.append("+")
    tokens: list[dict[str, str]] = []
    for part in parts:
        if part == "+":
            tokens.append({"char": "+"})
            continue
        lowered = part.lower()
        if lowered in MODIFIER_NAMES:
            tokens.append({"mod": MODIFIER_NAMES[lowered]})
            continue
        name = KEY_ALIASES.get(lowered)
        if name:
            tokens.append({"name": name})
            continue
        if len(part) == 1:
            tokens.append({"char": part})
            continue
        raise ToolError(
            "invalid_argument",
            f"未知按键：{part}",
            hint="支持 Enter/Tab/Escape/Backspace/方向键/F1-F12/单字符，以及 Control+a 这类组合",
        )
    modifiers = [token["mod"] for token in tokens if "mod" in token]
    mains = [token for token in tokens if "mod" not in token]
    if len(mains) != 1:
        raise ToolError(
            "invalid_argument",
            "组合键必须包含且只包含一个主键",
            hint="例如 Control+a、Shift+Tab",
        )
    return {"modifiers": modifiers, "main": mains[0]}


def match_option(option: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    raw = (option or "").strip()
    if not raw:
        raise ToolError("invalid_argument", "option 不能为空")
    enabled = [item for item in options if not item.get("disabled")]
    exact_value = [item for item in enabled if str(item.get("value", "")) == raw]
    if exact_value:
        return exact_value[0]
    exact_text = [item for item in enabled if str(item.get("text", "")).strip() == raw]
    if exact_text:
        return exact_text[0]
    lowered = raw.lower()
    fuzzy = [
        item
        for item in enabled
        if str(item.get("value", "")).lower() == lowered
        or str(item.get("text", "")).strip().lower() == lowered
    ]
    if fuzzy:
        return fuzzy[0]
    raise ToolError(
        "option_not_found",
        f"下拉框中没有匹配的选项：{option}",
        hint="使用选项的 value 或可见文本（大小写不敏感）",
        details={"option": option, "options": options[:30]},
    )


def check_actionability(probe: dict[str, Any], mode: str) -> None:
    ref = probe.get("ref") or ""
    if not probe.get("found"):
        raise ToolError(
            "stale_ref",
            "元素已不存在于当前页面",
            hint="重新调用 snapshot 获取最新 ref",
            details={"ref": ref},
        )
    details = {"ref": ref, "tag": probe.get("tag"), "rect": probe.get("rect")}
    if probe.get("disabled"):
        raise ToolError(
            "not_actionable",
            "元素处于 disabled 状态",
            hint="等待元素启用后再试",
            details={**details, "reason": "disabled"},
        )
    if not probe.get("visible") or not probe.get("in_viewport"):
        raise ToolError(
            "not_actionable",
            "元素不可见或不在视口内",
            hint="先滚动页面或等待元素出现",
            details={**details, "reason": "offscreen"},
        )
    if mode in ("click", "hover") and probe.get("covered"):
        raise ToolError(
            "not_actionable",
            "元素被其他节点遮挡",
            hint="先关闭弹层/对话框，或改用 click_at（计划 M2）",
            details={**details, "reason": "covered", "cover_tag": probe.get("cover_tag")},
        )
    if mode == "type" and not probe.get("editable"):
        raise ToolError(
            "not_actionable",
            "元素不可编辑",
            hint="确认目标是输入框或可编辑区域",
            details={**details, "reason": "not_editable"},
        )
    if mode == "select" and probe.get("tag") != "select":
        raise ToolError(
            "invalid_argument",
            "select 仅支持原生下拉框",
            hint="自定义下拉请用 click 序列操作",
            details={**details, "reason": "not_select"},
        )


class ActionRunner:
    def __init__(self, actor: "SessionActor", settings: "Settings") -> None:
        self.actor = actor
        self.backend: "BrowserBackend" = actor.backend
        self.settings = settings

    def click(self, ref: str, button: str = "left", count: int = 1, full: bool = False) -> dict[str, Any]:
        ref = normalize_ref(ref)
        if button not in BUTTONS:
            raise ToolError("invalid_argument", f"不支持的鼠标键：{button}", hint="可用：left / right")
        if count not in CLICK_COUNTS:
            raise ToolError("invalid_argument", f"不支持的点击次数：{count}", hint="可用：1 / 2")
        if button == "right" and count != 1:
            raise ToolError("invalid_argument", "右键双击暂不支持")
        self._run(ref, "click", lambda: self.backend.click_ref(ref, button=button, count=count))
        return self._observe("click", ref, full)

    def type_text(
        self,
        ref: str,
        text: str,
        clear: bool = True,
        submit: bool = False,
        full: bool = False,
    ) -> dict[str, Any]:
        ref = normalize_ref(ref)
        value = "" if text is None else str(text)
        if len(value) > MAX_TYPED_CHARS:
            raise ToolError("invalid_argument", f"文本过长（上限 {MAX_TYPED_CHARS} 字符）")
        self._run(
            ref,
            "type",
            lambda: self.backend.type_ref(ref, value, clear=bool(clear), submit=bool(submit)),
        )
        return self._observe("type", ref, full, extra={"typed_chars": len(value)})

    def select(self, ref: str, option: str, full: bool = False) -> dict[str, Any]:
        ref = normalize_ref(ref)
        self._assert_doc()
        data = self.backend.select_options(ref)
        if not data.get("found"):
            raise ToolError("stale_ref", "下拉框已不存在", details={"ref": ref})
        if not data.get("is_select"):
            raise ToolError(
                "invalid_argument",
                "select 仅支持原生下拉框",
                hint="自定义下拉请用 click 序列操作",
                details={"ref": ref, "tag": data.get("tag")},
            )
        matched = match_option(option, data.get("options") or [])
        self._run(ref, "select", lambda: self.backend.select_option(ref, matched["index"]))
        return self._observe("select", ref, full, extra={"option": matched})

    def press(self, keys: str, ref: str | None = None, full: bool = False) -> dict[str, Any]:
        parsed = parse_key_spec(keys)
        if ref is None:
            self.backend.press_keys(parsed, ref=None)
        else:
            ref = normalize_ref(ref)
            self._run(ref, "press", lambda: self.backend.press_keys(parsed, ref=ref))
        return self._observe("press", ref, full, extra={"keys": keys})

    def hover(self, ref: str, full: bool = False) -> dict[str, Any]:
        ref = normalize_ref(ref)
        self._run(ref, "hover", lambda: self.backend.hover_ref(ref))
        return self._observe("hover", ref, full)

    def scroll(self, ref: str | None = None, dy: int = 600, full: bool = False) -> dict[str, Any]:
        if not isinstance(dy, int) or isinstance(dy, bool):
            raise ToolError("invalid_argument", "dy 必须是整数")
        if dy == 0:
            raise ToolError("invalid_argument", "dy 不能为 0")
        if abs(dy) > 100_000:
            raise ToolError("invalid_argument", "dy 超出合理范围（|dy| <= 100000）")
        if ref is None:
            self.backend.scroll_by(dy)
        else:
            ref = normalize_ref(ref)
            self._assert_doc()
            data = self.backend.scroll_ref_into_view(ref)
            if not data.get("found"):
                raise ToolError("stale_ref", "元素已不存在", details={"ref": ref})
        return self._observe("scroll", ref, full, extra={"dy": dy})

    def click_at(
        self,
        x: float,
        y: float,
        button: str = "left",
        count: int = 1,
        full: bool = False,
    ) -> dict[str, Any]:
        for name, value in (("x", x), ("y", y)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ToolError("invalid_argument", f"{name} 必须是数字")
            if value < 0 or value > 1_000_000:
                raise ToolError("invalid_argument", f"{name} 超出合理范围")
        if button not in BUTTONS:
            raise ToolError("invalid_argument", f"不支持的鼠标键：{button}", hint="可用：left / right")
        if count not in CLICK_COUNTS:
            raise ToolError("invalid_argument", f"不支持的点击次数：{count}", hint="可用：1 / 2")
        if button == "right" and count != 1:
            raise ToolError("invalid_argument", "右键双击暂不支持")
        self._assert_doc()
        point = self.backend.point_info(float(x), float(y))
        if not point.get("in_viewport"):
            raise ToolError(
                "not_actionable",
                "坐标不在视口内",
                hint="先滚动页面或改用元素 ref",
                details={"x": x, "y": y, "reason": "offscreen"},
            )
        if not point.get("found"):
            raise ToolError(
                "not_actionable",
                "坐标处没有可交互的页面节点",
                details={"x": x, "y": y, "reason": "offscreen"},
            )
        self.backend.click_at(float(x), float(y), button=button, count=count)
        return self._observe(
            "click_at",
            None,
            full,
            extra={
                "x": x,
                "y": y,
                "target_ref": point.get("ref"),
                "target_tag": point.get("tag"),
            },
        )

    def dialog(self, action: str = "accept", text: str | None = None, full: bool = False) -> dict[str, Any]:
        if action not in ("accept", "dismiss"):
            raise ToolError(
                "invalid_argument", f"未知对话框动作：{action}", hint="accept / dismiss"
            )
        if not self.backend.has_dialog():
            raise ToolError(
                "dialog_not_open",
                "当前页面没有待处理的对话框",
                hint="先执行会触发对话框的动作",
            )
        info = self.backend.handle_dialog(action, text)
        if self.backend.has_dialog():
            raise ToolError(
                "dialog_open",
                "对话框中还有未处理的原生对话框",
                hint="继续调用 dialog 处理下一个对话框",
                details={"dialog": info},
            )
        return self._observe(
            "dialog",
            None,
            full,
            extra={"dialog_action": action, "dialog": info},
        )

    def _assert_doc(self) -> None:
        current = self.backend.doc_id()
        expected = self.actor.last_doc_id
        if expected is None:
            raise ToolError(
                "stale_ref",
                "尚无页面快照，ref 不可用",
                hint="先调用 snapshot 获取 [eN] ref",
                details={"doc_id": current},
            )
        if current != expected:
            raise ToolError(
                "stale_ref",
                "页面已变化：ref 属于旧文档",
                hint="重新调用 snapshot 获取新的 ref",
                details={"doc_id": current, "expected_doc_id": expected},
            )

    def _wait_stable(self, ref: str) -> dict[str, Any]:
        deadline = time.monotonic() + STABLE_TIMEOUT
        previous = None
        probe: dict[str, Any] = {}
        while time.monotonic() < deadline:
            probe = self.backend.probe_ref(ref)
            if not probe.get("found"):
                break
            rect = probe.get("rect") or {}
            current = (rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"))
            if previous == current:
                return probe
            previous = current
            time.sleep(0.05)
        return probe

    def _run(self, ref: str, mode: str, operation) -> None:
        self._assert_doc()
        if self.backend.has_dialog():
            raise ToolError(
                "dialog_open",
                "页面上有未处理的对话框",
                hint="先用 dialog 工具 accept/dismiss 处理对话框",
            )
        for attempt in range(RETRY_ATTEMPTS):
            try:
                data = self.backend.scroll_ref_into_view(ref)
                if not data.get("found"):
                    raise ToolError(
                        "stale_ref",
                        "元素已不存在于当前页面",
                        hint="重新调用 snapshot 获取最新 ref",
                        details={"ref": ref},
                    )
                probe = self._wait_stable(ref)
                probe["ref"] = ref
                check_actionability(probe, mode)
                operation()
                if self.backend.has_dialog():
                    raise ToolError(
                        "dialog_open",
                        "动作触发了原生对话框",
                        hint="先用 dialog 工具 accept/dismiss 处理对话框",
                        details={"ref": ref, "action_performed": True},
                    )
                return
            except ToolError as exc:
                if exc.code == "stale_ref" and exc.details.get("expected_doc_id"):
                    raise
                if exc.code not in ("stale_ref", "not_actionable") or attempt >= RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(RETRY_DELAY * (attempt + 1))

    def _settle(self) -> dict[str, Any]:
        result = self.backend.settle(self.settings.settle_timeout)
        if result.get("reason") == "context_destroyed":
            self.backend.wait_document_ready(min(10.0, self.settings.page_load_timeout))
        return result

    def _capture(self) -> dict[str, Any]:
        return self.backend.snapshot(
            self.settings.snapshot_max_nodes,
            self.settings.snapshot_max_chars,
            ref_base=self.actor.next_ref_base,
        )

    def _observe(
        self,
        action: str,
        ref: str | None,
        full: bool,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settle = self._settle()
        if self.backend.has_dialog():
            raise ToolError(
                "dialog_open",
                "动作后页面弹出了原生对话框",
                hint="先用 dialog 工具 accept/dismiss 处理对话框",
                details={"ref": ref, "action_performed": True},
            )
        try:
            raw = self._capture()
        except ToolError:
            self.backend.wait_document_ready(min(10.0, self.settings.page_load_timeout))
            raw = self._capture()
        old_doc = self.actor.last_doc_id
        old_tree = self.actor.last_tree
        self.actor.record_snapshot(raw)
        payload: dict[str, Any] = {
            "action": action,
            "doc_id": raw.get("doc_id"),
            "url": raw.get("url"),
            "title": raw.get("title"),
            "settle": settle,
        }
        if ref:
            payload["ref"] = ref
        if extra:
            payload.update(extra)
        navigated = bool(old_doc) and raw.get("doc_id") != old_doc
        if navigated:
            payload.update(
                {
                    "changed": True,
                    "navigated": True,
                    "snapshot": raw.get("snapshot") or "",
                    "stats": raw.get("stats") or {},
                    "full_snapshot_reason": "navigation",
                }
            )
            return payload
        if old_tree is None:
            payload.update(
                {
                    "changed": True,
                    "snapshot": raw.get("snapshot") or "",
                    "stats": raw.get("stats") or {},
                    "full_snapshot_reason": "no_previous_snapshot",
                }
            )
            return payload
        diff = diff_snapshots(old_tree, raw.get("tree"))
        payload["changed"] = diff["changed"]
        payload["diff"] = diff
        if full or diff["change_ratio"] > FULL_SNAPSHOT_RATIO:
            payload["snapshot"] = raw.get("snapshot") or ""
            payload["stats"] = raw.get("stats") or {}
            payload["full_snapshot_reason"] = "requested" if full else "large_change"
        return payload


def render_probe_js(ref: str) -> str:
    return PROBE_REF_JS.replace("__REF_JSON__", json.dumps(ref))


def render_scroll_ref_js(ref: str) -> str:
    return SCROLL_REF_JS.replace("__REF_JSON__", json.dumps(ref))


def render_focus_ref_js(ref: str) -> str:
    return FOCUS_REF_JS.replace("__REF_JSON__", json.dumps(ref))


def render_clear_ref_js(ref: str) -> str:
    return CLEAR_REF_JS.replace("__REF_JSON__", json.dumps(ref))


def render_select_options_js(ref: str) -> str:
    return SELECT_OPTIONS_JS.replace("__REF_JSON__", json.dumps(ref))


def render_set_select_js(ref: str, index: int) -> str:
    return SET_SELECT_JS.replace("__REF_JSON__", json.dumps(ref)).replace(
        "__INDEX_JSON__", json.dumps(index)
    )


def render_scroll_by_js(dy: int) -> str:
    return SCROLL_BY_JS.replace("__DY_JSON__", json.dumps(dy))


def render_settle_js(timeout: float, quiet_ms: int = 300, net_quiet_ms: int = 500) -> str:
    return (
        SETTLE_JS.replace("__QUIET_MS__", str(quiet_ms))
        .replace("__NET_QUIET_MS__", str(net_quiet_ms))
        .replace("__TIMEOUT_MS__", str(int(timeout * 1000)))
    )
