"""
Annotation mappings: parent metric → inline computed metrics.

For each (statement, period_mode) pair, defines which computed metrics
are injected as annotation rows immediately after their parent metric row.
Annotation rows are rendered with a '·' prefix to distinguish them from
accounting line items.
"""

from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# Income Statement
# ---------------------------------------------------------------------------

_IS_ANNUAL: Dict[str, List[str]] = {
    "revenue":               ["revenue_growth"],
    "gross_profit":          ["gross_margin"],
    "research_development":  ["rd_pct_revenue"],
    "selling_general_admin": ["sga_pct_revenue"],
    "operating_income":      ["operating_margin"],
    "ebitda":                ["ebitda_margin"],
    "net_income":            ["net_margin"],
    "eps_diluted":           ["eps_growth"],
}

_IS_QUARTERLY: Dict[str, List[str]] = {
    "revenue":               ["revenue_growth", "revenue_qoq"],
    "gross_profit":          ["gross_margin"],
    "research_development":  ["rd_pct_revenue"],
    "selling_general_admin": ["sga_pct_revenue"],
    "operating_income":      ["operating_margin", "ebit_qoq"],
    "ebitda":                ["ebitda_margin"],
    "net_income":            ["net_margin", "ni_qoq"],
    "eps_diluted":           ["eps_growth", "eps_qoq"],
}


# ---------------------------------------------------------------------------
# Balance Sheet
# ---------------------------------------------------------------------------

_BS_ANNUAL: Dict[str, List[str]] = {
    "total_current_assets":      ["current_ratio", "quick_ratio", "cash_ratio"],
    "total_current_liabilities": ["working_capital"],
    "total_assets":              ["roa", "debt_to_assets", "asset_turnover"],
    "long_term_debt":            ["net_debt_to_ebitda", "interest_coverage"],
    "total_equity":              ["roe", "book_value_per_share", "debt_to_equity", "equity_multiplier"],
}

_BS_QUARTERLY: Dict[str, List[str]] = {
    "total_current_assets":      ["current_ratio", "quick_ratio", "cash_ratio"],
    "total_current_liabilities": ["working_capital"],
    "total_assets":              ["roa", "debt_to_assets", "asset_turnover"],
    "long_term_debt":            ["net_debt_to_ebitda", "interest_coverage"],
    "total_equity":              ["roe", "book_value_per_share", "debt_to_equity", "equity_multiplier"],
}


# ---------------------------------------------------------------------------
# Cash Flow
# ---------------------------------------------------------------------------

_CF_ANNUAL: Dict[str, List[str]] = {
    "cf_operating":          ["operating_cf_margin", "cf_operating_yoy"],
    "free_cash_flow":        ["fcf_margin", "fcf_growth"],
    "cf_stock_compensation": ["sbc_margin"],
    "share_repurchases":     ["repurchase_margin"],
    "dividends_paid":        ["dividend_margin"],
}

_CF_QUARTERLY: Dict[str, List[str]] = {
    "cf_operating":          ["operating_cf_margin", "cf_operating_yoy", "cf_operating_qoq"],
    "free_cash_flow":        ["fcf_margin", "fcf_growth", "fcf_qoq"],
    "cf_stock_compensation": ["sbc_margin"],
    "share_repurchases":     ["repurchase_margin"],
    "dividends_paid":        ["dividend_margin"],
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_MAP = {
    ("income_statement", "annual"):    _IS_ANNUAL,
    ("income_statement", "quarterly"): _IS_QUARTERLY,
    ("balance_sheet",    "annual"):    _BS_ANNUAL,
    ("balance_sheet",    "quarterly"): _BS_QUARTERLY,
    ("cash_flow",        "annual"):    _CF_ANNUAL,
    ("cash_flow",        "quarterly"): _CF_QUARTERLY,
}


def get_annotations(statement: str, period: str) -> Dict[str, List[str]]:
    """Return {parent_metric_name: [annotation_metric_name, ...]} for this view."""
    return _MAP.get((statement, period), {})
