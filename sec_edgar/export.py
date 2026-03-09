"""
Export XBRL facts to CSV or JSON.
"""

from __future__ import annotations

import csv
import json
import sys
from typing import TextIO

from . import db


EXPORT_COLUMNS = [
    "ticker", "name", "taxonomy", "concept", "label",
    "unit", "period_type", "period_start", "period_end",
    "value", "value_text", "fiscal_year", "fiscal_period",
    "form", "filed_date", "frame", "accession_no",
]


def export_facts(
    conn,
    tickers: list[str],
    concepts: list[str] | None,
    form_types: list[str],
    fmt: str,
    output_path: str,
) -> int:
    """
    Query and write facts to output. Returns number of rows written.
    output_path="-" writes to stdout.
    """
    rows = db.query_facts(conn, tickers, concepts, form_types)

    out: TextIO
    if output_path == "-":
        out = sys.stdout
        should_close = False
    else:
        out = open(output_path, "w", newline="", encoding="utf-8")
        should_close = True

    try:
        if fmt == "csv":
            _write_csv(rows, out)
        else:
            _write_json(rows, out)
    finally:
        if should_close:
            out.close()

    return len(rows)


def _write_csv(rows: list[dict], out: TextIO) -> None:
    if not rows:
        writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        return
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def _write_json(rows: list[dict], out: TextIO) -> None:
    # Convert None to null naturally via json.dump
    json.dump(rows, out, indent=2, default=str)
    out.write("\n")
