"""
CLI entry point for sec-edgar tool.

Usage:
    export EDGAR_USER_AGENT="Your Name your@email.com"

    # Fetch filings
    sec-edgar fetch AAPL MSFT GOOGL
    sec-edgar fetch AAPL --forms 10-K

    # Standardized financial reports
    sec-edgar report AAPL
    sec-edgar report AAPL --statement income-statement --period annual --years 5
    sec-edgar report AAPL --statement all --period quarterly --quarters 8
    sec-edgar report AAPL --format excel -o aapl_financials.xlsx
    sec-edgar report AAPL MSFT --format csv --output-dir ./reports/

    # Raw XBRL export
    sec-edgar export AAPL --concepts Revenues,NetIncomeLoss --format csv -o out.csv

    # Database info
    sec-edgar ls
    sec-edgar info AAPL
"""

from __future__ import annotations

import os
import sys

import click

from . import db as db_mod
from . import pipeline
from . import export as export_mod
from . import reports as reports_mod
from .client import EdgarClient


@click.group()
@click.option(
    "--db",
    "db_path",
    default="edgar.db",
    show_default=True,
    envvar="EDGAR_DB",
    help="Path to SQLite database file.",
)
@click.option(
    "--user-agent",
    required=True,
    envvar="EDGAR_USER_AGENT",
    help='Required by SEC: "Name email@example.com"',
)
@click.pass_context
def cli(ctx: click.Context, db_path: str, user_agent: str) -> None:
    """SEC EDGAR 10-K/10-Q downloader and XBRL fact store."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path
    ctx.obj["user_agent"] = user_agent


@cli.command()
@click.argument("tickers", nargs=-1, required=False)
@click.option(
    "--forms",
    default="10-K,10-Q,10-K/A,10-Q/A",
    show_default=True,
    help="Comma-separated list of form types to fetch.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be done without writing.")
@click.option("--verbose", "-v", is_flag=True)
@click.option(
    "--all", "fetch_all",
    is_flag=True,
    help="Refresh all tickers already in the database.",
)
@click.pass_context
def fetch(
    ctx: click.Context,
    tickers: tuple[str, ...],
    forms: str,
    dry_run: bool,
    verbose: bool,
    fetch_all: bool,
) -> None:
    """Download filings metadata and XBRL facts for one or more TICKERS.

    Use --all to refresh every ticker already in the database.
    """
    if fetch_all:
        conn = db_mod.get_connection(ctx.obj["db_path"])
        rows = db_mod.list_companies(conn)
        if not rows:
            click.echo("No companies in database. Run 'fetch TICKER' first.", err=True)
            sys.exit(1)
        tickers = tuple(r["ticker"] for r in rows)
        click.echo(f"Refreshing {len(tickers)} ticker(s): {', '.join(tickers)}")
    elif not tickers:
        click.echo("Error: provide at least one TICKER or use --all.", err=True)
        sys.exit(1)

    form_types = [f.strip() for f in forms.split(",") if f.strip()]
    edgar_client = EdgarClient(user_agent=ctx.obj["user_agent"])
    pipeline.run(
        tickers=list(tickers),
        db_path=ctx.obj["db_path"],
        form_types=form_types,
        edgar_client=edgar_client,
        dry_run=dry_run,
        verbose=verbose,
    )


@cli.command("export")
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--concepts",
    default=None,
    help="Comma-separated XBRL concept names (e.g. Revenues,NetIncomeLoss). "
         "If omitted, exports all concepts.",
)
@click.option(
    "--forms",
    default="10-K,10-Q",
    show_default=True,
    help="Comma-separated form types to include.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default="csv",
    show_default=True,
)
@click.option(
    "--output",
    "-o",
    default="-",
    help="Output file path. Use '-' for stdout (default).",
)
@click.pass_context
def export_cmd(
    ctx: click.Context,
    tickers: tuple[str, ...],
    concepts: str | None,
    forms: str,
    fmt: str,
    output: str,
) -> None:
    """Export XBRL facts to CSV or JSON for analysis/visualization."""
    concept_list = [c.strip() for c in concepts.split(",") if c.strip()] if concepts else None
    form_types = [f.strip() for f in forms.split(",") if f.strip()]

    conn = db_mod.get_connection(ctx.obj["db_path"])
    count = export_mod.export_facts(
        conn=conn,
        tickers=list(tickers),
        concepts=concept_list,
        form_types=form_types,
        fmt=fmt,
        output_path=output,
    )
    if output != "-":
        click.echo(f"Exported {count} rows to {output}")


@cli.command("ls")
@click.pass_context
def list_companies(ctx: click.Context) -> None:
    """List all companies in the database."""
    conn = db_mod.get_connection(ctx.obj["db_path"])
    rows = db_mod.list_companies(conn)
    if not rows:
        click.echo("No companies in database. Run 'fetch' first.")
        return

    # Header
    click.echo(f"{'TICKER':<10} {'CIK':<12} {'NAME':<40} {'SIC':<6} {'FYE'}")
    click.echo("-" * 80)
    for r in rows:
        click.echo(
            f"{r['ticker']:<10} {r['cik']:<12} {r['name'][:38]:<40} "
            f"{r['sic'] or '':<6} {r['fiscal_year_end'] or ''}"
        )
    click.echo(f"\n{len(rows)} company/companies")


@cli.command()
@click.argument("ticker")
@click.pass_context
def info(ctx: click.Context, ticker: str) -> None:
    """Show filing and concept summary for TICKER."""
    conn = db_mod.get_connection(ctx.obj["db_path"])

    companies = db_mod.list_companies(conn)
    company = next((c for c in companies if c["ticker"] == ticker.upper()), None)
    if not company:
        click.echo(f"Ticker '{ticker}' not found. Run 'fetch {ticker}' first.", err=True)
        sys.exit(1)

    cik = company["cik"]
    click.echo(f"\nCompany : {company['name']}")
    click.echo(f"Ticker  : {company['ticker']}")
    click.echo(f"CIK     : {cik}")
    click.echo(f"SIC     : {company['sic']} ({company['sic_desc'] or 'n/a'})")
    click.echo(f"FYE     : {company['fiscal_year_end'] or 'n/a'}")
    click.echo(f"Updated : {company['updated_at']}")

    filings = db_mod.filing_summary(conn, cik)
    click.echo(f"\nFilings ({len(filings)} total):")
    click.echo(f"  {'FORM':<8} {'FILED':<12} {'PERIOD':<12} {'XBRL':<6} ACCESSION")
    click.echo("  " + "-" * 70)
    for f in filings[:20]:
        fetched = "yes" if f["xbrl_fetched"] else "no"
        click.echo(
            f"  {f['form_type']:<8} {f['filed_date']:<12} "
            f"{f['report_date'] or '':<12} {fetched:<6} {f['accession_no']}"
        )
    if len(filings) > 20:
        click.echo(f"  ... and {len(filings) - 20} more")

    concepts = db_mod.concept_summary(conn, cik)
    click.echo(f"\nXBRL Concepts ({len(concepts)} unique concept/unit pairs):")
    click.echo(f"  {'TAXONOMY':<10} {'CONCEPT':<45} {'UNIT':<10} {'COUNT':<7} {'EARLIEST':<12} LATEST")
    click.echo("  " + "-" * 100)
    for c in concepts[:30]:
        click.echo(
            f"  {c['taxonomy']:<10} {c['concept'][:43]:<45} {c['unit']:<10} "
            f"{c['fact_count']:<7} {c['earliest']:<12} {c['latest']}"
        )
    if len(concepts) > 30:
        click.echo(f"  ... and {len(concepts) - 30} more")


# ---------------------------------------------------------------------------
# report command
# ---------------------------------------------------------------------------

STATEMENT_CHOICES = click.Choice(
    ["income-statement", "balance-sheet", "cash-flow", "ratios", "all"],
    case_sensitive=False,
)

SCALE_MAP = {
    "millions": 1_000_000,
    "thousands": 1_000,
    "billions": 1_000_000_000,
    "raw": 1,
}


@cli.command()
@click.argument("tickers", nargs=-1, required=True)
@click.option(
    "--statement", "-s",
    type=STATEMENT_CHOICES,
    default="all",
    show_default=True,
    help="Financial statement to generate.",
)
@click.option(
    "--period", "-p",
    type=click.Choice(["annual", "quarterly"], case_sensitive=False),
    default="annual",
    show_default=True,
)
@click.option(
    "--years",
    type=int,
    default=5,
    show_default=True,
    help="Number of fiscal years (annual mode).",
)
@click.option(
    "--quarters",
    type=int,
    default=8,
    show_default=True,
    help="Number of quarters (quarterly mode).",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["text", "csv", "excel"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--scale",
    type=click.Choice(list(SCALE_MAP.keys()), case_sensitive=False),
    default="millions",
    show_default=True,
    help="Scale for USD values.",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output file path. For text/csv defaults to stdout. "
         "For excel, required (or auto-generated).",
)
@click.option(
    "--output-dir",
    default=None,
    help="Output directory when generating multiple files (multi-ticker csv/excel).",
)
@click.option(
    "--price",
    type=float,
    default=None,
    help="Current stock price. Unlocks market multiples (P/E, EV/EBITDA, etc.).",
)
@click.pass_context
def report(
    ctx: click.Context,
    tickers: tuple,
    statement: str,
    period: str,
    years: int,
    quarters: int,
    fmt: str,
    scale: str,
    output: Optional[str],
    output_dir: Optional[str],
    price: Optional[float],
) -> None:
    """
    Generate standardized Income Statement, Balance Sheet, or Cash Flow report.

    Examples:\n
        sec-edgar report AAPL\n
        sec-edgar report AAPL --statement income-statement --period annual --years 5\n
        sec-edgar report AAPL --statement all --period quarterly --quarters 8\n
        sec-edgar report AAPL --format excel -o aapl.xlsx\n
        sec-edgar report AAPL MSFT --format csv --output-dir ./reports/
    """
    from typing import Optional as _Opt  # noqa: F811

    conn = db_mod.get_connection(ctx.obj["db_path"])
    scale_divisor = SCALE_MAP[scale.lower()]
    num_periods = years if period == "annual" else quarters

    # Resolve statement list
    stmt_map = {
        "income-statement": ["income_statement"],
        "balance-sheet": ["balance_sheet"],
        "cash-flow": ["cash_flow"],
        "ratios": ["ratios"],
        "all": ["income_statement", "balance_sheet", "cash_flow", "ratios"],
    }
    statements = stmt_map[statement.lower()]

    for ticker in tickers:
        try:
            rpts = reports_mod.build_reports(
                conn=conn,
                ticker=ticker,
                statements=statements,
                period=period,
                num_periods=num_periods,
                scale=scale_divisor,
                price=price,
            )
        except ValueError as e:
            click.echo(f"[ERROR] {e}", err=True)
            continue

        if fmt == "text":
            dest = output or "-"
            out_fh = open(dest, "w") if dest != "-" else None
            for rpt in rpts:
                if isinstance(rpt, reports_mod.RatioReport):
                    text = reports_mod.format_ratio_text(rpt)
                else:
                    text = reports_mod.format_text(rpt)
                if out_fh:
                    out_fh.write(text + "\n\n")
                else:
                    click.echo(text)
                    click.echo()
            if out_fh:
                out_fh.close()
                click.echo(f"Saved to {dest}")

        elif fmt == "csv":
            for rpt in rpts:
                if output and len(tickers) == 1 and len(statements) == 1:
                    dest = output
                else:
                    stmt_slug = rpt.statement.replace("_", "-")
                    filename = f"{ticker.upper()}_{stmt_slug}.csv"
                    dest = os.path.join(output_dir or ".", filename)
                if isinstance(rpt, reports_mod.RatioReport):
                    csv_text = reports_mod.format_ratio_csv(rpt)
                else:
                    csv_text = reports_mod.format_csv(rpt)
                if dest == "-" or (output is None and output_dir is None and len(tickers) == 1 and len(statements) == 1):
                    click.echo(csv_text)
                else:
                    with open(dest, "w", newline="", encoding="utf-8") as f:
                        f.write(csv_text)
                    click.echo(f"Saved {rpt.statement_title} → {dest}")

        elif fmt == "excel":
            if output and len(tickers) == 1:
                dest = output
            else:
                filename = f"{ticker.upper()}_financials.xlsx"
                dest = os.path.join(output_dir or ".", filename)
            try:
                reports_mod.write_excel(rpts, dest)
                click.echo(f"Saved {ticker.upper()} workbook → {dest}")
            except ImportError as e:
                click.echo(f"[ERROR] {e}", err=True)
                sys.exit(1)
