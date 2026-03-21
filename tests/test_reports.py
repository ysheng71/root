"""
Tests for sec_edgar/reports.py: fiscal_year bug fix, date-format labels, LTM column.
Uses an in-memory SQLite database seeded with minimal fixture data.
"""

from __future__ import annotations

import pytest
import sqlite3

from sec_edgar import db as db_mod
from sec_edgar.computed import YoYGrowth
from sec_edgar.reports import _fetch_facts, _fetch_ltm, _period_sort_key, fetch_all_metrics


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

        result, _ = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)

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

        result, _ = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)

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

        result, _ = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)
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

        result, _ = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)
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

    def test_quarterly_mdyy_labels_sort(self):
        # Quarterly M/D/YY labels sort correctly via date parsing
        assert _period_sort_key("3/31/24") > _period_sort_key("12/31/23")
        assert _period_sort_key("12/31/23") > _period_sort_key("9/30/23")

    def test_legacy_quarterly_yyyyqn_labels_sort(self):
        # Legacy "YYYY QN" labels still sort correctly (backward compat)
        assert _period_sort_key("2024 Q2") > _period_sort_key("2024 Q1")
        assert _period_sort_key("2024 Q1") > _period_sort_key("2023 Q4")


# ---------------------------------------------------------------------------
# Bug #1 — Quarterly prior-year comparative picked over current-period value
# ---------------------------------------------------------------------------

class TestQuarterlyPeriodEndTiebreaker:
    """
    EDGAR stamps both the current-period row and the prior-year comparative row
    in a 10-Q with the same fiscal_year and fiscal_period. Without period_end DESC
    as a tiebreaker, ROW_NUMBER() picks the wrong (older) row.
    Fix: ORDER BY mm.priority ASC, f.period_end DESC, f.filed_date DESC.
    """

    def test_current_quarter_beats_prior_year_comparative(self, conn):
        """Q1 FY2025 (period_end=12/31/24) should win over the prior-year comparative."""
        facts = [
            # Current Q1: period_end=2024-12-31, value=9000M
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2024-10-01",
                period_end="2024-12-31",
                value=9_000_000_000.0,
                fiscal_year=2025,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2025-02-01",
                accession_no="0000123456-25-000001",
            ),
            # Prior-year Q1 comparative (same fiscal_year=2025 stamp from EDGAR)
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2023-10-01",
                period_end="2023-12-31",
                value=8_000_000_000.0,
                fiscal_year=2025,   # EDGAR stamps filing year — the bug
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2025-02-01",
                accession_no="0000123456-25-000001",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)

        # Current Q1 period_end=2024-12-31 → label "12/31/24"
        key = ("operating_income", "12/31/24")
        assert key in result, f"Expected period label '12/31/24' in results"
        assert result[key] == pytest.approx(9_000_000_000.0), (
            f"Expected current Q1 9B, got {result[key]!r}"
        )

    def test_prior_year_comparative_gets_own_label(self, conn):
        """Each period_end gets its own M/D/YY label."""
        facts = [
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2024-10-01",
                period_end="2024-12-31",
                value=9_000_000_000.0,
                fiscal_year=2025,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2025-02-01",
                accession_no="0000123456-25-000001",
            ),
            # Prior-year Q1 filed as a separate 10-Q with the correct fiscal_year stamp
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2023-10-01",
                period_end="2023-12-31",
                value=8_000_000_000.0,
                fiscal_year=2024,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2024-02-01",
                accession_no="0000123456-24-000001",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)

        assert result.get(("operating_income", "12/31/24")) == pytest.approx(9_000_000_000.0)
        assert result.get(("operating_income", "12/31/23")) == pytest.approx(8_000_000_000.0)


# ---------------------------------------------------------------------------
# Bug #3 — fetch_all_metrics preserves derived metrics after LTM injection
# ---------------------------------------------------------------------------

