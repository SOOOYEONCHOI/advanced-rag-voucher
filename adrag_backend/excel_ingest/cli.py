"""사용법: python -m excel_ingest.cli <xlsx> --instance-dir <backend>/instance [--doc-key KEY] [--model NEOCON C2]"""
import argparse
import os

from .export_md import export_markdown
from .parser import parse_workbook


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--instance-dir", required=True)
    ap.add_argument("--doc-key")
    ap.add_argument("--model")
    ap.add_argument("--run-id")
    a = ap.parse_args()
    key = a.doc_key or os.path.splitext(os.path.basename(a.xlsx))[0]
    res = parse_workbook(a.xlsx, key, a.model)
    out = export_markdown(res, a.instance_dir, a.run_id, os.path.basename(a.xlsx))
    print(out)


if __name__ == "__main__":
    main()
