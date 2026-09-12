"""Generate deterministic PDF fixture via reportlab.

Fixture shape (US Letter, 2 pages):
- Running header "Confidential" on every page (y near top)
- Running footer "Page N" on every page (y near bottom)
- Title "PDF Test Report" (24pt)
- H1 "Overview" (18pt) + 2 body paragraphs (11pt)
- H1 "Methods" (18pt) + 1 body paragraph
- H1 "Results" (18pt) + 3x3 ruled table + 1 body paragraph

Changing this breaks golden tests.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    TableStyle,
)
from reportlab.platypus import (
    Table as RLTable,
)

BODY = ParagraphStyle(
    name="body", fontName="Helvetica", fontSize=11, leading=14, spaceAfter=6,
)
H1 = ParagraphStyle(
    name="h1", fontName="Helvetica-Bold", fontSize=18, leading=22, spaceBefore=12, spaceAfter=8,
)
TITLE = ParagraphStyle(
    name="title", fontName="Helvetica-Bold", fontSize=24, leading=28, spaceAfter=14,
)


def _header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.drawString(0.75 * inch, 10.5 * inch, "Confidential")
    canvas.drawCentredString(4.25 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_basic(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=1.0 * inch,
        bottomMargin=1.0 * inch,
        title="PDF Test Report",
        author="kbparser-fixture",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_header_footer)])

    story = []
    story.append(Paragraph("PDF Test Report", TITLE))

    story.append(Paragraph("Overview", H1))
    story.append(Paragraph(
        "This document is a deterministic fixture used to validate the PDF parser. "
        "It exercises section headings, body paragraphs, and ruled tables.", BODY))
    story.append(Paragraph(
        "It also exercises running headers and footers which should be filtered "
        "out of the body blocks by the parser heuristic.", BODY))

    story.append(Paragraph("Methods", H1))
    story.append(Paragraph(
        "The parser extracts font sizes per span and infers heading levels "
        "by comparing against the dominant body font size.", BODY))

    story.append(PageBreak())
    story.append(Paragraph("Results", H1))
    data = [
        ["Metric", "Before", "After"],
        ["Precision", "0.72", "0.91"],
        ["Recall", "0.65", "0.88"],
    ]
    tbl = RLTable(data, colWidths=[1.8 * inch, 1.4 * inch, 1.4 * inch])
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "The precision and recall numbers above demonstrate the improvement "
        "delivered by the second iteration of the system.", BODY))

    doc.build(story)
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/pdf/basic.pdf")
    print(build_basic(out))
