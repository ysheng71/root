"""
Tests for formatting helpers in sec_edgar/reports.py.
All pure functions — no I/O, no database.
"""

import pytest

from sec_edgar.reports import (
    _fmt_value,
    _fmt_ratio_value,
    _period_sort_key,
    _ordered_periods,
)


# ---------------------------------------------------------------------------
# _fmt_value
# ---------------------------------------------------------------------------

class TestFmtValue:
    SCALE = 1_000_000  # millions

    def test_none_returns_dash(self):
        assert _fmt_value(None, "USD", self.SCALE) == "—"

    # USD
    def test_usd_large_no_decimal(self):
        # 2_500_000_000 / 1e6 = 2500.0 → ≥ 1000 → no decimal
        assert _fmt_value(2_500_000_000, "USD", self.SCALE) == "2,500"

    def test_usd_small_one_decimal(self):
        # 500_000_000 / 1e6 = 500.0 → < 1000 → one decimal
        assert _fmt_value(500_000_000, "USD", self.SCALE) == "500.0"

    def test_usd_negative(self):
        assert _fmt_value(-1_000_000_000, "USD", self.SCALE) == "-1,000"

    def test_usd_raw_scale(self):
        assert _fmt_value(1_234.0, "USD", 1) == "1,234"

    # shares
    def test_shares_in_millions(self):
        # 16_000_000_000 / 1e6 = 16000.0M
        result = _fmt_value(16_000_000_000, "shares", self.SCALE)
        assert "M" in result
        assert "16,000" in result

    # USD/shares (EPS)
    def test_usd_per_share_two_decimals(self):
        assert _fmt_value(6.11, "USD/shares", self.SCALE) == "6.11"

    def test_usd_per_share_not_scaled(self):
        # Scale should be ignored for USD/shares
        assert _fmt_value(6.11, "USD/shares", 1) == "6.11"
        assert _fmt_value(6.11, "USD/shares", 1_000_000) == "6.11"


# ---------------------------------------------------------------------------
# _fmt_ratio_value
# ---------------------------------------------------------------------------

class TestFmtRatioValue:
    SCALE = 1_000_000

    def test_none_returns_dash(self):
        assert _fmt_ratio_value(None, "percent", self.SCALE) == "—"

    # percent — values already in percentage points
    def test_percent_one_decimal(self):
        assert _fmt_ratio_value(23.4, "percent", self.SCALE) == "23.4%"

    def test_percent_negative(self):
        assert _fmt_ratio_value(-5.2, "percent", self.SCALE) == "-5.2%"

    def test_percent_large_zero_decimal(self):
        assert _fmt_ratio_value(1500.0, "percent", self.SCALE) == "1500%"

    def test_percent_not_scaled(self):
        # percent values are already in pct points; scale should not affect them
        assert _fmt_ratio_value(25.0, "percent", 1) == "25.0%"
        assert _fmt_ratio_value(25.0, "percent", 1_000_000_000) == "25.0%"

    # times / multiple
    def test_times_appends_x(self):
        assert _fmt_ratio_value(2.5, "times", self.SCALE) == "2.5x"

    def test_multiple_appends_x(self):
        assert _fmt_ratio_value(18.3, "multiple", self.SCALE) == "18.3x"

    # days
    def test_days_integer(self):
        assert _fmt_ratio_value(45.7, "days", self.SCALE) == "46"

    def test_days_zero(self):
        assert _fmt_ratio_value(0.0, "days", self.SCALE) == "0"

    # currency (scaled)
    def test_currency_large(self):
        # 2_000_000_000 / 1e6 = 2000 → no decimal
        assert _fmt_ratio_value(2_000_000_000, "currency", self.SCALE) == "2,000"

    def test_currency_small(self):
        # 500_000_000 / 1e6 = 500.0 → one decimal
        assert _fmt_ratio_value(500_000_000, "currency", self.SCALE) == "500.0"

    # currency_per_share
    def test_currency_per_share(self):
        assert _fmt_ratio_value(3.87, "currency_per_share", self.SCALE) == "$3.87"

    def test_currency_per_share_not_scaled(self):
        assert _fmt_ratio_value(3.87, "currency_per_share", 1) == "$3.87"
        assert _fmt_ratio_value(3.87, "currency_per_share", 1_000_000) == "$3.87"


# ---------------------------------------------------------------------------
# _period_sort_key
# ---------------------------------------------------------------------------

class TestPeriodSortKey:
    def test_annual_ordering(self):
        periods = ["FY2024", "FY2021", "FY2023", "FY2022"]
        assert sorted(periods, key=_period_sort_key) == [
            "FY2021", "FY2022", "FY2023", "FY2024"
        ]

    def test_quarterly_ordering(self):
        periods = ["2024 Q1", "2023 Q3", "2024 Q2", "2023 Q4"]
        assert sorted(periods, key=_period_sort_key) == [
            "2023 Q3", "2023 Q4", "2024 Q1", "2024 Q2"
        ]

    def test_annual_before_later_annual(self):
        assert _period_sort_key("FY2020") < _period_sort_key("FY2021")

    def test_q4_before_next_q1(self):
        assert _period_sort_key("2023 Q4") < _period_sort_key("2024 Q1")


# ---------------------------------------------------------------------------
# _ordered_periods
# ---------------------------------------------------------------------------

class TestOrderedPeriods:
    def _make_facts(self, period_labels):
        """Create a minimal facts dict with given period labels."""
        return {("revenue", p): 100.0 for p in period_labels}

    def test_caps_at_num_periods(self):
        labels = [f"FY{y}" for y in range(2018, 2025)]  # 7 years
        facts = self._make_facts(labels)
        result = _ordered_periods(facts, "annual", 5)
        assert len(result) == 5

    def test_keeps_most_recent(self):
        labels = [f"FY{y}" for y in range(2018, 2025)]
        facts = self._make_facts(labels)
        result = _ordered_periods(facts, "annual", 3)
        assert result == ["FY2022", "FY2023", "FY2024"]

    def test_ordered_oldest_to_newest(self):
        labels = ["FY2022", "FY2020", "FY2021"]
        facts = self._make_facts(labels)
        result = _ordered_periods(facts, "annual", 10)
        assert result == ["FY2020", "FY2021", "FY2022"]

    def test_fewer_periods_than_requested(self):
        labels = ["FY2023", "FY2024"]
        facts = self._make_facts(labels)
        result = _ordered_periods(facts, "annual", 5)
        assert result == ["FY2023", "FY2024"]

    def test_quarterly_ordering(self):
        labels = ["2023 Q3", "2024 Q1", "2023 Q4"]
        facts = self._make_facts(labels)
        result = _ordered_periods(facts, "quarterly", 10)
        assert result == ["2023 Q3", "2023 Q4", "2024 Q1"]
