"""
SQLite database layer: schema, upserts, and queries.
"""

from __future__ import annotations

import sqlite3
from typing import Any

METRIC_MAPPINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_mappings (
    metric_name  TEXT NOT NULL,
    display_name TEXT NOT NULL,
    statement    TEXT NOT NULL,
    period_type  TEXT NOT NULL,
    unit         TEXT NOT NULL,
    section      TEXT NOT NULL DEFAULT '',
    indent       INTEGER NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    is_derived   INTEGER NOT NULL DEFAULT 0,
    concept      TEXT NOT NULL,
    taxonomy     TEXT NOT NULL DEFAULT 'us-gaap',
    priority     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (metric_name, concept, taxonomy)
);
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS companies (
    cik             TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    name            TEXT NOT NULL,
    sic             TEXT,
    sic_desc        TEXT,
    ein             TEXT,
    state_inc       TEXT,
    fiscal_year_end TEXT,
    updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);

CREATE TABLE IF NOT EXISTS filings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cik             TEXT NOT NULL REFERENCES companies(cik),
    accession_no    TEXT NOT NULL,
    form_type       TEXT NOT NULL,
    filed_date      TEXT NOT NULL,
    report_date     TEXT,
    document_count  INTEGER,
    primary_doc     TEXT,
    xbrl_fetched    INTEGER NOT NULL DEFAULT 0,
    fetched_at      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_filings_accession ON filings(accession_no);
CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings(cik);
CREATE INDEX IF NOT EXISTS idx_filings_cik_form ON filings(cik, form_type, filed_date);

CREATE TABLE IF NOT EXISTS xbrl_facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cik             TEXT NOT NULL REFERENCES companies(cik),
    taxonomy        TEXT NOT NULL,
    concept         TEXT NOT NULL,
    label           TEXT,
    unit            TEXT NOT NULL,
    period_type     TEXT NOT NULL,
    period_start    TEXT,
    period_end      TEXT NOT NULL,
    value           REAL,
    value_text      TEXT,
    accession_no    TEXT,
    fiscal_year     INTEGER,
    fiscal_period   TEXT,
    form            TEXT,
    filed_date      TEXT,
    frame           TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_xbrl_facts_unique
    ON xbrl_facts(cik, taxonomy, concept, unit, period_end, accession_no);

CREATE INDEX IF NOT EXISTS idx_xbrl_facts_lookup
    ON xbrl_facts(cik, concept, period_end);

CREATE INDEX IF NOT EXISTS idx_xbrl_facts_accession
    ON xbrl_facts(accession_no);
"""

BATCH_SIZE = 1000


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executescript(METRIC_MAPPINGS_SCHEMA)
    _seed_metric_mappings(conn)
    return conn


def _seed_metric_mappings(conn: sqlite3.Connection) -> None:
    """Seed metric_mappings from Python definitions (INSERT OR REPLACE = always fresh)."""
    from .metrics import metric_mappings_rows
    rows = metric_mappings_rows()
    conn.executemany(
        """
        INSERT OR REPLACE INTO metric_mappings
            (metric_name, display_name, statement, period_type, unit, section,
             indent, sort_order, is_derived, concept, taxonomy, priority)
        VALUES
            (:metric_name, :display_name, :statement, :period_type, :unit, :section,
             :indent, :sort_order, :is_derived, :concept, :taxonomy, :priority)
        """,
        rows,
    )
    conn.commit()


def upsert_company(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO companies (cik, ticker, name, sic, sic_desc, ein,
                               state_inc, fiscal_year_end, updated_at)
        VALUES (:cik, :ticker, :name, :sic, :sic_desc, :ein,
                :state_inc, :fiscal_year_end, :updated_at)
        ON CONFLICT(cik) DO UPDATE SET
            ticker          = excluded.ticker,
            name            = excluded.name,
            sic             = excluded.sic,
            sic_desc        = excluded.sic_desc,
            ein             = excluded.ein,
            state_inc       = excluded.state_inc,
            fiscal_year_end = excluded.fiscal_year_end,
            updated_at      = excluded.updated_at
        """,
        data,
    )


