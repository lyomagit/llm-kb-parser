"""OCR helper for scanned PDF pages.

Runtime-gated: tesseract presence detected at call time. Missing binary is a
soft failure (warning, no crash) so text-bearing pages still parse cleanly.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

TESSERACT_CANDIDATES = (
    "tesseract",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
)


@dataclass
class OCRResult:
    text: str
    bbox: tuple[float, float, float, float]


def find_tesseract() -> str | None:
    for cand in TESSERACT_CANDIDATES:
        resolved = shutil.which(cand)
        if resolved:
            return resolved
        p = Path(cand)
        if p.is_file():
            return str(p)
    return None


def ocr_page(
    fitz_page, tesseract_bin: str, dpi: int = 300, lang: str = "eng",
) -> list[OCRResult]:
    """Render a pymupdf page, run Tesseract, return per-line results.

    `lang` accepts Tesseract's language codes, optionally joined by '+'
    (e.g. 'rus+eng'). Unavailable traineddata falls back to 'eng'.
    """
    import fitz
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = tesseract_bin

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = fitz_page.get_pixmap(matrix=matrix, alpha=False)
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    try:
        data = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT, lang=lang,
        )
    except pytesseract.TesseractError:
        # Fall back to English if requested language pack is missing.
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], dict] = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x = data["left"][i] / zoom
        y = data["top"][i] / zoom
        w = data["width"][i] / zoom
        h = data["height"][i] / zoom
        entry = lines.setdefault(key, {
            "words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h,
        })
        entry["words"].append(text)
        entry["x0"] = min(entry["x0"], x)
        entry["y0"] = min(entry["y0"], y)
        entry["x1"] = max(entry["x1"], x + w)
        entry["y1"] = max(entry["y1"], y + h)

    results: list[OCRResult] = []
    for _, info in sorted(lines.items()):
        txt = " ".join(info["words"])
        results.append(OCRResult(
            text=txt,
            bbox=(info["x0"], info["y0"], info["x1"], info["y1"]),
        ))
    return results
