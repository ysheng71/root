"""
Build and format standardized financial statements.

Uses metric_mappings in the DB to resolve XBRL facts to standardized metrics.
Supports annual (FY) and quarterly (Q1-Q4) granularity, multiple output formats.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .metrics import (
    STATEMENT_METRICS,
    STATEMENT_TITLES,
    ALL_METRICS,
    MetricDef,
    get_metric,
)

SCALE_LABELS = {
    1: "USD",
    1_000: "USD in Thousands",
    1_000_000: "USD in Millions",
    1_000_000_000: "USD in Billions",
}

# Section display names for headers
SECTION_HEADERS = {
    # Income Statement
    "revenue": None,          # no explicit header, first section
    "opex": "Operating Expenses",
    "operating": None,
    "below_line": "Non-Operating",
    "bottom_line": None,
    "supplemental": "Supplemental",
    "per_share": "Per Share",
    # Balance Sheet
    "current_assets": "Current Assets",
    "noncurrent_assets": "Non-Current Assets",
    "current_liabilities": "Current Liabilities",
    "noncurrent_liabilities": "Non-Current Liabilities",
    "equity": "Shareholders' Equity",
    # Cash Flow
    "operating": "Operating Activities",
    "investing": "Investing Activities",
    "financing": "Financing Activities",
    "summary": "Summary",
}


@dataclass
class ReportRow:
    metric: MetricDef
    values: Dict[str, Optional[float]]  # period_label -> raw value (unscaled)
    is_section_header: bool = False
    section_label: str = ""


@dataclass
class Report:
    company_name: str
    ticker: str
    statement: str          # income_statement | balance_sheet | cash_flow
    statement_title: str
    period: str             # annual | quarterly
    periods: List[str]      # ordered period labels, oldest→newest
    rows: List[ReportRow]
    scale: int              # USD divisor (1, 1000, 1_000_000, etc.)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_facts(
    conn: sqlite3.Connection,
    cik: str,
    statement: str,
    period: str,
    num_periods: int,
) -> Dict[Tuple[str, str], Optional[float]]:
    """
    Returns {(metric_name, period_label): best_value} for non-derived metrics.

    Uses ROW_NUMBER() to select: lowest concept priority first, then most
    recently filed version (handles restatements).
    """
    if period == "annual":
        form_values = "('10-K', '10-K/A')"
        period_values = "('FY')"
        year_limit = num_periods + 3
        period_key_expr = "printf('FY%d', f.fiscal_year)"
        sort_col = "fiscal_year"
    else:
        form_values = "('10-Q', '10-Q/A')"
        period_values = "('Q1', 'Q2', 'Q3', 'Q4')"
        year_limit = (num_periods // 4) + 3
        period_key_expr = "printf('%d %s', f.fiscal_year, f.fiscal_period)"
        sort_col = "period_end"

    sql = f"""
        WITH min_year AS (
            SELECT MAX(fiscal_year) - {year_limit} AS cutoff
            FROM xbrl_facts
            WHERE cik = :cik
              AND form IN {form_values}
        ),
        ranked AS (
            SELECT
                mm.metric_name,
                mm.priority    AS concept_priority,
                {period_key_expr} AS period_label,
                f.fiscal_year,
                f.fiscal_period,
                f.period_end,
                f.value,
                f.filed_date,
                ROW_NUMBER() OVER (
                    PARTITION BY mm.metric_name, f.fiscal_year, f.fiscal_period
                    ORDER BY mm.priority ASC, f.filed_date DESC
                ) AS rn
            FROM xbrl_facts f
            JOIN metric_mappings mm
                ON  mm.concept   = f.concept
                AND mm.taxonomy  = f.taxonomy
                AND mm.statement = :statement
                AND f.unit       = mm.unit
            CROSS JOIN min_year
            WHERE f.cik = :cik
              AND f.form IN {form_values}
              AND f.fiscal_period IN {period_values}
              AND f.fiscal_year >= min_year.cutoff
              AND f.value IS NOT NULL
        )
        SELECT metric_name, period_label, fiscal_year, fiscal_period,
               period_end, value
        FROM ranked
        WHERE rn = 1
        ORDER BY metric_name, {sort_col}
    """
    cursor = conn.execute(sql, {
        "cik": cik,
        "statement": statement,
    })

    result: Dict[Tuple[str, str], Optional[float]] = {}
    for row in cursor.fetchall():
        key = (row["metric_name"], row["period_label"])
        result[key] = row["value"]

    return result


def _ordered_periods(
    facts: Dict[Tuple[str, str], Optional[float]],
    period: str,
    num_periods: int,
) -> List[str]:
    """Extract sorted period labels from facts, capped at num_periods (most recent)."""
    all_periods = sorted({p for (_, p) in facts.keys()}, key=_period_sort_key)
    return all_periods[-num_periods:]  # keep most recent N


def _period_sort_key(label: str) -> Tuple:
    """Sort key for period labels: 'FY2023' or '2023 Q1'."""
    if label.startswith("FY"):
        return (int(label[2:]), 0)
    parts = label.split()
    if len(parts) == 2:
        year = int(parts[0])
        q = int(parts[1][1])
        return (year, q)
    return (0, 0)


def _compute_derived(
    metric: MetricDef,
    periods: List[str],
    values: Dict[Tuple[str, str], Optional[float]],
) -> Dict[str, Optional[float]]:
    """Evaluate derived_expr for each period."""
    result: Dict[str, Optional[float]] = {}
    for p in periods:
        try:
            # Build a namespace of {metric_name: value} for this period
            ns: Dict[str, float] = {}
            for m in ALL_METRICS:
                v = values.get((m.name, p))
                ns[m.name] = v if v is not None else float("nan")
            val = eval(metric.derived_expr, {"__builtins__": {}}, ns)  # noqa: S307
            import math
            result[p] = None if (math.isnan(val) or math.isinf(val)) else val
        except Exception:
            result[p] = None
    return result


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(
    conn: sqlite3.Connection,
    cik: str,
    ticker: str,
    company_name: str,
    statement: str,
    period: str,
    num_periods: int,
    scale: int = 1_000_000,
) -> Report:
    metrics = STATEMENT_METRICS[statement]

    # Fetch raw facts
    facts = _fetch_facts(conn, cik, statement, period, num_periods)

    # Determine periods present in data
    periods = _ordered_periods(facts, period, num_periods)

    # Compute derived metrics and merge into facts dict
    for m in metrics:
        if m.is_derived and m.derived_expr:
            derived_vals = _compute_derived(m, periods, facts)
            for p, v in derived_vals.items():
                facts[(m.name, p)] = v

    # Build rows with section headers
    rows: List[ReportRow] = []
    prev_section = None
    for m in metrics:
        if m.section != prev_section:
            hdr = SECTION_HEADERS.get(m.section)
            if hdr:
                rows.append(ReportRow(
                    metric=m,
                    values={},
                    is_section_header=True,
                    section_label=hdr,
                ))
            prev_section = m.section

        row_values = {p: facts.get((m.name, p)) for p in periods}
        rows.append(ReportRow(metric=m, values=row_values))

    return Report(
        company_name=company_name,
        ticker=ticker,
        statement=statement,
        statement_title=STATEMENT_TITLES[statement],
        period=period,
        periods=periods,
        rows=rows,
        scale=scale,
    )


def _get_company(conn: sqlite3.Connection, ticker: str) -> Optional[dict]:
    cursor = conn.execute(
        "SELECT cik, ticker, name FROM companies WHERE ticker = ?",
        (ticker.upper(),),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def build_reports(
    conn: sqlite3.Connection,
    ticker: str,
    statements: List[str],
    period: str,
    num_periods: int,
    scale: int = 1_000_000,
) -> List[Report]:
    company = _get_company(conn, ticker)
    if not company:
        raise ValueError(f"Ticker '{ticker}' not found in database. Run 'fetch' first.")

    reports = []
    for stmt in statements:
        r = build_report(
            conn=conn,
            cik=company["cik"],
            ticker=company["ticker"],
            company_name=company["name"],
            statement=stmt,
            period=period,
            num_periods=num_periods,
            scale=scale,
        )
        reports.append(r)
    return reports


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_value(value: Optional[float], unit: str, scale: int) -> str:
    if value is None:
        return "—"
    if unit == "USD":
        scaled = value / scale
        if abs(scaled) >= 1000:
            return f"{scaled:,.0f}"
        return f"{scaled:,.1f}"
    if unit == "shares":
        scaled = value / 1_000_000
        return f"{scaled:,.1f}M"
    if unit == "USD/shares":
        return f"{value:.2f}"
    return f"{value:,.2f}"


def _scale_label(scale: int) -> str:
    return SCALE_LABELS.get(scale, f"÷{scale:,}")


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def format_text(report: Report) -> str:
    LABEL_WIDTH = 42
    COL_WIDTH = 12
    total_width = LABEL_WIDTH + COL_WIDTH * len(report.periods) + 2

    lines: List[str] = []
    sep = "─" * total_width
    thick = "═" * total_width

    # Title block
    lines.append(thick)
    lines.append(
        f"  {report.company_name} ({report.ticker})  —  {report.statement_title}"
    )
    granularity = "Annual" if report.period == "annual" else "Quarterly"
    lines.append(f"  {granularity}  |  {_scale_label(report.scale)}")
    lines.append(thick)

    # Column headers
    header = " " * LABEL_WIDTH
    for p in report.periods:
        header += p.rjust(COL_WIDTH)
    lines.append(header)
    lines.append(sep)

    for row in report.rows:
        if row.is_section_header:
            lines.append("")
            lines.append(f"  {row.section_label.upper()}")
            lines.append(sep)
            continue

        m = row.metric
        prefix = "  " + ("  " if m.indent else "")
        label = prefix + m.display
        label = label[:LABEL_WIDTH]
        label = label.ljust(LABEL_WIDTH)

        vals = ""
        for p in report.periods:
            vals += _fmt_value(row.values.get(p), m.unit, report.scale).rjust(COL_WIDTH)

        # Bold total / header lines (indent=0, not section header) with underline char
        line = label + vals
        lines.append(line)

        # Add blank line after major totals for readability
        if m.indent == 0 and m.section not in ("revenue",):
            lines.append("")

    lines.append(thick)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSV formatter
# ---------------------------------------------------------------------------

def format_csv(report: Report) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header rows
    writer.writerow(["Company", report.company_name])
    writer.writerow(["Ticker", report.ticker])
    writer.writerow(["Statement", report.statement_title])
    writer.writerow(["Period", "Annual" if report.period == "annual" else "Quarterly"])
    writer.writerow(["Scale", _scale_label(report.scale)])
    writer.writerow([])

    col_headers = ["Metric", "Metric ID", "Unit"] + list(report.periods)
    writer.writerow(col_headers)

    for row in report.rows:
        if row.is_section_header:
            writer.writerow([f"--- {row.section_label} ---"])
            continue
        m = row.metric
        raw_vals = [row.values.get(p) for p in report.periods]
        # Scale USD values, keep others raw
        scaled_vals = []
        for v in raw_vals:
            if v is None:
                scaled_vals.append("")
            elif m.unit == "USD":
                scaled_vals.append(round(v / report.scale, 2))
            else:
                scaled_vals.append(v)
        writer.writerow([m.display, m.name, m.unit] + scaled_vals)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Excel formatter
# ---------------------------------------------------------------------------

def write_excel(reports: List[Report], output_path: str) -> None:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError(
            "openpyxl is required for Excel export. "
            "Install with: pip install openpyxl"
        )

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    HEADER_FILL = PatternFill("solid", fgColor="1F3864")
    HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
    SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")
    SECTION_FONT = Font(bold=True, size=9, color="1F3864")
    TOTAL_FONT = Font(bold=True, size=9)
    DETAIL_FONT = Font(size=9)
    TITLE_FONT = Font(bold=True, size=12)
    SUBTITLE_FONT = Font(size=9, italic=True)
    ALT_FILL = PatternFill("solid", fgColor="F5F7FA")
    THIN = Side(style="thin", color="D0D0D0")
    THIN_BORDER = Border(bottom=Side(style="thin", color="CCCCCC"))

    for report in reports:
        sheet_name = report.statement_title[:31]
        ws = wb.create_sheet(title=sheet_name)

        # Sheet title
        ws["A1"] = f"{report.company_name} ({report.ticker})"
        ws["A1"].font = TITLE_FONT
        granularity = "Annual" if report.period == "annual" else "Quarterly"
        ws["A2"] = f"{report.statement_title}  ·  {granularity}  ·  {_scale_label(report.scale)}"
        ws["A2"].font = SUBTITLE_FONT
        ws.append([])  # blank row 3

        # Column headers: row 4
        header_row = ["", "Metric ID", "Unit"] + list(report.periods)
        ws.append(header_row)
        hdr_row_num = ws.max_row
        for col_idx, val in enumerate(header_row, 1):
            cell = ws.cell(row=hdr_row_num, column=col_idx)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(
                horizontal="right" if col_idx > 3 else "left",
                vertical="center",
            )
        ws.freeze_panes = ws.cell(row=hdr_row_num + 1, column=4)

        # Data rows
        data_row_num = hdr_row_num
        alt = False
        for row in report.rows:
            data_row_num += 1
            if row.is_section_header:
                ws.cell(row=data_row_num, column=1, value=row.section_label)
                for c in range(1, 4 + len(report.periods)):
                    cell = ws.cell(row=data_row_num, column=c)
                    cell.fill = SECTION_FILL
                    cell.font = SECTION_FONT
                alt = False
                continue

            m = row.metric
            indent_str = "    " * m.indent
            label_cell = ws.cell(row=data_row_num, column=1, value=indent_str + m.display)
            id_cell = ws.cell(row=data_row_num, column=2, value=m.name)
            unit_cell = ws.cell(row=data_row_num, column=3, value=m.unit)

            row_font = TOTAL_FONT if m.indent == 0 else DETAIL_FONT
            label_cell.font = row_font
            id_cell.font = DETAIL_FONT
            unit_cell.font = DETAIL_FONT

            if alt:
                for c in range(1, 4 + len(report.periods)):
                    ws.cell(row=data_row_num, column=c).fill = ALT_FILL

            for col_offset, p in enumerate(report.periods):
                v = row.values.get(p)
                col_num = 4 + col_offset
                cell = ws.cell(row=data_row_num, column=col_num)
                if v is not None:
                    if m.unit == "USD":
                        cell.value = round(v / report.scale, 2)
                        cell.number_format = '#,##0.0'
                    elif m.unit == "shares":
                        cell.value = round(v / 1_000_000, 2)
                        cell.number_format = '#,##0.0'
                    elif m.unit == "USD/shares":
                        cell.value = round(v, 2)
                        cell.number_format = '0.00'
                    else:
                        cell.value = v
                        cell.number_format = '#,##0.00'
                cell.font = row_font
                cell.alignment = Alignment(horizontal="right")

            alt = not alt

        # Column widths
        ws.column_dimensions["A"].width = 38
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["C"].width = 12
        for col_offset in range(len(report.periods)):
            col_letter = get_column_letter(4 + col_offset)
            ws.column_dimensions[col_letter].width = 14

    wb.save(output_path)
