"""
All ratio, efficiency, growth, and market multiple definitions.

Evaluation order matters: each metric may reference any metric defined before
it in the list. Intermediates (net_debt, quick_assets, etc.) come first.
"""

from __future__ import annotations

from typing import List

from .computed import (
    CAGR,
    AvgDenominatorRatio,
    ComputedMetric,
    DaysMetric,
    MarketRatio,
    QoQGrowth,
    Ratio,
    Sum,
    YoYGrowth,
)

_SEC = "section"   # just a reminder — sections used as string keys below

# ---------------------------------------------------------------------------
# INTERMEDIATES  (not shown in report; building blocks for later metrics)
# ---------------------------------------------------------------------------
# Convention: prefix with "_" to mark as hidden intermediates.
# RatioEngine computes them all; the report layer filters by name.

_INTERMEDIATES: List[ComputedMetric] = [
    Sum("_total_debt", "Total Debt (internal)", "hidden", "currency",
        terms=[(1.0, "short_term_debt"), (1.0, "long_term_debt")]),

    Sum("_net_debt", "Net Debt (internal)", "hidden", "currency",
        terms=[(1.0, "short_term_debt"), (1.0, "long_term_debt"),
               (-1.0, "cash_equivalents")]),

    Sum("_quick_assets", "Quick Assets (internal)", "hidden", "currency",
        terms=[(1.0, "total_current_assets"), (-1.0, "inventory")]),

    Sum("_tangible_book", "Tangible Book Value (internal)", "hidden", "currency",
        terms=[(1.0, "total_equity"), (-1.0, "goodwill"), (-1.0, "intangible_assets")]),

    Sum("_invested_capital", "Invested Capital (internal)", "hidden", "currency",
        terms=[(1.0, "total_equity"), (1.0, "short_term_debt"),
               (1.0, "long_term_debt"), (-1.0, "cash_equivalents")]),
]


class _MarketCap(ComputedMetric):
    """market_cap = price × shares_diluted."""

    @property
    def dependencies(self):
        return ["shares_diluted"]

    def compute(self, data, periods, price=None):
        from .computed import _get
        if price is None:
            return {p: None for p in periods}
        return {
            p: (price * _get(data, "shares_diluted", p))
            if _get(data, "shares_diluted", p) is not None else None
            for p in periods
        }


class _EnterpriseValue(ComputedMetric):
    """enterprise_value = market_cap + net_debt."""

    @property
    def dependencies(self):
        return ["market_cap", "_net_debt"]

    def compute(self, data, periods, price=None):
        from .computed import _get
        result = {}
        for p in periods:
            mc = _get(data, "market_cap", p)
            nd = _get(data, "_net_debt", p)
            result[p] = (mc + nd) if (mc is not None and nd is not None) else None
        return result


_MARKET_INTERMEDIATES: List[ComputedMetric] = [
    _MarketCap("market_cap", "Market Cap", "hidden", "currency"),
    _EnterpriseValue("enterprise_value", "Enterprise Value", "hidden", "currency"),
]


# ---------------------------------------------------------------------------
# PROFITABILITY
# ---------------------------------------------------------------------------

PROFITABILITY: List[ComputedMetric] = [
    Ratio("gross_margin", "Gross Margin", "profitability", "percent",
          numerator="gross_profit", denominator="revenue", scale=100),
    Ratio("operating_margin", "Operating Margin", "profitability", "percent",
          numerator="operating_income", denominator="revenue", scale=100),
    Ratio("ebitda_margin", "EBITDA Margin", "profitability", "percent",
          numerator="ebitda", denominator="revenue", scale=100),
    Ratio("net_margin", "Net Margin", "profitability", "percent",
          numerator="net_income", denominator="revenue", scale=100),
    Ratio("rd_pct_revenue", "R&D % of Revenue", "profitability", "percent", indent=1,
          numerator="research_development", denominator="revenue", scale=100),
    Ratio("sga_pct_revenue", "SG&A % of Revenue", "profitability", "percent", indent=1,
          numerator="selling_general_admin", denominator="revenue", scale=100),
    AvgDenominatorRatio("roe", "Return on Equity (ROE)", "profitability", "percent",
                        numerator="net_income", denominator="total_equity", scale=100),
    AvgDenominatorRatio("roa", "Return on Assets (ROA)", "profitability", "percent",
                        numerator="net_income", denominator="total_assets", scale=100),
    Ratio("roic", "Return on Invested Capital (ROIC)", "profitability", "percent",
          numerator="operating_income", denominator="_invested_capital", scale=100),
]


