"""
Tests for sec_edgar/db.py — schema, upserts, bulk_insert, queries.
Uses an in-memory SQLite database; no files created on disk.
"""

import pytest
import sqlite3

from sec_edgar import db as db_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    """Fresh in-memory database for each test."""
    c = db_mod.get_connection(":memory:")
    yield c
    c.close()


def _company(cik="0000320193", ticker="AAPL", name="Apple Inc."):
    return {
        "cik": cik,
        "ticker": ticker,
        "name": name,
        "sic": "3571",
        "sic_desc": "Electronic Computers",
        "ein": "94-2404110",
        "state_inc": "CA",
        "fiscal_year_end": "0930",
        "updated_at": "2024-01-01T00:00:00+00:00",
    }


def _filing(cik="0000320193", accession_no="0000320193-24-000123", form_type="10-K"):
    return {
        "cik": cik,
        "accession_no": accession_no,
        "form_type": form_type,
        "filed_date": "2024-11-01",
        "report_date": "2024-09-28",
        "document_count": 5,
        "primary_doc": "aapl-20240928.htm",
    }


def _fact(cik="0000320193", concept="Revenues", accession_no="0000320193-24-000123",
          period_end="2024-09-28", value=391_035_000_000.0):
    return {
        "cik": cik,
        "taxonomy": "us-gaap",
        "concept": concept,
        "label": "Revenues",
        "unit": "USD",
        "period_type": "duration",
        "period_start": "2023-10-01",
        "period_end": period_end,
        "value": value,
        "value_text": None,
        "accession_no": accession_no,
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "form": "10-K",
        "filed_date": "2024-11-01",
        "frame": "CY2024",
    }


# ---------------------------------------------------------------------------
# Schema & seeding
# ---------------------------------------------------------------------------

class TestSchema:
    def test_tables_created(self, conn):
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "companies" in tables
        assert "filings" in tables
        assert "xbrl_facts" in tables
        assert "metric_mappings" in tables

    def test_metric_mappings_seeded(self, conn):
        count = conn.execute("SELECT COUNT(*) FROM metric_mappings").fetchone()[0]
        assert count > 0

    def test_known_metrics_present(self, conn):
        names = {row[0] for row in
                 conn.execute("SELECT DISTINCT metric_name FROM metric_mappings").fetchall()}
        for expected in ("revenue", "net_income", "total_assets", "cf_operating"):
            assert expected in names, f"metric '{expected}' missing from metric_mappings"

    def test_wal_mode(self, tmp_path):
        # WAL mode only applies to file-based databases; in-memory uses 'memory' mode
        db_path = str(tmp_path / "test.db")
        c = db_mod.get_connection(db_path)
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        c.close()
        assert mode == "wal"


# ---------------------------------------------------------------------------
# companies table
# ---------------------------------------------------------------------------

class TestUpsertCompany:
    def test_insert(self, conn):
        db_mod.upsert_company(conn, _company())
        conn.commit()
        row = conn.execute("SELECT * FROM companies WHERE ticker='AAPL'").fetchone()
        assert row is not None
        assert row["name"] == "Apple Inc."

    def test_update_on_conflict(self, conn):
        db_mod.upsert_company(conn, _company(name="Apple Inc."))
        conn.commit()
        db_mod.upsert_company(conn, _company(name="Apple Incorporated"))
        conn.commit()
        row = conn.execute("SELECT name FROM companies WHERE ticker='AAPL'").fetchone()
        assert row["name"] == "Apple Incorporated"

    def test_ticker_unique(self, conn):
        db_mod.upsert_company(conn, _company(cik="0000320193", ticker="AAPL"))
        conn.commit()
        # Different CIK, same ticker → should update (ON CONFLICT on ticker via upsert)
        # Actually the PK is cik; same ticker but different cik raises UNIQUE on ticker index
        with pytest.raises(sqlite3.IntegrityError):
            db_mod.upsert_company(conn, _company(cik="0000999999", ticker="AAPL"))
            conn.commit()

    def test_multiple_companies(self, conn):
        db_mod.upsert_company(conn, _company(cik="0000320193", ticker="AAPL", name="Apple Inc."))
        db_mod.upsert_company(conn, _company(cik="0000789019", ticker="MSFT", name="Microsoft"))
        conn.commit()
        rows = db_mod.list_companies(conn)
        tickers = [r["ticker"] for r in rows]
        assert "AAPL" in tickers
        assert "MSFT" in tickers


# ---------------------------------------------------------------------------
# filings table
# ---------------------------------------------------------------------------

