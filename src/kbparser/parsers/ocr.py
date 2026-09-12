"""OCR helper for scanned PDF pages.

Runtime-gated: tesseract presence detected at call time. Missing binary is a
soft failure (warning, no crash) so text-bearing pages still parse cleanly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..runtime_tools import TESSERACT, find_runnable_tool, find_tessdata_dir


class OCRTimeout(RuntimeError):
    pass


class OCREngineError(RuntimeError):
    pass


@dataclass
class OCRResult:
    text: str
    bbox: tuple[float, float, float, float]


def find_tesseract() -> str | None:
    found = find_runnable_tool(TESSERACT)
    return str(found) if found else None


def _image_to_data(pytesseract, img, *, lang: str, timeout_seconds: int):
    try:
        return pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            lang=lang,
            timeout=timeout_seconds,
        )
    except pytesseract.TesseractError:
        if lang != "eng":
            return pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
                timeout=timeout_seconds,
            )
        raise


def ocr_page(
    fitz_page,
    tesseract_bin: str,
    dpi: int = 300,
    lang: str = "eng",
    timeout_seconds: int = 20,
) -> list[OCRResult]:
    """Render a pymupdf page, run Tesseract, return per-line results."""
    import io

    import fitz
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = tesseract_bin
    old_tessdata = os.environ.get("TESSDATA_PREFIX")
    tessdata = find_tessdata_dir(Path(tesseract_bin))
    if tessdata is not None and old_tessdata is None:
        os.environ["TESSDATA_PREFIX"] = str(tessdata)

    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = fitz_page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        try:
            data = _image_to_data(pytesseract, img, lang=lang, timeout_seconds=timeout_seconds)
        except RuntimeError as exc:
            message = str(exc)
            lowered = message.lower()
            if "time" in lowered and "out" in lowered:
                raise OCRTimeout(message) from exc
            raise OCREngineError(message) from exc
        except pytesseract.TesseractError as exc:
            raise OCREngineError(str(exc)) from exc
    finally:
        if tessdata is not None and old_tessdata is None:
            os.environ.pop("TESSDATA_PREFIX", None)

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
        results.append(OCRResult(
            text=" ".join(info["words"]),
            bbox=(info["x0"], info["y0"], info["x1"], info["y1"]),
        ))
    return results
