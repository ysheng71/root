"""
Tests for sec_edgar/computed.py — ComputedMetric subclasses and RatioEngine.
All tests are pure (no I/O, no database).
"""

import math
import pytest

from sec_edgar.computed import (
    _safe_div,
    _safe_growth,
    _get,
    AvgDenominatorRatio,
    CAGR,
    DaysMetric,
    MarketRatio,
    QoQGrowth,
    Ratio,
    RatioEngine,
    Sum,
    YoYGrowth,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _ratio(name="r", num="a", den="b", scale=1.0):
    return Ratio(name, name, "section", "times", numerator=num, denominator=den, scale=scale)


def _fy_periods(n):
    return [f"FY{2020 + i}" for i in range(n)]


def _q_periods(n):
    """Generate quarterly period labels: '2023 Q1', '2023 Q2', ..."""
    labels = []
    year, q = 2023, 1
    for _ in range(n):
        labels.append(f"{year} Q{q}")
        q += 1
        if q > 4:
            q = 1
            year += 1
    return labels


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------

class TestSafeDiv:
    def test_normal(self):
        assert _safe_div(10.0, 4.0) == pytest.approx(2.5)

    def test_scale_applied(self):
        assert _safe_div(1.0, 4.0, scale=100) == pytest.approx(25.0)

    def test_zero_denominator(self):
        assert _safe_div(10.0, 0.0) is None

    def test_numerator_none(self):
        assert _safe_div(None, 4.0) is None

    def test_denominator_none(self):
        assert _safe_div(10.0, None) is None

    def test_both_none(self):
        assert _safe_div(None, None) is None

    def test_nan_result_returns_none(self):
        # Force nan by dividing 0/0 after overriding zero check — use inf path instead
        assert _safe_div(float("inf"), 1.0) is None

    def test_negative_values(self):
        assert _safe_div(-6.0, 2.0) == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# _safe_growth
# ---------------------------------------------------------------------------

class TestSafeGrowth:
    def test_normal_growth(self):
        # (110 - 100) / 100 = 0.10
        assert _safe_growth(110.0, 100.0) == pytest.approx(0.10)

    def test_negative_growth(self):
        assert _safe_growth(90.0, 100.0) == pytest.approx(-0.10)

    def test_zero_previous(self):
        assert _safe_growth(10.0, 0.0) is None

    def test_current_none(self):
        assert _safe_growth(None, 100.0) is None

    def test_previous_none(self):
        assert _safe_growth(100.0, None) is None

    def test_both_none(self):
        assert _safe_growth(None, None) is None

    def test_uses_abs_of_previous(self):
        # previous is -100: (50 - (-100)) / |-100| = 150/100 = 1.5
        assert _safe_growth(50.0, -100.0) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# _get
# ---------------------------------------------------------------------------

class TestGet:
    def test_present(self):
        data = {"revenue": {"FY2023": 100.0}}
        assert _get(data, "revenue", "FY2023") == 100.0

    def test_missing_metric(self):
        assert _get({}, "revenue", "FY2023") is None

    def test_missing_period(self):
        data = {"revenue": {"FY2023": 100.0}}
        assert _get(data, "revenue", "FY2022") is None

    def test_none_value(self):
        data = {"revenue": {"FY2023": None}}
        assert _get(data, "revenue", "FY2023") is None


# ---------------------------------------------------------------------------
# Ratio
# ---------------------------------------------------------------------------

class TestRatio:
    def test_basic(self):
        data = {"a": {"FY2023": 30.0}, "b": {"FY2023": 100.0}}
        r = _ratio(scale=100)
        result = r.compute(data, ["FY2023"])
        assert result["FY2023"] == pytest.approx(30.0)

    def test_missing_denominator(self):
        data = {"a": {"FY2023": 30.0}, "b": {"FY2023": None}}
        result = _ratio().compute(data, ["FY2023"])
        assert result["FY2023"] is None

    def test_missing_numerator(self):
        data = {"a": {"FY2023": None}, "b": {"FY2023": 100.0}}
        result = _ratio().compute(data, ["FY2023"])
        assert result["FY2023"] is None

    def test_multiple_periods(self):
        data = {
            "a": {"FY2022": 20.0, "FY2023": 30.0},
            "b": {"FY2022": 100.0, "FY2023": 150.0},
        }
        result = _ratio(scale=100).compute(data, ["FY2022", "FY2023"])
        assert result["FY2022"] == pytest.approx(20.0)
        assert result["FY2023"] == pytest.approx(20.0)

    def test_dependencies(self):
        r = _ratio(num="revenue", den="total_assets")
        assert "revenue" in r.dependencies
        assert "total_assets" in r.dependencies


# ---------------------------------------------------------------------------
# Sum
# ---------------------------------------------------------------------------

class TestSum:
    def test_addition(self):
        data = {"a": {"FY2023": 60.0}, "b": {"FY2023": 40.0}}
        s = Sum("s", "s", "section", "currency", terms=[(1.0, "a"), (1.0, "b")])
        assert s.compute(data, ["FY2023"])["FY2023"] == pytest.approx(100.0)

    def test_subtraction(self):
        data = {"a": {"FY2023": 100.0}, "b": {"FY2023": 30.0}}
        s = Sum("s", "s", "section", "currency", terms=[(1.0, "a"), (-1.0, "b")])
        assert s.compute(data, ["FY2023"])["FY2023"] == pytest.approx(70.0)

    def test_none_propagates(self):
        data = {"a": {"FY2023": 100.0}, "b": {"FY2023": None}}
        s = Sum("s", "s", "section", "currency", terms=[(1.0, "a"), (1.0, "b")])
        assert s.compute(data, ["FY2023"])["FY2023"] is None

    def test_weighted(self):
        data = {"a": {"FY2023": 10.0}, "b": {"FY2023": 5.0}}
        s = Sum("s", "s", "section", "currency", terms=[(2.0, "a"), (3.0, "b")])
        assert s.compute(data, ["FY2023"])["FY2023"] == pytest.approx(35.0)

    def test_dependencies(self):
        s = Sum("s", "s", "section", "currency", terms=[(1.0, "x"), (-1.0, "y")])
        assert s.dependencies == ["x", "y"]


# ---------------------------------------------------------------------------
# AvgDenominatorRatio
# ---------------------------------------------------------------------------

class TestAvgDenominatorRatio:
    def _make(self, num="ni", den="equity"):
        return AvgDenominatorRatio("roe", "ROE", "section", "percent",
                                   numerator=num, denominator=den, scale=100)

    def test_first_period_uses_current(self):
        data = {"ni": {"FY2022": 10.0}, "equity": {"FY2022": 100.0}}
        result = self._make().compute(data, ["FY2022"])
        assert result["FY2022"] == pytest.approx(10.0)  # 10/100 * 100

    def test_second_period_uses_average(self):
        # avg equity = (100 + 200) / 2 = 150; 30 / 150 * 100 = 20
        data = {
            "ni":     {"FY2022": 10.0, "FY2023": 30.0},
            "equity": {"FY2022": 100.0, "FY2023": 200.0},
        }
        result = self._make().compute(data, ["FY2022", "FY2023"])
        assert result["FY2023"] == pytest.approx(20.0)

    def test_missing_numerator(self):
        data = {"ni": {"FY2022": None}, "equity": {"FY2022": 100.0}}
        result = self._make().compute(data, ["FY2022"])
        assert result["FY2022"] is None


# ---------------------------------------------------------------------------
# DaysMetric
# ---------------------------------------------------------------------------

class TestDaysMetric:
    def _make(self):
        return DaysMetric("dso", "DSO", "section", "days",
                          numerator="ar", denominator="rev")

    def test_annual_uses_365(self):
        data = {"ar": {"FY2023": 365.0}, "rev": {"FY2023": 1000.0}}
        result = self._make().compute(data, ["FY2023"])
        assert result["FY2023"] == pytest.approx(365 * 365 / 1000)

    def test_quarterly_uses_91(self):
        data = {"ar": {"2023 Q1": 91.0}, "rev": {"2023 Q1": 1000.0}}
        result = self._make().compute(data, ["2023 Q1"])
        assert result["2023 Q1"] == pytest.approx(91 * 91 / 1000)

    def test_missing_value_returns_none(self):
        data = {"ar": {"FY2023": None}, "rev": {"FY2023": 1000.0}}
        assert self._make().compute(data, ["FY2023"])["FY2023"] is None


# ---------------------------------------------------------------------------
# YoYGrowth
# ---------------------------------------------------------------------------

class TestYoYGrowth:
    def _make(self, metric="revenue"):
        return YoYGrowth("rev_growth", "Revenue Growth", "section", "percent", metric=metric)

    def test_annual_first_period_is_none(self):
        data = {"revenue": {"FY2022": 100.0, "FY2023": 110.0}}
        result = self._make().compute(data, ["FY2022", "FY2023"])
        assert result["FY2022"] is None

    def test_annual_compares_previous_period(self):
        # (110 - 100) / 100 * 100 = 10.0 percentage points
        data = {"revenue": {"FY2022": 100.0, "FY2023": 110.0}}
        result = self._make().compute(data, ["FY2022", "FY2023"])
        assert result["FY2023"] == pytest.approx(10.0)

    def test_quarterly_first_four_are_none(self):
        periods = _q_periods(8)
        data = {"revenue": {p: 100.0 + i * 5 for i, p in enumerate(periods)}}
        result = self._make().compute(data, periods)
        for p in periods[:4]:
            assert result[p] is None

    def test_quarterly_fifth_compares_four_back(self):
        # periods[4] vs periods[0]
        periods = _q_periods(8)
        vals = {p: float(100 + i * 10) for i, p in enumerate(periods)}
        data = {"revenue": vals}
        result = self._make().compute(data, periods)
        p0, p4 = periods[0], periods[4]
        expected = (vals[p4] - vals[p0]) / abs(vals[p0]) * 100
        assert result[p4] == pytest.approx(expected)

    def test_result_in_percentage_points(self):
        data = {"revenue": {"FY2022": 100.0, "FY2023": 200.0}}
        result = self._make().compute(data, ["FY2022", "FY2023"])
        assert result["FY2023"] == pytest.approx(100.0)  # 100%, not 1.0

    def test_missing_value_returns_none(self):
        data = {"revenue": {"FY2022": None, "FY2023": 110.0}}
        result = self._make().compute(data, ["FY2022", "FY2023"])
        assert result["FY2023"] is None


# ---------------------------------------------------------------------------
# QoQGrowth
# ---------------------------------------------------------------------------

class TestQoQGrowth:
    def _make(self):
        return QoQGrowth("rev_qoq", "Revenue QoQ", "section", "percent", metric="revenue")

    def test_first_period_is_none(self):
        periods = _q_periods(4)
        data = {"revenue": {p: 100.0 for p in periods}}
        result = self._make().compute(data, periods)
        assert result[periods[0]] is None

    def test_always_looks_back_one(self):
        periods = _q_periods(5)
        vals = {p: float(100 + i * 10) for i, p in enumerate(periods)}
        data = {"revenue": vals}
        result = self._make().compute(data, periods)
        # period[4] vs period[3]
        p3, p4 = periods[3], periods[4]
        expected = (vals[p4] - vals[p3]) / abs(vals[p3]) * 100
        assert result[p4] == pytest.approx(expected)

    def test_annual_labels_still_use_lookback_one(self):
        # QoQ is always sequential, even with FY labels
        data = {"revenue": {"FY2021": 100.0, "FY2022": 120.0}}
        result = self._make().compute(data, ["FY2021", "FY2022"])
        assert result["FY2021"] is None
        assert result["FY2022"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------

class TestCAGR:
    def _make(self):
        return CAGR("rev_cagr", "Revenue CAGR", "section", "percent", metric="revenue")

    def test_value_only_in_last_period(self):
        periods = _fy_periods(4)
        data = {"revenue": {p: float(100 * (1.1 ** i)) for i, p in enumerate(periods)}}
        result = self._make().compute(data, periods)
        for p in periods[:-1]:
            assert result[p] is None
        assert result[periods[-1]] is not None

    def test_cagr_calculation(self):
        # 100 → 133.1 over 3 years = 10% CAGR
        periods = _fy_periods(4)
        data = {"revenue": {
            periods[0]: 100.0,
            periods[1]: 110.0,
            periods[2]: 121.0,
            periods[3]: 133.1,
        }}
        result = self._make().compute(data, periods)
        assert result[periods[-1]] == pytest.approx(10.0, abs=0.01)

    def test_single_period_all_none(self):
        data = {"revenue": {"FY2023": 100.0}}
        result = self._make().compute(data, ["FY2023"])
        assert result["FY2023"] is None

    def test_negative_first_value_all_none(self):
        periods = _fy_periods(3)
        data = {"revenue": {periods[0]: -100.0, periods[1]: 50.0, periods[2]: 200.0}}
        result = self._make().compute(data, periods)
        assert all(v is None for v in result.values())

    def test_result_in_percentage_points(self):
        periods = _fy_periods(2)
        # 100 → 121 over 1 year = 21% CAGR
        data = {"revenue": {periods[0]: 100.0, periods[1]: 121.0}}
        result = self._make().compute(data, periods)
        assert result[periods[-1]] == pytest.approx(21.0, abs=0.01)


# ---------------------------------------------------------------------------
# MarketRatio
# ---------------------------------------------------------------------------

class TestMarketRatio:
    def test_no_price_all_none(self):
        m = MarketRatio("pe", "P/E", "section", "multiple",
                        market_numerator="market_cap", denominator="net_income")
        data = {"shares_diluted": {"FY2023": 1e9}, "net_income": {"FY2023": 5e9}}
        result = m.compute(data, ["FY2023"], price=None)
        assert result["FY2023"] is None

    def test_market_cap_numerator(self):
        # market_cap = price * shares; pe = market_cap / net_income
        # price=10, shares=1e9 → market_cap=10e9; net_income=2e9 → pe=5
        m = MarketRatio("pe", "P/E", "section", "multiple",
                        market_numerator="market_cap", denominator="net_income")
        data = {"shares_diluted": {"FY2023": 1e9}, "net_income": {"FY2023": 2e9}}
        result = m.compute(data, ["FY2023"], price=10.0)
        assert result["FY2023"] == pytest.approx(5.0)

    def test_enterprise_value_numerator(self):
        m = MarketRatio("ev_ebitda", "EV/EBITDA", "section", "multiple",
                        market_numerator="enterprise_value", denominator="ebitda")
        data = {"enterprise_value": {"FY2023": 100e9}, "ebitda": {"FY2023": 10e9}}
        result = m.compute(data, ["FY2023"], price=10.0)
        assert result["FY2023"] == pytest.approx(10.0)

    def test_direct_metric_numerator(self):
        m = MarketRatio("fcf_yield", "FCF Yield", "section", "percent",
                        market_numerator="free_cash_flow", denominator="market_cap", scale=100)
        data = {
            "free_cash_flow": {"FY2023": 20e9},
            "market_cap": {"FY2023": 100e9},
            "shares_diluted": {"FY2023": 1e9},
        }
        result = m.compute(data, ["FY2023"], price=10.0)
        assert result["FY2023"] == pytest.approx(20.0)

    def test_missing_shares_returns_none(self):
        m = MarketRatio("pe", "P/E", "section", "multiple",
                        market_numerator="market_cap", denominator="net_income")
        data = {"shares_diluted": {"FY2023": None}, "net_income": {"FY2023": 5e9}}
        result = m.compute(data, ["FY2023"], price=10.0)
        assert result["FY2023"] is None


# ---------------------------------------------------------------------------
# RatioEngine
# ---------------------------------------------------------------------------

class TestRatioEngine:
    def test_basic_evaluation(self):
        metrics = [
            Ratio("margin", "Margin", "s", "percent",
                  numerator="profit", denominator="revenue", scale=100),
        ]
        data = {"profit": {"FY2023": 30.0}, "revenue": {"FY2023": 100.0}}
        result = RatioEngine().compute_all(metrics, data, ["FY2023"])
        assert result["margin"]["FY2023"] == pytest.approx(30.0)

    def test_chaining(self):
        # net_debt computed first, then net_debt_to_ebitda uses it
        metrics = [
            Sum("net_debt", "Net Debt", "s", "currency",
                terms=[(1.0, "debt"), (-1.0, "cash")]),
            Ratio("nd_ebitda", "ND/EBITDA", "s", "times",
                  numerator="net_debt", denominator="ebitda"),
        ]
        data = {
            "debt":   {"FY2023": 80.0},
            "cash":   {"FY2023": 20.0},
            "ebitda": {"FY2023": 30.0},
        }
        result = RatioEngine().compute_all(metrics, data, ["FY2023"])
        assert result["net_debt"]["FY2023"] == pytest.approx(60.0)
        assert result["nd_ebitda"]["FY2023"] == pytest.approx(2.0)

    def test_original_data_not_mutated(self):
        metrics = [
            Ratio("margin", "Margin", "s", "percent",
                  numerator="profit", denominator="revenue", scale=100),
        ]
        data = {"profit": {"FY2023": 30.0}, "revenue": {"FY2023": 100.0}}
        original_keys = set(data.keys())
        RatioEngine().compute_all(metrics, data, ["FY2023"])
        assert set(data.keys()) == original_keys

    def test_exception_in_metric_fills_none(self):
        class BadMetric(Ratio):
            def compute(self, data, periods, price=None):
                raise ValueError("boom")

        metrics = [BadMetric("bad", "Bad", "s", "times", numerator="a", denominator="b")]
        data = {"a": {"FY2023": 1.0}, "b": {"FY2023": 1.0}}
        result = RatioEngine().compute_all(metrics, data, ["FY2023"])
        assert result["bad"]["FY2023"] is None

    def test_multiple_periods(self):
        metrics = [
            YoYGrowth("rev_growth", "Rev Growth", "s", "percent", metric="revenue"),
        ]
        data = {"revenue": {"FY2022": 100.0, "FY2023": 110.0, "FY2024": 132.0}}
        periods = ["FY2022", "FY2023", "FY2024"]
        result = RatioEngine().compute_all(metrics, data, periods)
        assert result["rev_growth"]["FY2022"] is None
        assert result["rev_growth"]["FY2023"] == pytest.approx(10.0)
        assert result["rev_growth"]["FY2024"] == pytest.approx(20.0)
