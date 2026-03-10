"""
Generic computed metric system.

All financial ratios, growth rates, and multi-step derived values are expressed
as subclasses of ComputedMetric. The RatioEngine evaluates them in definition
order against a pool of {metric_name: {period: value}} data.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Type aliases
Data = Dict[str, Dict[str, Optional[float]]]
PeriodValues = Dict[str, Optional[float]]


def _safe_div(
    numerator: Optional[float],
    denominator: Optional[float],
    scale: float = 1.0,
) -> Optional[float]:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    result = (numerator / denominator) * scale
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _safe_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    result = (current - previous) / abs(previous)
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _get(data: Data, name: str, period: str) -> Optional[float]:
    return data.get(name, {}).get(period)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

@dataclass
class ComputedMetric(ABC):
    name: str
    display: str
    section: str
    fmt: str        # "percent" | "times" | "multiple" | "days" | "currency" | "raw"
    indent: int = 0
    sort_order: int = field(default=0, compare=False)

    @property
    def dependencies(self) -> List[str]:
        """Names of metrics this computation reads from the data pool."""
        return []

    @abstractmethod
    def compute(
        self,
        data: Data,
        periods: List[str],
        price: Optional[float] = None,
    ) -> PeriodValues:
        ...


# ---------------------------------------------------------------------------
# Ratio  —  numerator / denominator [× scale]
# ---------------------------------------------------------------------------

@dataclass
class Ratio(ComputedMetric):
    numerator: str = ""
    denominator: str = ""
    scale: float = 1.0

    @property
    def dependencies(self) -> List[str]:
        return [self.numerator, self.denominator]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        return {
            p: _safe_div(_get(data, self.numerator, p),
                         _get(data, self.denominator, p),
                         self.scale)
            for p in periods
        }


# ---------------------------------------------------------------------------
# Sum  —  weighted linear combination: w1·a + w2·b + ...
#         Use negative weights for subtraction.
# ---------------------------------------------------------------------------

@dataclass
class Sum(ComputedMetric):
    terms: List[Tuple[float, str]] = field(default_factory=list)
    # terms: [(weight, metric_name), ...]

    @property
    def dependencies(self) -> List[str]:
        return [m for _, m in self.terms]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        result: PeriodValues = {}
        for p in periods:
            vals = [_get(data, name, p) for _, name in self.terms]
            if any(v is None for v in vals):
                result[p] = None
            else:
                result[p] = sum(w * v for (w, _), v in zip(self.terms, vals))
        return result


# ---------------------------------------------------------------------------
# AvgDenominatorRatio  —  numerator / avg(denominator_t, denominator_{t-1})
#                         Used for ROE, ROA, asset turnover, etc.
# ---------------------------------------------------------------------------

@dataclass
class AvgDenominatorRatio(ComputedMetric):
    numerator: str = ""
    denominator: str = ""
    scale: float = 1.0

    @property
    def dependencies(self) -> List[str]:
        return [self.numerator, self.denominator]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        result: PeriodValues = {}
        for i, p in enumerate(periods):
            n = _get(data, self.numerator, p)
            d_curr = _get(data, self.denominator, p)
            d_prev = _get(data, self.denominator, periods[i - 1]) if i > 0 else None

            if d_curr is not None and d_prev is not None:
                avg_d = (d_curr + d_prev) / 2.0
            else:
                avg_d = d_curr  # fall back to current if no prior period

            result[p] = _safe_div(n, avg_d, self.scale)
        return result


# ---------------------------------------------------------------------------
# DaysMetric  —  (numerator / denominator) × days
#                DSO, DIO, DPO
# ---------------------------------------------------------------------------

@dataclass
class DaysMetric(ComputedMetric):
    numerator: str = ""
    denominator: str = ""
    days_annual: int = 365
    days_quarterly: int = 91

    @property
    def dependencies(self) -> List[str]:
        return [self.numerator, self.denominator]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        # Detect annual vs quarterly from period label
        is_quarterly = periods and not periods[0].startswith("FY")
        days = self.days_quarterly if is_quarterly else self.days_annual
        return {
            p: _safe_div(_get(data, self.numerator, p),
                         _get(data, self.denominator, p),
                         days)
            for p in periods
        }


# ---------------------------------------------------------------------------
# YoYGrowth  —  (a_t − a_{t-1}) / |a_{t-1}|
# QoQGrowth  —  alias; same math, semantic distinction for quarterly mode
# ---------------------------------------------------------------------------

@dataclass
class YoYGrowth(ComputedMetric):
    metric: str = ""
    fmt: str = "percent"

    @property
    def dependencies(self) -> List[str]:
        return [self.metric]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        result: PeriodValues = {}
        for i, p in enumerate(periods):
            if i == 0:
                result[p] = None
            else:
                raw = _safe_growth(
                    _get(data, self.metric, p),
                    _get(data, self.metric, periods[i - 1]),
                )
                result[p] = raw * 100 if raw is not None else None
        return result


@dataclass
class QoQGrowth(ComputedMetric):
    """Sequential quarter-over-quarter growth. Same math as YoYGrowth."""
    metric: str = ""
    fmt: str = "percent"

    @property
    def dependencies(self) -> List[str]:
        return [self.metric]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        result: PeriodValues = {}
        for i, p in enumerate(periods):
            if i == 0:
                result[p] = None
            else:
                raw = _safe_growth(
                    _get(data, self.metric, p),
                    _get(data, self.metric, periods[i - 1]),
                )
                result[p] = raw * 100 if raw is not None else None
        return result


# ---------------------------------------------------------------------------
# CAGR  —  (last / first)^(1/n) − 1
#          Shown only in the last period column; None for intermediate periods.
#          Also stored as a single aggregate value for summary display.
# ---------------------------------------------------------------------------

@dataclass
class CAGR(ComputedMetric):
    metric: str = ""
    fmt: str = "percent"

    @property
    def dependencies(self) -> List[str]:
        return [self.metric]

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        result: PeriodValues = {p: None for p in periods}
        if len(periods) < 2:
            return result

        first_val = _get(data, self.metric, periods[0])
        last_val = _get(data, self.metric, periods[-1])
        n = len(periods) - 1

        if first_val is None or last_val is None or first_val == 0:
            return result
        if first_val < 0 or last_val < 0:
            return result  # CAGR undefined for sign changes

        cagr = ((last_val / first_val) ** (1.0 / n) - 1.0) * 100
        if math.isnan(cagr) or math.isinf(cagr):
            return result

        result[periods[-1]] = cagr
        return result


# ---------------------------------------------------------------------------
# MarketRatio  —  requires external price; unlocked via --price flag
# ---------------------------------------------------------------------------

@dataclass
class MarketRatio(ComputedMetric):
    """
    Market-based multiples. Needs price supplied at compute time.

    market_numerator:
      "market_cap"        → price × shares_diluted
      "enterprise_value"  → market_cap + net_debt
      metric name         → use that computed/base metric directly

    denominator: base or computed metric name
    """
    market_numerator: str = "market_cap"   # "market_cap" | "enterprise_value" | metric_name
    denominator: str = ""
    scale: float = 1.0

    @property
    def dependencies(self) -> List[str]:
        deps = [self.denominator]
        if self.market_numerator not in ("market_cap", "enterprise_value"):
            deps.append(self.market_numerator)
        return deps

    def compute(self, data: Data, periods: List[str], price=None) -> PeriodValues:
        if price is None:
            return {p: None for p in periods}

        result: PeriodValues = {}
        for p in periods:
            # Resolve numerator
            if self.market_numerator == "market_cap":
                shares = _get(data, "shares_diluted", p)
                num = price * shares if shares is not None else None
            elif self.market_numerator == "enterprise_value":
                num = _get(data, "enterprise_value", p)
            else:
                num = _get(data, self.market_numerator, p)

            den = _get(data, self.denominator, p)
            result[p] = _safe_div(num, den, self.scale)
        return result


# ---------------------------------------------------------------------------
# RatioEngine
# ---------------------------------------------------------------------------

class RatioEngine:
    """
    Evaluates a list of ComputedMetrics in definition order against a data pool.

    The pool is seeded with base XBRL metric values and grows as each
    ComputedMetric is evaluated — so later metrics can reference earlier ones
    (e.g. net_debt_to_ebitda can use net_debt computed just before it).
    """

    def compute_all(
        self,
        metrics: List[ComputedMetric],
        data: Data,
        periods: List[str],
        price: Optional[float] = None,
    ) -> Data:
        pool: Data = {k: dict(v) for k, v in data.items()}  # shallow copy

        for m in metrics:
            try:
                pool[m.name] = m.compute(pool, periods, price=price)
            except Exception:
                pool[m.name] = {p: None for p in periods}

        return pool