# ---------------------------------------------------------------------------
# LIQUIDITY
# ---------------------------------------------------------------------------

LIQUIDITY: List[ComputedMetric] = [
    Sum("working_capital", "Working Capital", "liquidity", "currency",
        terms=[(1.0, "total_current_assets"), (-1.0, "total_current_liabilities")]),
    Ratio("current_ratio", "Current Ratio", "liquidity", "times",
          numerator="total_current_assets", denominator="total_current_liabilities"),
    Ratio("quick_ratio", "Quick Ratio", "liquidity", "times",
          numerator="_quick_assets", denominator="total_current_liabilities"),
    Ratio("cash_ratio", "Cash Ratio", "liquidity", "times",
          numerator="cash_equivalents", denominator="total_current_liabilities"),
]


# ---------------------------------------------------------------------------
# LEVERAGE & SOLVENCY
# ---------------------------------------------------------------------------

LEVERAGE: List[ComputedMetric] = [
    Sum("total_debt", "Total Debt", "leverage", "currency",
        terms=[(1.0, "short_term_debt"), (1.0, "long_term_debt")]),
    Sum("net_debt", "Net Debt", "leverage", "currency",
        terms=[(1.0, "short_term_debt"), (1.0, "long_term_debt"),
               (-1.0, "cash_equivalents")]),
    Ratio("debt_to_equity", "Debt / Equity", "leverage", "times",
          numerator="total_debt", denominator="total_equity"),
    Ratio("net_debt_to_equity", "Net Debt / Equity", "leverage", "times",
          numerator="net_debt", denominator="total_equity"),
    Ratio("net_debt_to_ebitda", "Net Debt / EBITDA", "leverage", "times",
          numerator="net_debt", denominator="ebitda"),
    Ratio("debt_to_assets", "Debt / Assets", "leverage", "percent",
          numerator="total_debt", denominator="total_assets", scale=100),
    Ratio("interest_coverage", "Interest Coverage", "leverage", "times",
          numerator="operating_income", denominator="interest_expense"),
    Ratio("equity_multiplier", "Equity Multiplier", "leverage", "times",
          numerator="total_assets", denominator="total_equity"),
]


# ---------------------------------------------------------------------------
# EFFICIENCY
# ---------------------------------------------------------------------------

EFFICIENCY: List[ComputedMetric] = [
    AvgDenominatorRatio("asset_turnover", "Asset Turnover", "efficiency", "times",
                        numerator="revenue", denominator="total_assets"),
    AvgDenominatorRatio("inventory_turnover", "Inventory Turnover", "efficiency", "times",
                        numerator="cost_of_revenue", denominator="inventory"),
    AvgDenominatorRatio("receivables_turnover", "Receivables Turnover", "efficiency", "times",
                        numerator="revenue", denominator="accounts_receivable"),
    DaysMetric("dso", "Days Sales Outstanding (DSO)", "efficiency", "days",
               numerator="accounts_receivable", denominator="revenue"),
    DaysMetric("dio", "Days Inventory Outstanding (DIO)", "efficiency", "days",
               numerator="inventory", denominator="cost_of_revenue"),
    DaysMetric("dpo", "Days Payable Outstanding (DPO)", "efficiency", "days",
               numerator="accounts_payable", denominator="cost_of_revenue"),
    Sum("ccc", "Cash Conversion Cycle (CCC)", "efficiency", "days",
        terms=[(1.0, "dso"), (1.0, "dio"), (-1.0, "dpo")]),
    Ratio("capex_pct_revenue", "Capex / Revenue", "efficiency", "percent",
          numerator="capex", denominator="revenue", scale=100),
    Ratio("capex_to_da", "Capex / D&A", "efficiency", "times",
          numerator="capex", denominator="depreciation_amortization"),
]


