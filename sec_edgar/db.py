"""
SQLite database layer: schema, upserts, and queries.
"""

from __future__ import annotations

import sqlite3
from typing import Any

METRIC_MAPPINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_mappings (
    metric_name           TEXT NOT NULL,
    display_name          TEXT NOT NULL,
    statement             TEXT NOT NULL,
    period_type           TEXT NOT NULL,
    unit                  TEXT NOT NULL,
    section               TEXT NOT NULL DEFAULT '',
    indent                INTEGER NOT NULL DEFAULT 0,
    sort_order            INTEGER NOT NULL DEFAULT 0,
    is_derived            INTEGER NOT NULL DEFAULT 0,
    concept               TEXT NOT NULL,
    taxonomy              TEXT NOT NULL DEFAULT 'us-gaap',
    priority              INTEGER NOT NULL DEFAULT 0,
    skip_ytd_subtraction  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (metric_name, concept, taxonomy)
);
"""

STOCK_SPLITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_splits (
    id                  INTEGER PRIMARY KEY,
    cik                 TEXT    NOT NULL,
    ticker              TEXT,
    numerator           INTEGER NOT NULL,
    denominator         INTEGER NOT NULL,
    -- Estimated date the split took effect (midpoint of pre/post filing dates).
    -- Used to identify pre-split periods: period_end < ex_date.
    ex_date             TEXT    NOT NULL,
    -- Date of the first post-split filing that retroactively adjusted comparatives.
    -- Used to identify stale pre-split facts: fact.filed_date < adjustment_boundary.
    adjustment_boundary TEXT    NOT NULL,
    ref_concept         TEXT    NOT NULL,
    ref_period_end      TEXT    NOT NULL,
    pre_value           REAL    NOT NULL,
    post_value          REAL    NOT NULL,
    pre_filed_date      TEXT    NOT NULL,
    post_filed_date     TEXT    NOT NULL,
    ratio_actual        REAL    NOT NULL,
    confidence          REAL    NOT NULL,
    detection_method    TEXT    NOT NULL DEFAULT 'auto',
    detected_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    -- One row per CIK per split ratio: deduplicates multiple detections of the
    -- same split event (different period/concept pairs can all detect the same jump).
    UNIQUE (cik, numerator, denominator)
);
CREATE INDEX IF NOT EXISTS idx_stock_splits_cik ON stock_splits (cik);
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
    conn.executescript(STOCK_SPLITS_SCHEMA)
    _migrate_schema(conn)
    _seed_metric_mappings(conn)
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply any additive schema migrations for existing databases."""
    # Add skip_ytd_subtraction column if it was created before this field existed.
    try:
        conn.execute(
            "ALTER TABLE metric_mappings ADD COLUMN "
            "skip_ytd_subtraction INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def _seed_metric_mappings(conn: sqlite3.Connection) -> None:
    """Seed metric_mappings from Python definitions (INSERT OR REPLACE = always fresh)."""
    from .metrics import metric_mappings_rows
    rows = metric_mappings_rows()
    conn.executemany(
        """
        INSERT OR REPLACE INTO metric_mappings
            (metric_name, display_name, statement, period_type, unit, section,
             indent, sort_order, is_derived, concept, taxonomy, priority,
             skip_ytd_subtraction)
        VALUES
            (:metric_name, :display_name, :statement, :period_type, :unit, :section,
             :indent, :sort_order, :is_derived, :concept, :taxonomy, :priority,
             :skip_ytd_subtraction)
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


# ---------------------------------------------------------------------------
# Stock split detection
# ---------------------------------------------------------------------------

# EPS concepts: post-split value is smaller (÷ factor); direction = "divide"
# Share count concepts: post-split value is larger (× factor); direction = "multiply"
_SPLIT_CONCEPTS: dict[str, str] = {
    "EarningsPerShareBasic":                          "divide",
    "EarningsPerShareDiluted":                        "divide",
    "WeightedAverageNumberOfSharesOutstandingBasic":  "multiply",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "multiply",
}

# Maps per-share metric names to split direction (used in reports.py)
SPLIT_ADJUSTED_METRICS: dict[str, str] = {
    "eps_basic":      "divide",
    "eps_diluted":    "divide",
    "shares_basic":   "multiply",
    "shares_diluted": "multiply",
}

_SPLIT_TOLERANCE = 0.08   # accept ratio within 8% of a round integer
_MAX_SPLIT_RATIO  = 20    # reject ratios above this (eliminates unit-scale false positives)


def detect_and_upsert_splits(
    conn: sqlite3.Connection,
    cik: str,
    ticker: str | None = None,
) -> list[dict]:
    """
    Auto-detect stock splits for a CIK by looking for (concept, period_end) pairs
    where the same period appears in two different filings with values differing by
    a factor close to a round integer ≥ 2.

    Returns a list of newly inserted split dicts.
    """
    import math

    concept_list = ", ".join(f"'{c}'" for c in _SPLIT_CONCEPTS)

    rows = conn.execute(
        f"""
        WITH filed_values AS (
            -- One value per (concept, period_end, filed_date) to avoid duplicates
            SELECT concept, period_end, filed_date, MIN(value) AS value
            FROM xbrl_facts
            WHERE cik = ?
              AND concept IN ({concept_list})
              AND value IS NOT NULL
              AND value != 0
            GROUP BY concept, period_end, filed_date
        ),
        bounds AS (
            SELECT concept, period_end,
                   MIN(filed_date) AS pre_filed,
                   MAX(filed_date) AS post_filed
            FROM filed_values
            GROUP BY concept, period_end
            HAVING MIN(filed_date) != MAX(filed_date)
        )
        SELECT
            b.concept, b.period_end,
            pre.value  AS pre_value,  b.pre_filed,
            post.value AS post_value, b.post_filed
        FROM bounds b
        JOIN filed_values pre
            ON  pre.concept    = b.concept
            AND pre.period_end = b.period_end
            AND pre.filed_date = b.pre_filed
        JOIN filed_values post
            ON  post.concept    = b.concept
            AND post.period_end = b.period_end
            AND post.filed_date = b.post_filed
        WHERE pre.value != 0 AND post.value != 0
        """,
        (cik,),
    ).fetchall()

    # Candidates: {(numerator, denominator) → best split dict}
    # One row per unique ratio — deduplicates multiple detections of the same split event.
    # Tiebreak: prefer the detection with the earliest adjustment_boundary (= first post-split
    # filing), then highest confidence.
    candidates: dict[tuple, dict] = {}

    for row in rows:
        concept   = row["concept"]
        direction = _SPLIT_CONCEPTS[concept]
        pre_v     = row["pre_value"]
        post_v    = row["post_value"]

        # Filter out sign changes (restated loss↔profit, not a split signal)
        if (pre_v > 0) != (post_v > 0):
            continue

        if direction == "divide":
            # EPS: pre-split EPS is larger; ratio = |pre| / |post|
            ratio = abs(pre_v) / abs(post_v)
        else:
            # Shares: post-split count is larger; ratio = post / pre
            ratio = post_v / pre_v

        if ratio < 1.5 or ratio > _MAX_SPLIT_RATIO:
            continue  # not a plausible stock split

        rounded = round(ratio)
        confidence = 1.0 - abs(rounded - ratio) / rounded
        if confidence < (1.0 - _SPLIT_TOLERANCE):
            continue

        # Use post_filed as ex_date: the split happened before this filing
        # (which shows retroactively adjusted values). Any period ending before
        # post_filed is a candidate for adjustment.
        ex_date = row["post_filed"]

        candidate = {
            "cik":                 cik,
            "ticker":              ticker,
            "numerator":           rounded,
            "denominator":         1,
            "ex_date":             ex_date,
            "adjustment_boundary": row["post_filed"],
            "ref_concept":         concept,
            "ref_period_end":      row["period_end"],
            "pre_value":           pre_v,
            "post_value":          post_v,
            "pre_filed_date":      row["pre_filed"],
            "post_filed_date":     row["post_filed"],
            "ratio_actual":        ratio,
            "confidence":          confidence,
        }

        # Keep the best candidate per ratio: earliest boundary first (= the first
        # post-split filing — any fact filed after this is already retroactively
        # adjusted and must NOT be re-adjusted), then highest confidence as tiebreak.
        key = (rounded, 1)
        existing = candidates.get(key)
        if existing is None:
            candidates[key] = candidate
        elif (row["post_filed"] < existing["adjustment_boundary"] or
              (row["post_filed"] == existing["adjustment_boundary"] and
               confidence > existing["confidence"])):
            candidates[key] = candidate

    inserted = []
    for split in candidates.values():
        conn.execute(
            """
            INSERT INTO stock_splits
                (cik, ticker, numerator, denominator, ex_date, adjustment_boundary,
                 ref_concept, ref_period_end, pre_value, post_value,
                 pre_filed_date, post_filed_date, ratio_actual, confidence)
            VALUES
                (:cik, :ticker, :numerator, :denominator, :ex_date, :adjustment_boundary,
                 :ref_concept, :ref_period_end, :pre_value, :post_value,
                 :pre_filed_date, :post_filed_date, :ratio_actual, :confidence)
            ON CONFLICT(cik, numerator, denominator) DO UPDATE SET
                ex_date             = excluded.ex_date,
                adjustment_boundary = excluded.adjustment_boundary,
                ref_concept         = excluded.ref_concept,
                ref_period_end      = excluded.ref_period_end,
                pre_value           = excluded.pre_value,
                post_value          = excluded.post_value,
                pre_filed_date      = excluded.pre_filed_date,
                post_filed_date     = excluded.post_filed_date,
                ratio_actual        = excluded.ratio_actual,
                confidence          = excluded.confidence,
                detected_at         = datetime('now')
            """,
            split,
        )
        inserted.append(split)

    conn.commit()
    return inserted


def load_splits(conn: sqlite3.Connection, cik: str) -> list[dict]:
    """Return all known stock splits for a CIK, ordered by ex_date ascending."""
    cursor = conn.execute(
        """
        SELECT numerator, denominator, ex_date, adjustment_boundary
        FROM stock_splits
        WHERE cik = ?
        ORDER BY ex_date
        """,
        (cik,),
    )
    return [dict(row) for row in cursor.fetchall()]
