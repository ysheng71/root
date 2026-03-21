"""
Orchestrate: fetch -> parse -> store for one or more tickers.
"""

from __future__ import annotations

from datetime import datetime, timezone

import click

from . import client as client_mod
from . import db
from . import parser


DEFAULT_FORM_TYPES = ["10-K", "10-Q", "10-K/A", "10-Q/A"]


def run(
    tickers: list[str],
    db_path: str,
    form_types: list[str],
    edgar_client: client_mod.EdgarClient,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    conn = db.get_connection(db_path)

    click.echo("Fetching ticker -> CIK map...")
    ticker_map = edgar_client.get_ticker_cik_map()

    for ticker in tickers:
        ticker_upper = ticker.upper()
        cik = ticker_map.get(ticker_upper)
        if not cik:
            click.echo(f"[WARN] Unknown ticker: {ticker}", err=True)
            continue

        _process_ticker(
            ticker=ticker_upper,
            cik=cik,
            conn=conn,
            form_types=form_types,
            edgar_client=edgar_client,
            dry_run=dry_run,
            verbose=verbose,
        )


def _process_ticker(
    ticker: str,
    cik: str,
    conn,
    form_types: list[str],
    edgar_client: client_mod.EdgarClient,
    dry_run: bool,
    verbose: bool,
) -> None:
    click.echo(f"\n[{ticker}] CIK: {cik}")

    # --- Step 1: Fetch and store submissions metadata ---
    click.echo(f"[{ticker}] Fetching submissions...")
    try:
        raw_sub = edgar_client.get_submissions(cik)
    except Exception as e:
        click.echo(f"[{ticker}] ERROR fetching submissions: {e}", err=True)
        return

    company_data, filings_list = parser.parse_submissions(raw_sub)
    # Override ticker with what user provided (API may return different case)
    company_data["ticker"] = ticker

    if not dry_run:
        db.upsert_company(conn, company_data)
        new_filings = 0
        for filing in filings_list:
            cursor = conn.execute(
                "SELECT id FROM filings WHERE accession_no = ?",
                (filing["accession_no"],),
            )
            if cursor.fetchone() is None:
                new_filings += 1
            db.upsert_filing(conn, filing)
        conn.commit()
        click.echo(
            f"[{ticker}] {len(filings_list)} filings in history "
            f"({new_filings} new)"
        )
    else:
        click.echo(f"[{ticker}] [DRY RUN] Would store {len(filings_list)} filings")
        return

    # --- Step 2: Check which filings still need XBRL facts ---
    unfetched = db.get_unfetched_filings(conn, cik, form_types)
    if not unfetched:
        click.echo(f"[{ticker}] All filings up to date, skipping XBRL fetch")
        return

    click.echo(f"[{ticker}] {len(unfetched)} filings need XBRL data, fetching...")

    # --- Step 3: Fetch all XBRL facts (one call returns full history) ---
    try:
        raw_facts = edgar_client.get_company_facts(cik)
    except Exception as e:
        click.echo(f"[{ticker}] ERROR fetching company facts: {e}", err=True)
        return

    all_facts = parser.parse_company_facts(cik, raw_facts)
    if verbose:
        click.echo(f"[{ticker}] Parsed {len(all_facts)} total facts from API")

    # Filter to only facts from unfetched filings
    unfetched_accns = {f["accession_no"] for f in unfetched}
    facts_to_insert = [f for f in all_facts if f.get("accession_no") in unfetched_accns]

    click.echo(
        f"[{ticker}] Inserting {len(facts_to_insert)} facts "
        f"from {len(unfetched)} filings..."
    )

    inserted = db.bulk_insert_facts(conn, facts_to_insert)

    now = datetime.now(timezone.utc).isoformat()
    for filing in unfetched:
        db.mark_filing_fetched(conn, filing["accession_no"], now)
    conn.commit()

    click.echo(f"[{ticker}] Done. {inserted} new facts inserted.")

    # Detect stock splits from newly ingested data
    splits = db.detect_and_upsert_splits(conn, cik, ticker=ticker)
    if splits:
        for s in splits:
            click.echo(
                f"[{ticker}] Stock split detected: {s['numerator']}:{s['denominator']} "
                f"~{s['ex_date']} (confidence {s['confidence']:.3f}, "
                f"factor from {s['ref_concept']})"
            )
