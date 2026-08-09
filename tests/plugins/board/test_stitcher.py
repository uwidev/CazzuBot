"""Board plugin — grid stitcher tests: geometry, labels, robustness."""

from pathlib import Path

import pytest
from PIL import Image

from cazzubot.errors import UserInputError
from plugins.board.stitcher import ImageGridStitcher


def _image(
    path: Path,
    size: tuple[int, int] = (100, 80),
    color: tuple[int, int, int] = (200, 30, 30),
) -> None:
    Image.new("RGB", size, color).save(path, "PNG")


def _stitcher(**kwargs) -> ImageGridStitcher:
    return ImageGridStitcher(label_font_size=30, padding=8, **kwargs)


def test_single_row_geometry(tmp_path: Path) -> None:
    a = tmp_path / "1-a.png"
    b = tmp_path / "2-b.png"
    _image(a, (100, 80))
    _image(b, (200, 120))
    out = tmp_path / "grid.webp"

    canvas = _stitcher().stitch(
        [str(a), str(b)],
        str(out),
        images_per_row=3,
        target_size=(100, 100),
        grid_border_width=4,
    )

    label_height = 30 + 8 * 2
    assert canvas.size == (2 * 100 + 1 * 4, 100 + label_height)
    assert out.exists()
    with Image.open(out) as reopened:
        assert reopened.format == "WEBP"
        assert reopened.size == canvas.size


def test_two_rows_geometry(tmp_path: Path) -> None:
    paths = []
    for i in range(4):
        p = tmp_path / f"{i + 1}-a.png"
        _image(p, (100, 80))
        paths.append(str(p))
    out = tmp_path / "grid.webp"

    canvas = _stitcher().stitch(
        paths,
        str(out),
        images_per_row=3,
        target_size=(100, 100),
        grid_border_width=4,
    )

    label_height = 30 + 8 * 2
    assert canvas.size == (3 * 100 + 2 * 4, 2 * (100 + label_height) + 4)


def test_cell_fit_preserves_aspect_and_letterboxes(tmp_path: Path) -> None:
    a = tmp_path / "wide.png"
    _image(a, (200, 100), color=(200, 30, 30))  # 2:1 into a 1:1 cell
    out = tmp_path / "grid.webp"

    canvas = _stitcher(background_color="black").stitch(
        [str(a)],
        str(out),
        images_per_row=1,
        target_size=(100, 100),
        grid_border_width=0,
    )

    assert canvas.getpixel((0, 50)) == (0, 0, 0)  # letterboxed edge
    # image center: cell starts at label_height, image is centered in it
    label_height = 30 + 8 * 2
    assert canvas.getpixel((50, label_height + 50)) == (200, 30, 30)


def test_skips_unreadable_files(tmp_path: Path) -> None:
    junk = tmp_path / "1-junk.png"
    good = tmp_path / "2-good.png"
    junk.write_bytes(b"not an image")
    _image(good)
    out = tmp_path / "grid.webp"

    canvas = _stitcher().stitch(
        [str(junk), str(good)],
        str(out),
        images_per_row=2,
        target_size=(100, 100),
    )

    label_height = 30 + 8 * 2
    assert canvas.size == (100, 100 + label_height)


def test_nothing_stitchable_raises(tmp_path: Path) -> None:
    junk = tmp_path / "1-junk.png"
    junk.write_bytes(b"not an image")
    out = tmp_path / "grid.webp"

    with pytest.raises(UserInputError, match="no readable images"):
        _stitcher().stitch(
            [str(junk)], str(out), images_per_row=2, target_size=(100, 100)
        )
    assert not out.exists()
