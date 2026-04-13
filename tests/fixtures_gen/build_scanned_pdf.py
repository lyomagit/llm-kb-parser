"""Generate a deterministic 'scanned' PDF fixture.

Strategy: rasterize plain text into a PNG via PIL, embed that image in a PDF
with reportlab. The PDF has *no text layer* — it forces the parser down the
OCR path.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


_TEXT_LINES = [
    "Scanned Document Test",
    "",
    "This PDF has no text layer.",
    "It contains only a rasterized image of text.",
    "The parser should invoke Tesseract OCR to recover the content.",
]


def _render_text_png(path: Path, dpi: int = 150) -> Path:
    width, height = int(8.5 * dpi), int(11 * dpi)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    y = 200
    for line in _TEXT_LINES:
        draw.text((150, y), line, fill="black", font=font)
        y += 60
    img.save(path, "PNG")
    return path


def build_basic(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    png_path = path.with_suffix(".png")
    _render_text_png(png_path)

    c = canvas.Canvas(str(path), pagesize=LETTER)
    w, h = LETTER
    c.drawImage(ImageReader(str(png_path)), 0, 0, width=w, height=h, preserveAspectRatio=True)
    c.setTitle("Scanned Document Test")
    c.setAuthor("kbparser-fixture")
    c.showPage()
    c.save()
    png_path.unlink(missing_ok=True)
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/pdf/scanned.pdf")
    print(build_basic(out))