class TestUpsertFiling:
    def setup_company(self, conn):
        db_mod.upsert_company(conn, _company())
        conn.commit()

    def test_insert(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing())
        conn.commit()
        row = conn.execute(
            "SELECT * FROM filings WHERE accession_no='0000320193-24-000123'"
        ).fetchone()
        assert row is not None
        assert row["form_type"] == "10-K"
        assert row["xbrl_fetched"] == 0

    def test_ignore_on_duplicate_accession(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing())
        db_mod.upsert_filing(conn, _filing())  # second insert — same accession_no
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        assert count == 1

    def test_mark_filing_fetched(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing())
        conn.commit()
        db_mod.mark_filing_fetched(conn, "0000320193-24-000123", "2024-11-02T00:00:00+00:00")
        conn.commit()
        row = conn.execute(
            "SELECT xbrl_fetched, fetched_at FROM filings WHERE accession_no='0000320193-24-000123'"
        ).fetchone()
        assert row["xbrl_fetched"] == 1
        assert row["fetched_at"] == "2024-11-02T00:00:00+00:00"

    def test_get_unfetched_filings(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000001", form_type="10-K"))
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000002", form_type="10-Q"))
        conn.commit()
        unfetched = db_mod.get_unfetched_filings(conn, "0000320193", ["10-K", "10-Q"])
        assert len(unfetched) == 2

    def test_get_unfetched_excludes_fetched(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000001"))
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000002"))
        conn.commit()
        db_mod.mark_filing_fetched(conn, "0000320193-24-000001", "2024-11-02T00:00:00+00:00")
        conn.commit()
        unfetched = db_mod.get_unfetched_filings(conn, "0000320193", ["10-K"])
        accessions = [f["accession_no"] for f in unfetched]
        assert "0000320193-24-000001" not in accessions
        assert "0000320193-24-000002" in accessions

    def test_get_unfetched_filters_by_form_type(self, conn):
        self.setup_company(conn)
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000001", form_type="10-K"))
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000002", form_type="10-Q"))
        conn.commit()
        unfetched = db_mod.get_unfetched_filings(conn, "0000320193", ["10-K"])
        assert len(unfetched) == 1
        assert unfetched[0]["form_type"] == "10-K"


# ---------------------------------------------------------------------------
# xbrl_facts table
# ---------------------------------------------------------------------------

class TestBulkInsertFacts:
    def setup_company(self, conn):
        db_mod.upsert_company(conn, _company())
        conn.commit()

    def test_insert_returns_count(self, conn):
        self.setup_company(conn)
        facts = [_fact(), _fact(concept="Assets", value=352_583_000_000.0)]
        n = db_mod.bulk_insert_facts(conn, facts)
        conn.commit()
        assert n == 2

    def test_empty_list_returns_zero(self, conn):
        n = db_mod.bulk_insert_facts(conn, [])
        assert n == 0

    def test_duplicate_ignored(self, conn):
        self.setup_company(conn)
        fact = _fact()
        db_mod.bulk_insert_facts(conn, [fact])
        conn.commit()
        n2 = db_mod.bulk_insert_facts(conn, [fact])  # same unique key
        conn.commit()
        assert n2 == 0
        total = conn.execute("SELECT COUNT(*) FROM xbrl_facts").fetchone()[0]
        assert total == 1

    def test_different_accession_not_duplicate(self, conn):
        self.setup_company(conn)
        f1 = _fact(accession_no="0000320193-24-000001")
        f2 = _fact(accession_no="0000320193-24-000002")
        n = db_mod.bulk_insert_facts(conn, [f1, f2])
        conn.commit()
        assert n == 2

    def test_batching(self, conn):
        """Insert more than BATCH_SIZE=1000 facts in one call."""
        self.setup_company(conn)
        facts = [_fact(concept=f"Concept{i}", period_end=f"2024-{i:02d}-01"
                       if i <= 12 else "2024-01-01",
                       accession_no="0000320193-24-000001")
                 for i in range(1, 1201)]
        # Make each fact unique by varying concept + period_end combination
        facts = [
            {**_fact(), "concept": f"Concept{i}", "period_end": "2024-01-01",
             "accession_no": f"0000320193-24-{i:06d}"}
            for i in range(1201)
        ]
        n = db_mod.bulk_insert_facts(conn, facts)
        conn.commit()
        assert n == 1201


# ---------------------------------------------------------------------------
# list_companies / filing_summary / concept_summary
# ---------------------------------------------------------------------------

class TestQueryHelpers:
    def test_list_companies_ordered_by_ticker(self, conn):
        db_mod.upsert_company(conn, _company(cik="0000789019", ticker="MSFT", name="Microsoft"))
        db_mod.upsert_company(conn, _company(cik="0000320193", ticker="AAPL", name="Apple Inc."))
        conn.commit()
        rows = db_mod.list_companies(conn)
        tickers = [r["ticker"] for r in rows]
        assert tickers == sorted(tickers)

    def test_filing_summary(self, conn):
        db_mod.upsert_company(conn, _company())
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-24-000001"))
        db_mod.upsert_filing(conn, _filing(accession_no="0000320193-23-000099", form_type="10-Q"))
        conn.commit()
        rows = db_mod.filing_summary(conn, "0000320193")
        assert len(rows) == 2

    def test_concept_summary(self, conn):
        db_mod.upsert_company(conn, _company())
        db_mod.bulk_insert_facts(conn, [
            _fact(concept="Revenues"),
            _fact(concept="Assets", value=352e9),
        ])
        conn.commit()
        rows = db_mod.concept_summary(conn, "0000320193")
        concepts = {r["concept"] for r in rows}
        assert "Revenues" in concepts
        assert "Assets" in concepts
