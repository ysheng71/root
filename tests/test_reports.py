"""
Tests for sec_edgar/reports.py: fiscal_year bug fix, date-format labels, LTM column.
Uses an in-memory SQLite database seeded with minimal fixture data.
"""

from __future__ import annotations

import pytest
import sqlite3

from sec_edgar import db as db_mod
from sec_edgar.reports import _fetch_facts, _fetch_ltm, _period_sort_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CIK = "0000123456"
TICKER = "TEST"


@pytest.fixture()
def conn():
    """In-memory DB with schema and metric_mappings seeded."""
    c = db_mod.get_connection(":memory:")
    # Insert a dummy company required by the FK constraint
    c.execute(
        """
        INSERT INTO companies (cik, ticker, name, sic, sic_desc, ein,
                               state_inc, fiscal_year_end, updated_at)
        VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?)
        """,
        (CIK, TICKER, "Test Corp", "2024-01-01T00:00:00"),
    )
    c.commit()
    yield c
    c.close()


def _fact(
    cik=CIK,
    concept="OperatingIncomeLoss",
    taxonomy="us-gaap",
    unit="USD",
    period_type="duration",
    period_start="2023-10-01",
    period_end="2024-09-30",
    value=23_595_000_000.0,
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    filed_date="2024-11-01",
    accession_no="0000123456-24-000001",
):
    return {
        "cik": cik,
        "taxonomy": taxonomy,
        "concept": concept,
        "label": concept,
        "unit": unit,
        "period_type": period_type,
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "value_text": None,
        "accession_no": accession_no,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "form": form,
        "filed_date": filed_date,
        "frame": None,
    }


# ---------------------------------------------------------------------------
# Bug regression: fiscal_year partition caused wrong row selection
# ---------------------------------------------------------------------------