class TestFetchAllMetricsDerivedPreserved:
    """
    The old code called pool = _pool_from_flat(all_flat, all_periods) after
    adding LTM, wiping all previously computed derived metrics. The fix injects
    LTM incrementally so non-LTM derived values survive.
    """

    def _seed_operating_income_and_da(self, conn):
        """Seed operating_income and depreciation for 3 annual periods."""
        periods = [
            ("2022-10-01", "2023-09-30", 2023, 20_000_000_000.0, "0000123456-23-000001"),
            ("2023-10-01", "2024-09-30", 2024, 22_000_000_000.0, "0000123456-24-000001"),
            ("2024-10-01", "2025-09-30", 2025, 24_000_000_000.0, "0000123456-25-000001"),
        ]
        da_periods = [
            ("2022-10-01", "2023-09-30", 2023, 2_000_000_000.0, "0000123456-23-000002"),
            ("2023-10-01", "2024-09-30", 2024, 2_200_000_000.0, "0000123456-24-000002"),
            ("2024-10-01", "2025-09-30", 2025, 2_400_000_000.0, "0000123456-25-000002"),
        ]
        facts = [
            _fact(
                concept="OperatingIncomeLoss",
                period_start=ps,
                period_end=pe,
                value=val,
                fiscal_year=fy,
                filed_date=f"{fy + 1}-01-01" if fy < 2025 else "2025-11-01",
                accession_no=acc,
            )
            for ps, pe, fy, val, acc in periods
        ] + [
            _fact(
                concept="DepreciationDepletionAndAmortization",
                period_start=ps,
                period_end=pe,
                value=val,
                fiscal_year=fy,
                filed_date=f"{fy + 1}-01-01" if fy < 2025 else "2025-11-01",
                accession_no=acc,
            )
            for ps, pe, fy, val, acc in da_periods
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

    def test_ebitda_not_none_for_annual_periods(self, conn):
        """EBITDA (derived: operating_income + depreciation_amortization) must be
        non-None for historical annual periods — not wiped by LTM pool rebuild."""
        self._seed_operating_income_and_da(conn)

        pool, periods = fetch_all_metrics(conn, CIK, "annual", num_periods=3)

        annual_periods = [p for p in periods if p != "LTM"]
        assert annual_periods, "Expected at least one non-LTM period"

        for p in annual_periods:
            val = pool.get("ebitda", {}).get(p)
            assert val is not None, (
                f"ebitda should not be None for annual period {p!r} (Bug #3)"
            )
            assert val > 0, f"ebitda={val} for {p!r} — expected positive"


# ---------------------------------------------------------------------------
# Bug #4 — YoYGrowth incorrectly detects M/D/YY annual labels as quarterly
# ---------------------------------------------------------------------------

class TestYoYGrowthAnnualDetection:
    """
    YoYGrowth used `not periods[0].startswith('FY')` to detect quarterly mode.
    After switching to M/D/YY labels, '9/30/23' doesn't start with 'FY',
    so is_quarterly=True, lookback=4, and all 4 periods return None.
    Fix: use `any('Q' in p ...)` instead.
    """

    def test_annual_mdyy_labels_produce_growth_values(self):
        periods = ["9/30/22", "9/30/23", "9/30/24", "9/30/25"]
        data = {
            "revenue": {
                "9/30/22": 29_310_000_000.0,
                "9/30/23": 32_653_000_000.0,
                "9/30/24": 35_926_000_000.0,
                "9/30/25": 39_721_000_000.0,
            }
        }
        m = YoYGrowth(
            name="revenue_growth",
            display="Revenue Growth",
            section="revenue",
            fmt="percent",
            metric="revenue",
        )
        result = m.compute(data, periods)

        # First period has no prior → None; rest should be non-None
        assert result["9/30/22"] is None
        assert result["9/30/23"] is not None, "Bug #4: annual YoY growth is None"
        assert result["9/30/24"] is not None
        assert result["9/30/25"] is not None

    def test_annual_growth_value_correct(self):
        periods = ["9/30/23", "9/30/24"]
        data = {
            "revenue": {
                "9/30/23": 32_653_000_000.0,
                "9/30/24": 35_926_000_000.0,
            }
        }
        m = YoYGrowth(
            name="revenue_growth",
            display="Revenue Growth",
            section="revenue",
            fmt="percent",
            metric="revenue",
        )
        result = m.compute(data, periods)

        expected_pct = (35_926 - 32_653) / 32_653 * 100  # ≈ 10.02%
        assert result["9/30/24"] == pytest.approx(expected_pct, rel=0.01)

    def test_quarterly_mdyy_labels_use_lookback_4(self):
        """Quarterly M/D/YY mode (YoY same quarter last year) should use lookback=4."""
        # Quarterly dates: consecutive gaps ~90 days → detected as quarterly
        periods = ["12/31/22", "3/31/23", "6/30/23", "9/30/23", "12/31/23"]
        data = {
            "revenue": {
                "12/31/22": 8_000.0,
                "3/31/23": 8_200.0,
                "6/30/23": 8_400.0,
                "9/30/23": 8_600.0,
                "12/31/23": 9_000.0,
            }
        }
        m = YoYGrowth(
            name="revenue_growth",
            display="Revenue Growth",
            section="revenue",
            fmt="percent",
            metric="revenue",
        )
        result = m.compute(data, periods)

        # First 4 periods have no same-quarter comparison → None
        for p in ["12/31/22", "3/31/23", "6/30/23", "9/30/23"]:
            assert result[p] is None, f"Expected None for {p!r} (no prior-year quarter)"
        # 12/31/23 vs 12/31/22: (9000 - 8000) / 8000 * 100 = 12.5%
        assert result["12/31/23"] == pytest.approx(12.5, rel=0.01)

    def test_legacy_quarterly_yyyyqn_labels_still_work(self):
        """Legacy 'YYYY QN' format is still detected as quarterly (backward compat)."""
        periods = ["2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4", "2024 Q1"]
        data = {
            "revenue": {
                "2023 Q1": 8_000.0,
                "2023 Q2": 8_200.0,
                "2023 Q3": 8_400.0,
                "2023 Q4": 8_600.0,
                "2024 Q1": 9_000.0,
            }
        }
        m = YoYGrowth(
            name="revenue_growth",
            display="Revenue Growth",
            section="revenue",
            fmt="percent",
            metric="revenue",
        )
        result = m.compute(data, periods)

        for p in ["2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4"]:
            assert result[p] is None
        assert result["2024 Q1"] == pytest.approx(12.5, rel=0.01)


# ---------------------------------------------------------------------------
# Bug #5 — capex missing: PaymentsToAcquireProductiveAssets not in mappings
# ---------------------------------------------------------------------------

class TestCapexConceptMapping:
    """PaymentsToAcquireProductiveAssets must map to capex in cash_flow."""

    def test_productive_assets_maps_to_capex(self, conn):
        facts = [
            _fact(
                concept="PaymentsToAcquireProductiveAssets",
                period_start="2024-10-01",
                period_end="2025-09-30",
                value=1_482_000_000.0,
                fiscal_year=2025,
                filed_date="2025-11-01",
                accession_no="0000123456-25-000010",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "cash_flow", "annual", num_periods=5)

        key = ("capex", "9/30/25")
        assert key in result, f"Expected capex in cash_flow results, keys: {list(result.keys())[:10]}"
        assert result[key] == pytest.approx(1_482_000_000.0)


# ---------------------------------------------------------------------------
# Bug #6 — total_equity blank: StockholdersEquityIncluding... not in mappings
# ---------------------------------------------------------------------------

class TestTotalEquityConceptMapping:
    """StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest
    must map to total_equity in balance_sheet."""

    def test_equity_including_noncontrolling_maps_to_total_equity(self, conn):
        facts = [
            _fact(
                concept="StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                period_type="instant",
                period_start=None,
                period_end="2025-09-30",
                value=37_909_000_000.0,
                fiscal_year=2025,
                filed_date="2025-11-01",
                accession_no="0000123456-25-000020",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "balance_sheet", "annual", num_periods=5)

        key = ("total_equity", "9/30/25")
        assert key in result, f"Expected total_equity in balance_sheet results"
        assert result[key] == pytest.approx(37_909_000_000.0)


# ---------------------------------------------------------------------------
# Bug #7 — _fetch_ltm has no recency cutoff, picks decade-old XBRL data
# ---------------------------------------------------------------------------

class TestFetchLtmRecencyCutoff:
    """_fetch_ltm Q1 annual query must exclude filings older than 10 years."""

    def test_stale_filing_excluded(self, conn):
        """A fact filed > 10 years ago must not appear in LTM output."""
        stale = _fact(
            concept="OperatingIncomeLoss",
            period_start="2009-10-01",
            period_end="2010-09-30",
            value=999_999_999_999.0,   # obviously wrong sentinel value
            fiscal_year=2010,
            fiscal_period="FY",
            form="10-K",
            filed_date="2010-11-01",   # filed > 10 years ago
            accession_no="0000123456-10-000001",
        )
        db_mod.bulk_insert_facts(conn, [stale])
        conn.commit()

        ltm = _fetch_ltm(conn, CIK, "income_statement")
        # Stale filing should be filtered out → no operating_income in LTM
        val = ltm.get("operating_income")
        assert val != pytest.approx(999_999_999_999.0), (
            "Bug #7: _fetch_ltm returned a value from a filing > 10 years old"
        )

    def test_recent_filing_included(self, conn):
        """A fact from a recent 10-K must still be picked up by _fetch_ltm."""
        recent = _fact(
            concept="OperatingIncomeLoss",
            period_start="2024-10-01",
            period_end="2025-09-30",
            value=24_000_000_000.0,
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            filed_date="2025-11-01",   # recent
            accession_no="0000123456-25-000030",
        )
        db_mod.bulk_insert_facts(conn, [recent])
        conn.commit()

        ltm = _fetch_ltm(conn, CIK, "income_statement")
        assert ltm.get("operating_income") == pytest.approx(24_000_000_000.0)

    def test_stale_replaced_by_recent(self, conn):
        """When both a stale and a recent 10-K exist, the recent value wins."""
        stale = _fact(
            concept="OperatingIncomeLoss",
            period_start="2009-10-01",
            period_end="2010-09-30",
            value=1.0,   # sentinel
            fiscal_year=2010,
            fiscal_period="FY",
            form="10-K",
            filed_date="2010-11-01",
            accession_no="0000123456-10-000002",
        )
        recent = _fact(
            concept="OperatingIncomeLoss",
            period_start="2024-10-01",
            period_end="2025-09-30",
            value=24_000_000_000.0,
            fiscal_year=2025,
            fiscal_period="FY",
            form="10-K",
            filed_date="2025-11-01",
            accession_no="0000123456-25-000031",
        )
        db_mod.bulk_insert_facts(conn, [stale, recent])
        conn.commit()

        ltm = _fetch_ltm(conn, CIK, "income_statement")
        assert ltm.get("operating_income") == pytest.approx(24_000_000_000.0)


# ---------------------------------------------------------------------------
# Bug #8 — interest_expense blank: InterestExpenseNonoperating not in mappings
# ---------------------------------------------------------------------------

class TestInterestExpenseConceptMapping:
    """InterestExpenseNonoperating must map to interest_expense in income_statement."""

    def test_nonoperating_interest_maps_to_interest_expense(self, conn):
        facts = [
            _fact(
                concept="InterestExpenseNonoperating",
                period_start="2024-10-01",
                period_end="2025-09-30",
                value=589_000_000.0,
                fiscal_year=2025,
                filed_date="2025-11-01",
                accession_no="0000123456-25-000040",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "income_statement", "annual", num_periods=5)

        key = ("interest_expense", "9/30/25")
        assert key in result, f"Expected interest_expense in income_statement results"
        assert result[key] == pytest.approx(589_000_000.0)


# ---------------------------------------------------------------------------
# Bug #2 — Quarterly income statement shows YTD cumulative, not standalone quarter
# ---------------------------------------------------------------------------

class TestQuarterlyYtdToStandalone:
    """
    EDGAR Q2 and Q3 facts are YTD (6-month and 9-month cumulative).
    Fix: subtract prior-quarter YTD via LAG to yield standalone values.
    Q1 is already standalone (LAG = 0), instant metrics are never subtracted.
    """

    def _seed_ytd(self, conn, fiscal_year=2025, fy_start="2024-10-01"):
        """Seed Q1/Q2/Q3 YTD revenue and total_assets for one fiscal year."""
        facts = [
            # Q1 YTD = Q1 standalone = 9000M
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2024-12-31",
                value=9_000_000_000.0,
                fiscal_year=fiscal_year,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2025-02-01",
                accession_no="0000123456-25-000101",
            ),
            # Q2 YTD = 19000M  →  standalone = 19000 - 9000 = 10000M
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2025-03-31",
                value=19_000_000_000.0,
                fiscal_year=fiscal_year,
                fiscal_period="Q2",
                form="10-Q",
                filed_date="2025-05-01",
                accession_no="0000123456-25-000102",
            ),
            # Q3 YTD = 29000M  →  standalone = 29000 - 19000 = 10000M
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2025-06-30",
                value=29_000_000_000.0,
                fiscal_year=fiscal_year,
                fiscal_period="Q3",
                form="10-Q",
                filed_date="2025-08-01",
                accession_no="0000123456-25-000103",
            ),
            # Balance sheet (instant) — should NOT be subtracted
            _fact(
                concept="Assets",
                period_type="instant",
                period_start=None,
                period_end="2024-12-31",
                value=91_888_000_000.0,
                fiscal_year=fiscal_year,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2025-02-01",
                accession_no="0000123456-25-000104",
            ),
            _fact(
                concept="Assets",
                period_type="instant",
                period_start=None,
                period_end="2025-03-31",
                value=92_853_000_000.0,
                fiscal_year=fiscal_year,
                fiscal_period="Q2",
                form="10-Q",
                filed_date="2025-05-01",
                accession_no="0000123456-25-000105",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

    def test_q1_standalone_unchanged(self, conn):
        """Q1 value is already standalone — LAG subtracts 0."""
        self._seed_ytd(conn)
        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)
        assert result.get(("operating_income", "12/31/24")) == pytest.approx(9_000_000_000.0)

    def test_q2_ytd_converted_to_standalone(self, conn):
        """Q2 YTD 19000M minus Q1 YTD 9000M = standalone 10000M."""
        self._seed_ytd(conn)
        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)
        assert result.get(("operating_income", "3/31/25")) == pytest.approx(10_000_000_000.0), (
            "Bug #2: Q2 should be standalone 10B, not YTD 19B"
        )

    def test_q3_ytd_converted_to_standalone(self, conn):
        """Q3 YTD 29000M minus Q2 YTD 19000M = standalone 10000M."""
        self._seed_ytd(conn)
        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)
        assert result.get(("operating_income", "6/30/25")) == pytest.approx(10_000_000_000.0), (
            "Bug #2: Q3 should be standalone 10B, not YTD 29B"
        )

    def test_instant_metric_not_subtracted(self, conn):
        """Balance sheet snapshots must be used directly, not YTD-subtracted."""
        self._seed_ytd(conn)
        result, _ = _fetch_facts(conn, CIK, "balance_sheet", "quarterly", num_periods=5)
        assert result.get(("total_assets", "12/31/24")) == pytest.approx(91_888_000_000.0)
        assert result.get(("total_assets", "3/31/25")) == pytest.approx(92_853_000_000.0)

    def test_period_labels_use_period_end_date(self, conn):
        """Quarterly column labels must be M/D/YY of period_end, not 'YYYY QN'."""
        self._seed_ytd(conn)
        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=5)
        labels = {p for (_, p) in result.keys()}
        assert "12/31/24" in labels
        assert "3/31/25" in labels
        assert not any("Q" in p for p in labels), (
            f"Expected no 'YYYY QN' labels, got {labels}"
        )

    def test_standalone_across_two_fiscal_years(self, conn):
        """YTD subtraction is scoped per fiscal year — no cross-year contamination."""
        # FY2024: Q3 YTD = 27000M  →  standalone Q3 = 9000M
        prior_facts = [
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2023-10-01",
                period_end="2023-12-31",
                value=8_500_000_000.0,
                fiscal_year=2024,
                fiscal_period="Q1",
                form="10-Q",
                filed_date="2024-02-01",
                accession_no="0000123456-24-000101",
            ),
            _fact(
                concept="OperatingIncomeLoss",
                period_start="2023-10-01",
                period_end="2024-03-31",
                value=17_500_000_000.0,
                fiscal_year=2024,
                fiscal_period="Q2",
                form="10-Q",
                filed_date="2024-05-01",
                accession_no="0000123456-24-000102",
            ),
        ]
        db_mod.bulk_insert_facts(conn, prior_facts)
        self._seed_ytd(conn)  # FY2025 data

        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=8)

        # FY2024 Q2 standalone = 17500 - 8500 = 9000M
        assert result.get(("operating_income", "3/31/24")) == pytest.approx(9_000_000_000.0)
        # FY2025 Q2 standalone = 19000 - 9000 = 10000M (not affected by FY2024 values)
        assert result.get(("operating_income", "3/31/25")) == pytest.approx(10_000_000_000.0)

    def test_q4_from_10k_included_in_quarterly_series(self, conn):
        """Fiscal year-end (9/30) period from 10-K must appear in quarterly output as Q4."""
        # Three 10-Q rows (Q1, Q2, Q3 YTD) + one 10-K FY row (= Q4 via LAG)
        fy_start = "2024-10-01"
        facts = [
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2024-12-31",
                value=9_000_000_000.0,
                fiscal_year=2025, fiscal_period="Q1",
                form="10-Q", filed_date="2025-02-01",
                accession_no="0000123456-25-000201",
            ),
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2025-03-31",
                value=19_000_000_000.0,
                fiscal_year=2025, fiscal_period="Q2",
                form="10-Q", filed_date="2025-05-01",
                accession_no="0000123456-25-000202",
            ),
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2025-06-30",
                value=29_000_000_000.0,
                fiscal_year=2025, fiscal_period="Q3",
                form="10-Q", filed_date="2025-08-01",
                accession_no="0000123456-25-000203",
            ),
            # 10-K annual FY row — should become Q4 standalone = 40000 - 29000 = 11000M
            _fact(
                concept="OperatingIncomeLoss",
                period_start=fy_start,
                period_end="2025-09-30",
                value=40_000_000_000.0,
                fiscal_year=2025, fiscal_period="FY",
                form="10-K", filed_date="2025-11-15",
                accession_no="0000123456-25-000204",
            ),
        ]
        db_mod.bulk_insert_facts(conn, facts)
        conn.commit()

        result, _ = _fetch_facts(conn, CIK, "income_statement", "quarterly", num_periods=8)

        # Q4 label = period_end "9/30/25"
        key = ("operating_income", "9/30/25")
        assert key in result, "9/30 (Q4) period must appear in quarterly series"
        assert result[key] == pytest.approx(11_000_000_000.0), (
            f"Q4 standalone = Annual(40B) - Q3_YTD(29B) = 11B, got {result[key]!r}"
        )
