"""Numbered-grid stitcher for the board plugin (PIL only).

Port of the root ``stich.py`` script, absorbed into the plugin: images are
resized to fit uniform cells (aspect preserved, no clipping), each cell
carries its grid number above it, and the result is saved as
PNG/JPEG/WebP. The script's draft bugs are fixed here — the duplicated
``resize_to_fit`` is gone, ``os`` is imported at module level, and the
font lookup tries real Linux font paths before falling back to PIL's
default font.
"""

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cazzubot.errors import UserInputError

# Linux font paths — there is no arial.ttf outside Windows.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]


class ImageGridStitcher:
    """Stitch images into a numbered grid, one label per cell."""

    def __init__(
        self,
        *,
        label_font_size: int = 64,
        background_color: str = "#1A1A1E",
        label_color: str = "white",
        padding: int = 16,
    ) -> None:
        self.label_font_size = label_font_size
        self.background_color = background_color
        self.label_color = label_color
        self.padding = padding
        self.font = self._load_font()

    def _load_font(
        self,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for path in _FONT_CANDIDATES:
            if os.path.exists(path):
                return ImageFont.truetype(path, self.label_font_size)
        try:
            return ImageFont.load_default(size=self.label_font_size)
        except TypeError:  # Pillow < 10.1 has no size parameter
            return ImageFont.load_default()

    def _resize_to_fit(
        self, image: Image.Image, target_width: int, target_height: int
    ) -> Image.Image:
        """Fit within the target box, centered on a background canvas."""
        img_width, img_height = image.size
        scale = min(target_width / img_width, target_height / img_height)
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        resized = image.resize(  # pyright: ignore[reportUnknownMemberType] PIL stubs
            (new_width, new_height), Image.Resampling.LANCZOS
        )
        canvas = Image.new(
            "RGB", (target_width, target_height), self.background_color
        )
        x_offset = (target_width - new_width) // 2
        y_offset = (target_height - new_height) // 2
        canvas.paste(resized, (x_offset, y_offset))
        return canvas

    def stitch(
        self,
        image_paths: list[str | Path],
        output_path: str | Path,
        *,
        images_per_row: int = 9,
        target_size: tuple[int, int] = (768, 768),
        compression: str = "webp",
        quality: int = 85,
        grid_border_width: int = 8,
        grid_border_color: str = "gray",
    ) -> Image.Image:
        """Stitch images into a numbered grid and save it.

        Images are resized to fit their cell (aspect preserved, no
        clipping); unreadable files are skipped. Raises
        ``UserInputError`` when nothing can be stitched.
        """
        cell_width, cell_height = target_size
        label_height = self.label_font_size + self.padding * 2

        images: list[Image.Image] = []
        for path in image_paths:
            try:
                images.append(Image.open(path).convert("RGB"))
            except Exception:
                # any read failure (corrupt/truncated/unsupported) skips
                # the file; the caller reports how many were skipped
                continue
        if not images:
            raise UserInputError("no readable images to stitch")

        total = len(images)
        rows = math.ceil(total / images_per_row)
        cols = min(images_per_row, total)
        grid_width = (cols * cell_width) + ((cols - 1) * grid_border_width)
        grid_height = (rows * (cell_height + label_height)) + (
            (rows - 1) * grid_border_width
        )

        canvas = Image.new(
            "RGB", (grid_width, grid_height), self.background_color
        )
        draw = ImageDraw.Draw(canvas)

        for idx, img in enumerate(images):
            row = idx // images_per_row
            col = idx % images_per_row
            x = col * (cell_width + grid_border_width)
            y = (
                row * (cell_height + label_height + grid_border_width)
                + label_height
            )
            fitted = self._resize_to_fit(img, cell_width, cell_height)
            canvas.paste(fitted, (x, y))
            self._draw_label(
                draw, idx + 1, x, y - label_height, cell_width
            )

        if grid_border_width > 0:
            for col in range(1, cols):
                line_x = col * (cell_width + grid_border_width) - (
                    grid_border_width // 2
                )
                draw.line(
                    [(line_x, 0), (line_x, grid_height)],
                    fill=grid_border_color,
                    width=grid_border_width,
                )
            for row in range(1, rows):
                line_y = row * (
                    cell_height + label_height + grid_border_width
                ) - (grid_border_width // 2)
                draw.line(
                    [(0, line_y), (grid_width, line_y)],
                    fill=grid_border_color,
                    width=grid_border_width,
                )

        self._save(canvas, output_path, compression, quality)
        return canvas

    def _save(
        self,
        canvas: Image.Image,
        output_path: str | Path,
        compression: str,
        quality: int,
    ) -> None:
        fmt = compression.lower()
        if fmt == "png":
            canvas.save(
                output_path, "PNG", optimize=True, compress_level=9
            )
        elif fmt in ("jpg", "jpeg"):
            canvas.save(
                output_path,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
        elif fmt == "webp":
            canvas.save(
                output_path,
                "WEBP",
                quality=quality,
                method=6,
                lossless=False,
            )
        else:
            canvas.save(output_path)

    def _draw_label(
        self,
        draw: ImageDraw.ImageDraw,
        number: int,
        img_x: int,
        label_y: int,
        img_width: int,
    ) -> None:
        """Draw the centered grid number above a cell."""
        text = str(number)
        bbox = draw.textbbox((0, 0), text, font=self.font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = img_x + (img_width - text_width) // 2
        text_y = (
            label_y
            + (self.label_font_size - text_height) // 2
            + self.padding
        )
        draw.text(
            (text_x, text_y), text, font=self.font, fill=self.label_color
        )
