"""
Tests for sec_edgar/annotation_defs.py — consistency and cross-module checks.
Verifies that all annotation references resolve to real computed metrics.
"""

import pytest

from sec_edgar.annotation_defs import get_annotations, _MAP
from sec_edgar.ratio_defs import ALL_COMPUTED


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ALL_COMPUTED_NAMES = {m.name for m in ALL_COMPUTED}
ALL_COMPUTED_BY_NAME = {m.name: m for m in ALL_COMPUTED}

STATEMENTS = ("income_statement", "balance_sheet", "cash_flow")
PERIODS = ("annual", "quarterly")


# ---------------------------------------------------------------------------
# get_annotations returns dict for all valid keys
# ---------------------------------------------------------------------------

class TestGetAnnotations:
    def test_all_combinations_return_dict(self):
        for stmt in STATEMENTS:
            for period in PERIODS:
                result = get_annotations(stmt, period)
                assert isinstance(result, dict), f"Expected dict for ({stmt}, {period})"

    def test_unknown_statement_returns_empty(self):
        assert get_annotations("profit_loss", "annual") == {}

    def test_unknown_period_returns_empty(self):
        assert get_annotations("income_statement", "monthly") == {}

    def test_both_unknown_returns_empty(self):
        assert get_annotations("unknown", "unknown") == {}


# ---------------------------------------------------------------------------
# All annotation metric names exist in ALL_COMPUTED
# ---------------------------------------------------------------------------

class TestAnnotationMetricsExist:
    @pytest.mark.parametrize("key", list(_MAP.keys()))
    def test_annotation_metrics_in_all_computed(self, key):
        mapping = _MAP[key]
        for parent, ann_names in mapping.items():
            for ann_name in ann_names:
                assert ann_name in ALL_COMPUTED_NAMES, (
                    f"Annotation '{ann_name}' (after parent '{parent}' in {key}) "
                    f"not found in ALL_COMPUTED"
                )


# ---------------------------------------------------------------------------
# All annotation metrics have a usable fmt
# ---------------------------------------------------------------------------

class TestAnnotationMetricFormats:
    VALID_FMTS = {"percent", "times", "multiple", "days", "currency",
                  "currency_per_share", "raw"}

    @pytest.mark.parametrize("key", list(_MAP.keys()))
    def test_annotation_metrics_have_valid_fmt(self, key):
        mapping = _MAP[key]
        for parent, ann_names in mapping.items():
            for ann_name in ann_names:
                if ann_name in ALL_COMPUTED_BY_NAME:
                    fmt = ALL_COMPUTED_BY_NAME[ann_name].fmt
                    assert fmt in self.VALID_FMTS, (
                        f"Metric '{ann_name}' has unrecognised fmt='{fmt}'"
                    )


# ---------------------------------------------------------------------------
# Quarterly is a superset of annual (never removes, only adds)
# ---------------------------------------------------------------------------

class TestQuarterlyIsSupersetOfAnnual:
    @pytest.mark.parametrize("stmt", STATEMENTS)
    def test_quarterly_superset(self, stmt):
        annual = get_annotations(stmt, "annual")
        quarterly = get_annotations(stmt, "quarterly")
        for parent, ann_names in annual.items():
            assert parent in quarterly, (
                f"Parent metric '{parent}' present in annual but missing in quarterly "
                f"for {stmt}"
            )
            for ann in ann_names:
                assert ann in quarterly[parent], (
                    f"Annotation '{ann}' in annual/{stmt} but missing from quarterly/{stmt}"
                )


# ---------------------------------------------------------------------------
# Annotation values are lists of strings
# ---------------------------------------------------------------------------

class TestAnnotationStructure:
    @pytest.mark.parametrize("key", list(_MAP.keys()))
    def test_values_are_lists_of_strings(self, key):
        mapping = _MAP[key]
        for parent, ann_names in mapping.items():
            assert isinstance(ann_names, list), (
                f"Expected list for parent '{parent}' in {key}, got {type(ann_names)}"
            )
            for ann in ann_names:
                assert isinstance(ann, str) and ann, (
                    f"Expected non-empty string in annotation list for '{parent}' in {key}"
                )


# ---------------------------------------------------------------------------
# Spot-check known expected annotations
# ---------------------------------------------------------------------------

class TestKnownAnnotations:
    def test_income_statement_annual_revenue(self):
        ann = get_annotations("income_statement", "annual")
        assert "revenue" in ann
        assert "revenue_growth" in ann["revenue"]

    def test_income_statement_quarterly_revenue_has_qoq(self):
        ann = get_annotations("income_statement", "quarterly")
        assert "revenue" in ann
        assert "revenue_qoq" in ann["revenue"]

    def test_cash_flow_annual_cf_operating(self):
        ann = get_annotations("cash_flow", "annual")
        assert "cf_operating" in ann
        assert "operating_cf_margin" in ann["cf_operating"]
        assert "cf_operating_yoy" in ann["cf_operating"]

    def test_cash_flow_quarterly_has_qoq(self):
        ann = get_annotations("cash_flow", "quarterly")
        assert "cf_operating_qoq" in ann["cf_operating"]
        assert "fcf_qoq" in ann["free_cash_flow"]

    def test_balance_sheet_equity_ratios(self):
        ann = get_annotations("balance_sheet", "annual")
        assert "total_equity" in ann
        equity_anns = ann["total_equity"]
        assert "roe" in equity_anns
        assert "book_value_per_share" in equity_anns
        assert "debt_to_equity" in equity_anns

    def test_balance_sheet_liquidity_ratios(self):
        ann = get_annotations("balance_sheet", "annual")
        assert "total_current_assets" in ann
        assert "current_ratio" in ann["total_current_assets"]
        assert "quick_ratio" in ann["total_current_assets"]
        assert "cash_ratio" in ann["total_current_assets"]

    def test_sbc_dividend_repurchase_margins(self):
        for period in ("annual", "quarterly"):
            ann = get_annotations("cash_flow", period)
            assert "sbc_margin" in ann.get("cf_stock_compensation", [])
            assert "repurchase_margin" in ann.get("share_repurchases", [])
            assert "dividend_margin" in ann.get("dividends_paid", [])
