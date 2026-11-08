from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont

from .actions import normalize_ref
from .errors import ToolError
from .snapshot import flatten_refs, ref_order

if TYPE_CHECKING:
    from .config import Settings
    from .sessions import SessionActor

MAX_IMAGE_PIXELS = 40_000_000


def _load_font(scale: float) -> ImageFont.ImageFont:
    size = max(11, int(round(13 * max(1.0, scale))))
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _draw_annotation(
    image: Image.Image,
    rects: list[dict[str, Any]],
    *,
    scale_x: float,
    scale_y: float,
    offset_x: float,
    offset_y: float,
) -> None:
    draw = ImageDraw.Draw(image)
    font = _load_font(max(scale_x, scale_y))
    for item in rects:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        x = (float(item["x"]) + offset_x) * scale_x
        y = (float(item["y"]) + offset_y) * scale_y
        width = float(item["width"]) * scale_x
        height = float(item["height"]) * scale_y
        if width < 4 or height < 4:
            continue
        left, top = int(round(x)), int(round(y))
        right, bottom = int(round(x + width)), int(round(y + height))
        if right <= 0 or bottom <= 0 or left >= image.width or top >= image.height:
            continue
        draw.rectangle(
            [left, top, min(right, image.width - 1), min(bottom, image.height - 1)],
            outline=(255, 40, 40),
            width=max(1, int(round(scale_x))),
        )
        label = ref
        try:
            text_box = draw.textbbox((0, 0), label, font=font)
            text_w = text_box[2] - text_box[0]
            text_h = text_box[3] - text_box[1]
        except Exception:
            text_w, text_h = 6 * len(label), 10
        pad = 3
        label_x = min(max(left, 0), max(0, image.width - text_w - 2 * pad))
        label_y = top - text_h - 2 * pad
        if label_y < 0:
            label_y = min(bottom + 1, max(0, image.height - text_h - 2 * pad))
        draw.rectangle(
            [
                label_x,
                label_y,
                min(label_x + text_w + 2 * pad, image.width - 1),
                min(label_y + text_h + 2 * pad, image.height - 1),
            ],
            fill=(0, 0, 0),
        )
        draw.text((label_x + pad, label_y + pad), label, fill=(255, 230, 0), font=font)


def _scope_refs(actor: "SessionActor", current_doc: str | None) -> list[str]:
    if not actor.last_tree or (current_doc and actor.last_doc_id != current_doc):
        return []
    return sorted(flatten_refs(actor.last_tree).keys(), key=ref_order)


def capture_screenshot(
    actor: "SessionActor",
    settings: "Settings",
    ref: str | None = None,
    full_page: bool = False,
    annotate: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    backend = actor.backend
    ref = normalize_ref(ref) if ref is not None else None
    if ref is not None:
        current = backend.doc_id()
        if actor.last_doc_id and current != actor.last_doc_id:
            raise ToolError(
                "stale_ref",
                "页面已变化：ref 属于旧文档",
                hint="重新调用 snapshot 后使用新的 ref",
                details={"doc_id": current, "expected_doc_id": actor.last_doc_id},
            )
        scroll = backend.scroll_ref_into_view(ref)
        if not scroll.get("found"):
            raise ToolError(
                "stale_ref",
                "元素已不存在于当前页面",
                hint="重新调用 snapshot 获取最新 ref",
                details={"ref": ref},
            )
        probe = backend.probe_ref(ref)
        if not probe.get("found"):
            raise ToolError(
                "stale_ref",
                "元素已不存在于当前页面",
                hint="重新调用 snapshot 获取最新 ref",
                details={"ref": ref},
            )
        if not probe.get("visible"):
            raise ToolError(
                "not_actionable",
                "元素不可见，无法截图",
                details={"ref": ref, "reason": "offscreen"},
            )

    scope = "element" if ref else ("full_page" if full_page else "viewport")
    need_full = bool(full_page or ref)
    png = backend.screenshot_png(full_page=need_full)
    try:
        image = Image.open(io.BytesIO(png))
        image.load()
    except Exception as exc:
        raise ToolError(
            "screenshot_failed",
            f"截图数据无法解析：{type(exc).__name__}",
        ) from exc
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise ToolError(
            "screenshot_failed",
            "页面过大，截图超过像素上限",
            details={"width": image.width, "height": image.height},
        )
    image = image.convert("RGB")

    current_doc = backend.doc_id()
    refs = _scope_refs(actor, current_doc)
    metrics = backend.collect_ref_rects(refs) if refs else {}
    inner_width = float(metrics.get("inner_width") or image.width)
    inner_height = float(metrics.get("inner_height") or image.height)
    scroll_width = float(metrics.get("scroll_width") or inner_width)
    scroll_height = float(metrics.get("scroll_height") or inner_height)

    if need_full:
        scale_x = image.width / max(scroll_width, 1.0)
        scale_y = image.height / max(scroll_height, 1.0)
    else:
        scale_x = image.width / max(inner_width, 1.0)
        scale_y = image.height / max(inner_height, 1.0)

    rects = list(metrics.get("refs") or [])
    offset_x = float(metrics.get("scroll_x") or 0.0) if need_full else 0.0
    offset_y = float(metrics.get("scroll_y") or 0.0) if need_full else 0.0
    if annotate and rects and actor.last_doc_id == current_doc:
        _draw_annotation(
            image,
            rects,
            scale_x=scale_x,
            scale_y=scale_y,
            offset_x=offset_x,
            offset_y=offset_y,
        )

    if ref is not None:
        target = next((item for item in rects if item.get("ref") == ref), None)
        if target is None:
            raise ToolError(
                "screenshot_failed",
                "无法计算元素截图区域",
                details={"ref": ref},
            )
        left = int(round((float(target["x"]) + float(metrics.get("scroll_x") or 0))
                         * scale_x))
        top = int(round((float(target["y"]) + float(metrics.get("scroll_y") or 0))
                        * scale_y))
        right = int(round(left + float(target["width"]) * scale_x))
        bottom = int(round(top + float(target["height"]) * scale_y))
        left = max(0, min(left, image.width - 1))
        top = max(0, min(top, image.height - 1))
        right = max(left + 1, min(right, image.width))
        bottom = max(top + 1, min(bottom, image.height))
        image = image.crop((left, top, right, bottom))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target_dir = Path(settings.artifact_dir) / actor.name
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"screenshot-{stamp}.png"
    path.write_bytes(data)
    try:
        current_url = backend.current_url
    except Exception:
        current_url = actor.last_url

    meta = {
        "ok": True,
        "session": actor.name,
        "scope": scope,
        "ref": ref,
        "annotated": bool(annotate),
        "full_page": bool(need_full),
        "width": image.width,
        "height": image.height,
        "bytes": len(data),
        "path": str(path.resolve()),
        "doc_id": current_doc,
        "url": current_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": 0,
    }
    return data, meta
