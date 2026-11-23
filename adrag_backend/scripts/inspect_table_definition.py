from __future__ import annotations

import sys
from pathlib import Path

import openpyxl


def main() -> None:
    path = Path(sys.argv[1])
    workbook = openpyxl.load_workbook(path, data_only=False)
    print(workbook.sheetnames)
    specs = sys.argv[2:] or workbook.sheetnames
    for spec in specs:
        parts = spec.rsplit(":", 2)
        sheet_name = parts[0]
        start = int(parts[1]) if len(parts) >= 2 else 1
        end = int(parts[2]) if len(parts) >= 3 else workbook[sheet_name].max_row
        sheet = workbook[sheet_name]
        print(f"\n### {sheet_name} ({sheet.max_row}x{sheet.max_column})")
        merged = [str(cell_range) for cell_range in sheet.merged_cells.ranges]
        if merged:
            print("MERGED", merged)
        print("FREEZE", sheet.freeze_panes, "FILTER", sheet.auto_filter.ref)
        for row in sheet.iter_rows(min_row=start, max_row=end):
            values = [cell.value for cell in row]
            if any(value is not None for value in values):
                print(row[0].row, repr(values))


if __name__ == "__main__":
    main()