# ---------------------------------------------------------------------------
# CASH FLOW QUALITY
# ---------------------------------------------------------------------------

CASH_FLOW_QUALITY: List[ComputedMetric] = [
    Ratio("operating_cf_margin", "Operating CF Margin", "cash_flow_quality", "percent",
          numerator="cf_operating", denominator="revenue", scale=100),
    Ratio("fcf_margin", "FCF Margin", "cash_flow_quality", "percent",
          numerator="free_cash_flow", denominator="revenue", scale=100),
    Ratio("fcf_conversion", "FCF / Net Income", "cash_flow_quality", "percent",
          numerator="free_cash_flow", denominator="net_income", scale=100),
    Ratio("fcf_per_share", "FCF per Share", "cash_flow_quality", "currency_per_share",
          numerator="free_cash_flow", denominator="shares_diluted"),
    Ratio("sbc_margin", "SBC / Revenue", "cash_flow_quality", "percent",
          numerator="cf_stock_compensation", denominator="revenue", scale=100),
    Ratio("repurchase_margin", "Repurchases / Revenue", "cash_flow_quality", "percent",
          numerator="share_repurchases", denominator="revenue", scale=100),
    Ratio("dividend_margin", "Dividends / Revenue", "cash_flow_quality", "percent",
          numerator="dividends_paid", denominator="revenue", scale=100),
]


# ---------------------------------------------------------------------------
# PER SHARE
# ---------------------------------------------------------------------------

PER_SHARE: List[ComputedMetric] = [
    Ratio("book_value_per_share", "Book Value per Share", "per_share", "currency_per_share",
          numerator="total_equity", denominator="shares_diluted"),
    Ratio("tangible_bvps", "Tangible Book Value per Share", "per_share", "currency_per_share",
          numerator="_tangible_book", denominator="shares_diluted"),
    Ratio("revenue_per_share", "Revenue per Share", "per_share", "currency_per_share",
          numerator="revenue", denominator="shares_diluted"),
    Ratio("eps_basic_calc", "EPS (Basic)", "per_share", "currency_per_share",
          numerator="net_income", denominator="shares_basic"),
    Ratio("eps_diluted_calc", "EPS (Diluted)", "per_share", "currency_per_share",
          numerator="net_income", denominator="shares_diluted"),
]


# ---------------------------------------------------------------------------
# GROWTH
# ---------------------------------------------------------------------------

GROWTH: List[ComputedMetric] = [
    YoYGrowth("revenue_growth",      "Revenue Growth (YoY)",          "growth", "percent",
              metric="revenue"),
    QoQGrowth("revenue_qoq",         "Revenue Growth (QoQ)",          "growth", "percent",
              metric="revenue"),
    YoYGrowth("gp_growth",           "Gross Profit Growth (YoY)",     "growth", "percent", indent=1,
              metric="gross_profit"),
    YoYGrowth("ebit_growth",         "Operating Income Growth (YoY)", "growth", "percent", indent=1,
              metric="operating_income"),
    QoQGrowth("ebit_qoq",            "EBIT Growth (QoQ)",             "growth", "percent", indent=1,
              metric="operating_income"),
    YoYGrowth("ni_growth",           "Net Income Growth (YoY)",       "growth", "percent",
              metric="net_income"),
    QoQGrowth("ni_qoq",              "Net Income Growth (QoQ)",       "growth", "percent",
              metric="net_income"),
    YoYGrowth("eps_growth",          "EPS Growth (YoY)",              "growth", "percent", indent=1,
              metric="eps_diluted"),
    QoQGrowth("eps_qoq",             "EPS Growth (QoQ)",              "growth", "percent", indent=1,
              metric="eps_diluted"),
    YoYGrowth("fcf_growth",          "FCF Growth (YoY)",              "growth", "percent",
              metric="free_cash_flow"),
    QoQGrowth("fcf_qoq",             "FCF Growth (QoQ)",              "growth", "percent",
              metric="free_cash_flow"),
    YoYGrowth("cf_operating_yoy",    "Operating CF Growth (YoY)",     "growth", "percent",
              metric="cf_operating"),
    QoQGrowth("cf_operating_qoq",    "Operating CF Growth (QoQ)",     "growth", "percent",
              metric="cf_operating"),
    CAGR("revenue_cagr",             "Revenue CAGR",                  "growth", "percent",
         metric="revenue"),
    CAGR("ni_cagr",                  "Net Income CAGR",               "growth", "percent",
         metric="net_income"),
    CAGR("eps_cagr",                 "EPS CAGR",                      "growth", "percent",
         metric="eps_diluted"),
    CAGR("fcf_cagr",                 "FCF CAGR",                      "growth", "percent",
         metric="free_cash_flow"),
]


