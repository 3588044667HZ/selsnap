from PIL import Image

from selsnap.screenshots import _draw_annotation


def test_draw_annotation_marks_image():
    image = Image.new("RGB", (200, 100), (255, 255, 255))
    _draw_annotation(
        image,
        [{"ref": "e1", "x": 10, "y": 10, "width": 60, "height": 40}],
        scale_x=1.0,
        scale_y=1.0,
        offset_x=0.0,
        offset_y=0.0,
    )
    colors = image.getcolors(maxcolors=100000)
    assert colors is not None
    assert any(color != (255, 255, 255) for _, color in colors)


def test_draw_annotation_scales_and_offsets():
    image = Image.new("RGB", (400, 200), (255, 255, 255))
    _draw_annotation(
        image,
        [{"ref": "e2", "x": 10, "y": 10, "width": 20, "height": 10}],
        scale_x=2.0,
        scale_y=2.0,
        offset_x=100.0,
        offset_y=50.0,
    )
    # 矩形左边 (10+100)*2 = 220，顶边 (10+50)*2 = 120
    assert image.getpixel((221, 121)) != (255, 255, 255)


def test_draw_annotation_skips_tiny_or_offscreen():
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    _draw_annotation(
        image,
        [
            {"ref": "e1", "x": 0, "y": 0, "width": 1, "height": 1},
            {"ref": "e2", "x": 999, "y": 999, "width": 10, "height": 10},
        ],
        scale_x=1.0,
        scale_y=1.0,
        offset_x=0.0,
        offset_y=0.0,
    )
    assert image.getcolors(maxcolors=100000) == [(100 * 100, (255, 255, 255))]