def upsert_filing(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    # INSERT OR IGNORE to preserve xbrl_fetched flag on re-runs
    conn.execute(
        """
        INSERT OR IGNORE INTO filings
            (cik, accession_no, form_type, filed_date, report_date,
             document_count, primary_doc)
        VALUES
            (:cik, :accession_no, :form_type, :filed_date, :report_date,
             :document_count, :primary_doc)
        """,
        data,
    )


def mark_filing_fetched(conn: sqlite3.Connection, accession_no: str, fetched_at: str) -> None:
    conn.execute(
        "UPDATE filings SET xbrl_fetched=1, fetched_at=? WHERE accession_no=?",
        (fetched_at, accession_no),
    )


def bulk_insert_facts(conn: sqlite3.Connection, facts: list[dict[str, Any]]) -> int:
    """Insert facts in batches; skips duplicates. Returns count inserted."""
    if not facts:
        return 0

    sql = """
        INSERT OR IGNORE INTO xbrl_facts
            (cik, taxonomy, concept, label, unit, period_type, period_start,
             period_end, value, value_text, accession_no, fiscal_year,
             fiscal_period, form, filed_date, frame)
        VALUES
            (:cik, :taxonomy, :concept, :label, :unit, :period_type, :period_start,
             :period_end, :value, :value_text, :accession_no, :fiscal_year,
             :fiscal_period, :form, :filed_date, :frame)
    """
    inserted = 0
    for i in range(0, len(facts), BATCH_SIZE):
        batch = facts[i : i + BATCH_SIZE]
        cursor = conn.executemany(sql, batch)
        inserted += cursor.rowcount
    return inserted


def get_unfetched_filings(
    conn: sqlite3.Connection,
    cik: str,
    form_types: list[str],
) -> list[dict]:
    placeholders = ",".join("?" * len(form_types))
    cursor = conn.execute(
        f"""
        SELECT accession_no, form_type, filed_date, report_date
        FROM filings
        WHERE cik = ? AND xbrl_fetched = 0 AND form_type IN ({placeholders})
        ORDER BY filed_date
        """,
        [cik, *form_types],
    )
    return [dict(row) for row in cursor.fetchall()]


def query_facts(
    conn: sqlite3.Connection,
    tickers: list[str],
    concepts: list[str] | None,
    form_types: list[str],
) -> list[dict]:
    ticker_placeholders = ",".join("?" * len(tickers))
    params: list[Any] = list(tickers)

    concept_filter = ""
    if concepts:
        concept_placeholders = ",".join("?" * len(concepts))
        concept_filter = f"AND f.concept IN ({concept_placeholders})"
        params.extend(concepts)

    form_placeholders = ",".join("?" * len(form_types))
    params.extend(form_types)

    cursor = conn.execute(
        f"""
        SELECT c.ticker, c.name, f.taxonomy, f.concept, f.label,
               f.unit, f.period_type, f.period_start, f.period_end,
               f.value, f.value_text, f.fiscal_year, f.fiscal_period,
               f.form, f.filed_date, f.frame, f.accession_no
        FROM xbrl_facts f
        JOIN companies c ON c.cik = f.cik
        WHERE c.ticker IN ({ticker_placeholders})
          {concept_filter}
          AND f.form IN ({form_placeholders})
        ORDER BY c.ticker, f.concept, f.period_end
        """,
        params,
    )
    return [dict(row) for row in cursor.fetchall()]


def list_companies(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.execute(
        "SELECT cik, ticker, name, sic, sic_desc, fiscal_year_end, updated_at "
        "FROM companies ORDER BY ticker"
    )
    return [dict(row) for row in cursor.fetchall()]


def filing_summary(conn: sqlite3.Connection, cik: str) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT form_type, filed_date, report_date, xbrl_fetched, accession_no
        FROM filings WHERE cik = ?
        ORDER BY filed_date DESC
        """,
        (cik,),
    )
    return [dict(row) for row in cursor.fetchall()]


def concept_summary(conn: sqlite3.Connection, cik: str) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT taxonomy, concept, label, unit, COUNT(*) as fact_count,
               MIN(period_end) as earliest, MAX(period_end) as latest
        FROM xbrl_facts WHERE cik = ?
        GROUP BY taxonomy, concept, unit
        ORDER BY taxonomy, concept
        """,
        (cik,),
    )
    return [dict(row) for row in cursor.fetchall()]