# ---------------------------------------------------------------------------
# MARKET MULTIPLES  (require --price)
# ---------------------------------------------------------------------------

MARKET: List[ComputedMetric] = [
    MarketRatio("pe",         "Price / Earnings (P/E)",    "market", "multiple",
                market_numerator="market_cap",        denominator="net_income"),
    MarketRatio("ps",         "Price / Sales (P/S)",       "market", "multiple",
                market_numerator="market_cap",        denominator="revenue"),
    MarketRatio("pb",         "Price / Book (P/B)",        "market", "multiple",
                market_numerator="market_cap",        denominator="total_equity"),
    MarketRatio("p_fcf",      "Price / FCF (P/FCF)",       "market", "multiple",
                market_numerator="market_cap",        denominator="free_cash_flow"),
    MarketRatio("ev_revenue", "EV / Revenue",              "market", "multiple",
                market_numerator="enterprise_value",  denominator="revenue"),
    MarketRatio("ev_ebitda",  "EV / EBITDA",               "market", "multiple",
                market_numerator="enterprise_value",  denominator="ebitda"),
    MarketRatio("ev_ebit",    "EV / EBIT",                 "market", "multiple",
                market_numerator="enterprise_value",  denominator="operating_income"),
    MarketRatio("ev_fcf",     "EV / FCF",                  "market", "multiple",
                market_numerator="enterprise_value",  denominator="free_cash_flow"),
    MarketRatio("earnings_yield", "Earnings Yield",        "market", "percent",
                market_numerator="net_income",        denominator="market_cap", scale=100),
    MarketRatio("fcf_yield",  "FCF Yield",                 "market", "percent",
                market_numerator="free_cash_flow",    denominator="market_cap", scale=100),
]


# ---------------------------------------------------------------------------
# Master list — order defines evaluation sequence
# ---------------------------------------------------------------------------

# Hidden names (prefix "_") are computed but not shown in reports
_HIDDEN_NAMES = {m.name for m in _INTERMEDIATES} | {"market_cap", "enterprise_value"}

ALL_COMPUTED: List[ComputedMetric] = (
    _INTERMEDIATES
    + _MARKET_INTERMEDIATES
    + PROFITABILITY
    + LIQUIDITY
    + LEVERAGE
    + EFFICIENCY
    + CASH_FLOW_QUALITY
    + PER_SHARE
    + GROWTH
    + MARKET
)

# Assign sort_order
for _i, _m in enumerate(ALL_COMPUTED):
    _m.sort_order = _i

SECTION_ORDER = [
    "profitability",
    "liquidity",
    "leverage",
    "efficiency",
    "cash_flow_quality",
    "per_share",
    "growth",
    "market",
]

SECTION_TITLES = {
    "profitability":    "Profitability",
    "liquidity":        "Liquidity",
    "leverage":         "Leverage & Solvency",
    "efficiency":       "Efficiency",
    "cash_flow_quality":"Cash Flow Quality",
    "per_share":        "Per Share",
    "growth":           "Growth",
    "market":           "Market Multiples",
}

# Metrics visible in the report (excludes hidden intermediates)
VISIBLE_COMPUTED: List[ComputedMetric] = [
    m for m in ALL_COMPUTED if m.name not in _HIDDEN_NAMES and m.section != "hidden"
]