class TestFiscalYearBugRegression:
    """
    The bug: EDGAR stamps all comparative periods in a 10-K with the filing's FY.
    So a FY2024 10-K (filed 2024-11) has fy=2024 for ALL rows including FY2022 data.
    Partitioning by (metric_name, fiscal_year, fiscal_period) picks one arbitrarily.
    Fix: partition by (metric_name, period_end) so each date gets its own winner.
    """

    def test_correct_value_returned_for_period_end(self, conn):
        """Should return 23595 for 9/30/24, not 18813 from a comparative period."""
        facts = [
            # Correct FY2024 row: period_end=2024-09-30, fy=2024, filed 2024-11
            _fact(
                period_end="2024-09-30",
                value=23_595_000_000.0,
                fiscal_year=2024,
                filed_date="2024-11-01",
                accession_no="0000123456-24-000001",
            ),
            # Comparative FY2022 row inside same 10-K: fy=2024 (EDGAR stamps filing year)
            _fact(
                period_end="2022-09-30",
                value=18_813_000_000.0,
                fiscal_year=2024,   # wrong stamp — this is the EDGAR bug
                filed_date="2024-11-01",
                accession_no="0000123456-24-000001",
            ),
            # Same period from next year's 10-K as comparative (fy=2025)
            _fact(
                period_end="2024-09-30",
                value=23_595_000_000.0,
                fiscal_year=2025,
                filed_date="2025-11-01",
                accession_no="0000123456-25-000001",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)

        # Find the label for 9/30/24
        label_9_30_24 = "9/30/24"
        key = ("operating_income", label_9_30_24)
        assert key in result, f"Expected period label '{label_9_30_24}' in results"
        assert result[key] == 23_595_000_000.0, (
            f"Expected 23,595M but got {result[key]}"
        )

    def test_wrong_comparative_not_returned(self, conn):
        """The 18813 value (wrong comparative period) should not appear for 9/30/24."""
        facts = [
            _fact(
                period_end="2024-09-30",
                value=23_595_000_000.0,
                fiscal_year=2024,
                filed_date="2024-11-01",
                accession_no="0000123456-24-000001",
            ),
            _fact(
                period_end="2022-09-30",
                value=18_813_000_000.0,
                fiscal_year=2024,
                filed_date="2024-11-01",
                accession_no="0000123456-24-000001",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)

        # 18813 should only appear under 9/30/22, never under 9/30/24
        val_9_30_24 = result.get(("operating_income", "9/30/24"))
        assert val_9_30_24 != 18_813_000_000.0


# ---------------------------------------------------------------------------
# Column label format: M/D/YY instead of FY####
# ---------------------------------------------------------------------------

class TestColumnLabelFormat:
    def test_annual_labels_use_date_format(self, conn):
        facts = [
            _fact(
                period_end="2024-09-30",
                value=23_595_000_000.0,
                fiscal_year=2024,
                accession_no="0000123456-24-000001",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)
        period_labels = {p for (_, p) in result.keys()}

        assert "9/30/24" in period_labels, f"Expected '9/30/24' in {period_labels}"
        assert not any(p.startswith("FY") for p in period_labels), (
            f"Expected no 'FY####' labels but got {period_labels}"
        )

    def test_december_year_end_label(self, conn):
        facts = [
            _fact(
                period_end="2023-12-31",
                value=10_000_000.0,
                fiscal_year=2023,
                accession_no="0000123456-24-000099",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)
        period_labels = {p for (_, p) in result.keys()}
        assert "12/31/23" in period_labels, f"Expected '12/31/23' in {period_labels}"


# ---------------------------------------------------------------------------
# LTM computation
# ---------------------------------------------------------------------------

class TestFetchLtm:
    """
    LTM formula (duration metrics): annual + recent_ytd - prior_ytd
    annual FY ending 9/30/23: 20_000
    recent Q3 YTD (9 months to 6/30/24): 16_000
    prior Q3 YTD (9 months to 6/30/23): 15_000
    LTM = 20_000 + 16_000 - 15_000 = 21_000
    """

    def _seed(self, conn):
        annual = _fact(
            period_end="2023-09-30",
            period_start="2022-10-01",
            value=20_000_000_000.0,
            fiscal_year=2023,
            fiscal_period="FY",
            form="10-K",
            filed_date="2023-11-15",
            accession_no="0000123456-23-000001",
        )
        # Recent YTD: 9 months to 6/30/24 (Q3 of FY2024)
        recent_q = _fact(
            period_end="2024-06-30",
            period_start="2023-10-01",
            value=16_000_000_000.0,
            fiscal_year=2024,
            fiscal_period="Q3",
            form="10-Q",
            filed_date="2024-08-01",
            accession_no="0000123456-24-000010",
        )
        # Prior-year same quarter YTD: 9 months to 6/30/23
        prior_q = _fact(
            period_end="2023-06-30",
            period_start="2022-10-01",
            value=15_000_000_000.0,
            fiscal_year=2023,
            fiscal_period="Q3",
            form="10-Q",
            filed_date="2023-08-01",
            accession_no="0000123456-23-000010",
        )
        db_mod.bulk_insert_facts(conn, [annual, recent_q, prior_q])
        conn.commit()

    def test_ltm_formula(self, conn):
        self._seed(conn)
        ltm = _fetch_ltm(conn, CIK, "income_statement")
        val = ltm.get("operating_income")
        expected = 20_000_000_000.0 + 16_000_000_000.0 - 15_000_000_000.0
        assert val == pytest.approx(expected), (
            f"Expected LTM operating_income={expected}, got {val}"
        )

    def test_ltm_falls_back_to_annual_when_no_quarters(self, conn):
        annual = _fact(
            period_end="2023-09-30",
            period_start="2022-10-01",
            value=20_000_000_000.0,
            fiscal_year=2023,
            fiscal_period="FY",
            form="10-K",
            filed_date="2023-11-15",
            accession_no="0000123456-23-000001",
        )
        db_mod.bulk_insert_facts(conn, [annual])
        conn.commit()

        ltm = _fetch_ltm(conn, CIK, "income_statement")
        # No quarters → returns annual as-is
        assert ltm.get("operating_income") == pytest.approx(20_000_000_000.0)

    def test_ltm_empty_when_no_annual(self, conn):
        # No data at all → empty dict
        ltm = _fetch_ltm(conn, CIK, "income_statement")
        assert ltm == {}

    def test_ltm_instant_uses_quarterly_snapshot(self, conn):
        """Balance sheet (instant) LTM should use the latest quarterly value, not annual."""
        # Annual balance sheet value (9/30/23)
        annual_bs = _fact(
            concept="Assets",
            period_end="2023-09-30",
            period_start=None,
            value=50_000_000_000.0,
            fiscal_year=2023,
            fiscal_period="FY",
            form="10-K",
            filed_date="2023-11-15",
            accession_no="0000123456-23-000002",
        )
        # Quarterly snapshot (6/30/24) — should be LTM value for balance sheet
        quarterly_bs = _fact(
            concept="Assets",
            period_end="2024-06-30",
            period_start=None,
            value=55_000_000_000.0,
            fiscal_year=2024,
            fiscal_period="Q3",
            form="10-Q",
            filed_date="2024-08-01",
            accession_no="0000123456-24-000011",
        )
        db_mod.bulk_insert_facts(conn, [annual_bs, quarterly_bs])
        conn.commit()

        ltm = _fetch_ltm(conn, CIK, "balance_sheet")
        val = ltm.get("total_assets")
        assert val == pytest.approx(55_000_000_000.0), (
            f"Expected quarterly snapshot 55B for total_assets LTM, got {val}"
        )


# ---------------------------------------------------------------------------
# Sort key
# ---------------------------------------------------------------------------

class TestPeriodSortKey:
    def test_ltm_sorts_last(self):
        assert _period_sort_key("LTM") > _period_sort_key("12/31/24")

    def test_later_date_sorts_after_earlier(self):
        assert _period_sort_key("12/31/24") > _period_sort_key("9/30/24")

    def test_annual_dates_sort_before_ltm(self):
        labels = ["LTM", "9/30/24", "9/30/23", "12/31/24"]
        sorted_labels = sorted(labels, key=_period_sort_key)
        assert sorted_labels[-1] == "LTM"
        assert sorted_labels[0] == "9/30/23"

    def test_fy_backward_compat(self):
        # FY labels still sort correctly for backward compatibility
        assert _period_sort_key("FY2024") > _period_sort_key("FY2023")

    def test_quarterly_labels_sort(self):
        assert _period_sort_key("2024 Q2") > _period_sort_key("2024 Q1")
        assert _period_sort_key("2024 Q1") > _period_sort_key("2023 Q4")
