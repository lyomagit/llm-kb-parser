"""Generate deterministic DOCX fixtures for tests.

Keep content stable — changing it breaks golden assertions.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document as _DocxDocument


def build_basic(path: Path) -> Path:
    """Fixture: 2 H1 sections (one with H2 subsection), paragraphs, list, table."""
    d = _DocxDocument()

    d.add_heading("Introduction", level=1)
    d.add_paragraph("This is the intro paragraph about the topic.")
    d.add_paragraph("A second intro paragraph with more detail.")

    d.add_heading("Methods", level=1)
    d.add_paragraph("We used the following approaches:")
    d.add_paragraph("Step one described here.", style="List Bullet")
    d.add_paragraph("Step two described here.", style="List Bullet")
    d.add_paragraph("Step three described here.", style="List Bullet")

    d.add_heading("Materials", level=2)
    d.add_paragraph("Materials paragraph under Methods.")

    t = d.add_table(rows=3, cols=3)
    t.rows[0].cells[0].text = "Item"
    t.rows[0].cells[1].text = "Qty"
    t.rows[0].cells[2].text = "Price"
    t.rows[1].cells[0].text = "Apple"
    t.rows[1].cells[1].text = "2"
    t.rows[1].cells[2].text = "1.50"
    t.rows[2].cells[0].text = "Pear"
    t.rows[2].cells[1].text = "5"
    t.rows[2].cells[2].text = "0.80"

    d.add_heading("Conclusion", level=1)
    d.add_paragraph("Final thoughts paragraph.")

    # Second table exercises merged cells: merged title row (horizontal)
    # and a merged left column (vertical).
    t2 = d.add_table(rows=4, cols=3)
    # Horizontal merge across first row.
    merged_title = t2.rows[0].cells[0].merge(t2.rows[0].cells[1]).merge(t2.rows[0].cells[2])
    merged_title.text = "Merged Title"
    # Column headers.
    t2.rows[1].cells[0].text = "Group"
    t2.rows[1].cells[1].text = "Metric"
    t2.rows[1].cells[2].text = "Value"
    # Vertical merge of "A" group across rows 2 and 3.
    group_cell = t2.rows[2].cells[0].merge(t2.rows[3].cells[0])
    group_cell.text = "A"
    t2.rows[2].cells[1].text = "m1"
    t2.rows[2].cells[2].text = "1"
    t2.rows[3].cells[1].text = "m2"
    t2.rows[3].cells[2].text = "2"

    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/docx/basic.docx")
    print(build_basic(out))
