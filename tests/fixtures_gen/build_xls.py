"""Generate deterministic XLS (legacy binary) fixture via xlwt."""
from __future__ import annotations

from pathlib import Path

import xlwt


def build_basic(path: Path) -> Path:
    wb = xlwt.Workbook()

    s1 = wb.add_sheet("Sales")
    s1.write_merge(0, 0, 0, 3, "Q1 Sales Report")  # A1:D1 merged title
    for ci, h in enumerate(["Product", "Units", "Price", "Total"]):
        s1.write(1, ci, h)
    data = [
        ("Apple", 10, 1.5, 15.0),
        ("Pear", 5, 2.0, 10.0),
        ("Plum", 7, 0.8, 5.6),
    ]
    for ri, (prod, units, price, total) in enumerate(data, start=2):
        s1.write(ri, 0, prod)
        s1.write(ri, 1, units)
        s1.write(ri, 2, price)
        s1.write(ri, 3, total)
    s1.write(6, 0, "Note: preliminary figures.")

    s2 = wb.add_sheet("Summary")
    s2.write(0, 0, "Metric")
    s2.write(0, 1, "Value")
    s2.write(1, 0, "Total Units")
    s2.write(1, 1, 22)
    s2.write(2, 0, "Total Revenue")
    s2.write(2, 1, 30.6)

    s3 = wb.add_sheet("Archive")
    s3.write(0, 0, "legacy")
    s3.visibility = 1  # hidden

    # Sheet 4: exercise date/bool/error types.
    s4 = wb.add_sheet("Types")
    s4.write(0, 0, "When")
    s4.write(0, 1, "Flag")
    s4.write(0, 2, "Count")
    import datetime as _dt
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    s4.write(1, 0, _dt.datetime(2026, 4, 13), date_style)
    s4.write(1, 1, True)
    s4.write(1, 2, 42)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixtures/xls/basic.xls")
    print(build_basic(out))
