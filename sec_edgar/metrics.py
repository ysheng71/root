"""
Standardized financial metric definitions mapping XBRL concepts to
human-readable names for Income Statement, Balance Sheet, and Cash Flow.

Each metric has an ordered list of XBRL concept candidates; the first concept
with available data wins (lower index = higher priority).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MetricDef:
    name: str                      # snake_case identifier, e.g. "revenue"
    display: str                   # Human-readable, e.g. "Revenue"
    statement: str                 # income_statement | balance_sheet | cash_flow
    period_type: str               # duration | instant
    unit: str                      # USD | shares | USD/shares | pure
    concepts: List[str]            # XBRL concept names, priority order (first wins)
    section: str = ""              # grouping key for visual separators
    indent: int = 0                # 0 = major line / total, 1 = sub-line
    is_derived: bool = False       # computed from other metrics
    derived_expr: Optional[str] = None  # Python expr; other metrics are variables
    sort_order: int = field(default=0, compare=False)


# ---------------------------------------------------------------------------
# Income Statement
# ---------------------------------------------------------------------------

_IS = "income_statement"
_DUR = "duration"
_INS = "instant"

INCOME_STATEMENT: List[MetricDef] = [
    MetricDef("revenue", "Revenue", _IS, _DUR, "USD",
        ["RevenueFromContractWithCustomerExcludingAssessedTax",
         "RevenueFromContractWithCustomerIncludingAssessedTax",
         "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
         "RevenuesNetOfInterestExpense"],
        section="revenue"),
    MetricDef("cost_of_revenue", "Cost of Revenue", _IS, _DUR, "USD",
        ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
         "CostOfGoodsAndServices"],
        section="revenue", indent=1),
    MetricDef("gross_profit", "Gross Profit", _IS, _DUR, "USD",
        ["GrossProfit"],
        section="revenue"),

    MetricDef("research_development", "Research & Development", _IS, _DUR, "USD",
        ["ResearchAndDevelopmentExpense",
         "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
        section="opex", indent=1),
    MetricDef("selling_general_admin", "Selling, General & Admin", _IS, _DUR, "USD",
        ["SellingGeneralAndAdministrativeExpense",
         "SellingAndMarketingExpense", "GeneralAndAdministrativeExpense"],
        section="opex", indent=1),
    MetricDef("operating_expenses", "Total Operating Expenses", _IS, _DUR, "USD",
        ["OperatingExpenses", "CostsAndExpenses"],
        section="opex"),

    MetricDef("operating_income", "Operating Income (EBIT)", _IS, _DUR, "USD",
        ["OperatingIncomeLoss"],
        section="operating"),

    MetricDef("interest_expense", "Interest Expense", _IS, _DUR, "USD",
        ["InterestExpense", "InterestAndDebtExpense", "InterestExpenseDebt"],
        section="below_line", indent=1),
    MetricDef("other_income_expense", "Other Income (Expense), net", _IS, _DUR, "USD",
        ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense",
         "InvestmentIncomeInterest"],
        section="below_line", indent=1),
    MetricDef("income_before_tax", "Income Before Tax", _IS, _DUR, "USD",
        ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
         "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
        section="below_line"),
    MetricDef("income_tax", "Income Tax Expense", _IS, _DUR, "USD",
        ["IncomeTaxExpenseBenefit"],
        section="below_line", indent=1),

    MetricDef("net_income", "Net Income", _IS, _DUR, "USD",
        ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAttributableToParent",
         "IncomeLossFromContinuingOperations"],
        section="bottom_line"),

    MetricDef("depreciation_amortization", "Depreciation & Amortization", _IS, _DUR, "USD",
        ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
         "Depreciation"],
        section="supplemental", indent=1),
    MetricDef("ebitda", "EBITDA", _IS, _DUR, "USD",
        [], section="supplemental",
        is_derived=True, derived_expr="operating_income + depreciation_amortization"),

    MetricDef("eps_basic", "EPS (Basic)", _IS, _DUR, "USD/shares",
        ["EarningsPerShareBasic"],
        section="per_share", indent=1),
    MetricDef("eps_diluted", "EPS (Diluted)", _IS, _DUR, "USD/shares",
        ["EarningsPerShareDiluted"],
        section="per_share", indent=1),
    MetricDef("shares_basic", "Shares Outstanding (Basic)", _IS, _DUR, "shares",
        ["WeightedAverageNumberOfSharesOutstandingBasic"],
        section="per_share", indent=1),
    MetricDef("shares_diluted", "Shares Outstanding (Diluted)", _IS, _DUR, "shares",
        ["WeightedAverageNumberOfDilutedSharesOutstanding",
         "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"],
        section="per_share", indent=1),
]


# ---------------------------------------------------------------------------
# Balance Sheet
# ---------------------------------------------------------------------------

_BS = "balance_sheet"

BALANCE_SHEET: List[MetricDef] = [
    # Current Assets
    MetricDef("cash_equivalents", "Cash & Equivalents", _BS, _INS, "USD",
        ["CashAndCashEquivalentsAtCarryingValue", "Cash",
         "CashCashEquivalentsAndFederalFundsSold"],
        section="current_assets", indent=1),
    MetricDef("short_term_investments", "Short-term Investments", _BS, _INS, "USD",
        ["ShortTermInvestments", "MarketableSecuritiesCurrent",
         "AvailableForSaleSecuritiesCurrent"],
        section="current_assets", indent=1),
    MetricDef("accounts_receivable", "Accounts Receivable, net", _BS, _INS, "USD",
        ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
        section="current_assets", indent=1),
    MetricDef("inventory", "Inventories", _BS, _INS, "USD",
        ["InventoryNet", "FIFOInventoryAmount"],
        section="current_assets", indent=1),
    MetricDef("other_current_assets", "Other Current Assets", _BS, _INS, "USD",
        ["OtherAssetsCurrent", "PrepaidExpenseAndOtherAssetsCurrent"],
        section="current_assets", indent=1),
    MetricDef("total_current_assets", "Total Current Assets", _BS, _INS, "USD",
        ["AssetsCurrent"],
        section="current_assets"),

    # Non-Current Assets
    MetricDef("ppe_net", "Property, Plant & Equipment, net", _BS, _INS, "USD",
        ["PropertyPlantAndEquipmentNet"],
        section="noncurrent_assets", indent=1),
    MetricDef("goodwill", "Goodwill", _BS, _INS, "USD",
        ["Goodwill"],
        section="noncurrent_assets", indent=1),
    MetricDef("intangible_assets", "Intangible Assets, net", _BS, _INS, "USD",
        ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
        section="noncurrent_assets", indent=1),
    MetricDef("long_term_investments", "Long-term Investments", _BS, _INS, "USD",
        ["LongTermInvestments", "MarketableSecuritiesNoncurrent",
         "AvailableForSaleSecuritiesNoncurrent"],
        section="noncurrent_assets", indent=1),
    MetricDef("other_noncurrent_assets", "Other Non-Current Assets", _BS, _INS, "USD",
        ["OtherAssetsNoncurrent"],
        section="noncurrent_assets", indent=1),
    MetricDef("total_assets", "Total Assets", _BS, _INS, "USD",
        ["Assets"],
        section="noncurrent_assets"),

    # Current Liabilities
    MetricDef("accounts_payable", "Accounts Payable", _BS, _INS, "USD",
        ["AccountsPayableCurrent"],
        section="current_liabilities", indent=1),
    MetricDef("short_term_debt", "Short-term Debt & Current Portion", _BS, _INS, "USD",
        ["ShortTermBorrowings", "CommercialPaper",
         "LongTermDebtCurrent", "NotesPayableCurrent"],
        section="current_liabilities", indent=1),
    MetricDef("deferred_revenue_current", "Deferred Revenue (Current)", _BS, _INS, "USD",
        ["DeferredRevenueCurrent", "ContractWithCustomerLiabilityCurrent"],
        section="current_liabilities", indent=1),
    MetricDef("other_current_liabilities", "Other Current Liabilities", _BS, _INS, "USD",
        ["OtherLiabilitiesCurrent", "AccruedLiabilitiesCurrent"],
        section="current_liabilities", indent=1),
    MetricDef("total_current_liabilities", "Total Current Liabilities", _BS, _INS, "USD",
        ["LiabilitiesCurrent"],
        section="current_liabilities"),

    # Non-Current Liabilities
    MetricDef("long_term_debt", "Long-term Debt", _BS, _INS, "USD",
        ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermNotesPayable"],
        section="noncurrent_liabilities", indent=1),
    MetricDef("deferred_tax_liabilities", "Deferred Tax Liabilities", _BS, _INS, "USD",
        ["DeferredIncomeTaxLiabilitiesNet", "DeferredTaxLiabilitiesNoncurrent"],
        section="noncurrent_liabilities", indent=1),
    MetricDef("other_noncurrent_liabilities", "Other Non-Current Liabilities", _BS, _INS, "USD",
        ["OtherLiabilitiesNoncurrent"],
        section="noncurrent_liabilities", indent=1),
    MetricDef("total_liabilities", "Total Liabilities", _BS, _INS, "USD",
        ["Liabilities"],
        section="noncurrent_liabilities"),

    # Equity
    MetricDef("common_stock_apic", "Common Stock & APIC", _BS, _INS, "USD",
        ["AdditionalPaidInCapital", "CommonStocksIncludingAdditionalPaidInCapital",
         "AdditionalPaidInCapitalCommonStock"],
        section="equity", indent=1),
    MetricDef("retained_earnings", "Retained Earnings (Deficit)", _BS, _INS, "USD",
        ["RetainedEarningsAccumulatedDeficit"],
        section="equity", indent=1),
    MetricDef("treasury_stock", "Treasury Stock", _BS, _INS, "USD",
        ["TreasuryStockValue", "TreasuryStockCommonValue"],
        section="equity", indent=1),
    MetricDef("total_equity", "Total Shareholders' Equity", _BS, _INS, "USD",
        ["StockholdersEquity", "StockholdersEquityAttributableToParent"],
        section="equity"),
    MetricDef("total_liabilities_equity", "Total Liabilities & Equity", _BS, _INS, "USD",
        ["LiabilitiesAndStockholdersEquity"],
        section="equity"),
]


# ---------------------------------------------------------------------------
# Cash Flow Statement
# ---------------------------------------------------------------------------

_CF = "cash_flow"

CASH_FLOW: List[MetricDef] = [
    # Operating Activities
    MetricDef("cf_net_income", "Net Income", _CF, _DUR, "USD",
        ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAttributableToParent"],
        section="operating", indent=1),
    MetricDef("cf_depreciation", "Depreciation & Amortization", _CF, _DUR, "USD",
        ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
        section="operating", indent=1),
    MetricDef("cf_stock_compensation", "Stock-based Compensation", _CF, _DUR, "USD",
        ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense",
         "ShareBasedCompensationExpense"],
        section="operating", indent=1),
    MetricDef("cf_working_capital", "Changes in Working Capital", _CF, _DUR, "USD",
        ["IncreaseDecreaseInOperatingCapital",
         "IncreaseDecreaseInOperatingLiabilities"],
        section="operating", indent=1),
    MetricDef("cf_operating", "Net Cash from Operations", _CF, _DUR, "USD",
        ["NetCashProvidedByUsedInOperatingActivities"],
        section="operating"),

    # Investing Activities
    MetricDef("capex", "Capital Expenditures", _CF, _DUR, "USD",
        ["PaymentsToAcquirePropertyPlantAndEquipment",
         "PaymentsForCapitalImprovements"],
        section="investing", indent=1),
    MetricDef("acquisitions", "Acquisitions, net of cash", _CF, _DUR, "USD",
        ["PaymentsToAcquireBusinessesNetOfCashAcquired",
         "PaymentsToAcquireBusinessesAndInterestInAffiliates"],
        section="investing", indent=1),
    MetricDef("investment_purchases", "Purchases of Investments", _CF, _DUR, "USD",
        ["PaymentsToAcquireMarketableSecurities",
         "PaymentsToAcquireAvailableForSaleSecurities",
         "PaymentsToAcquireInvestments"],
        section="investing", indent=1),
    MetricDef("investment_proceeds", "Sales/Maturities of Investments", _CF, _DUR, "USD",
        ["ProceedsFromSaleAndMaturityOfMarketableSecurities",
         "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
         "ProceedsFromSaleOfAvailableForSaleSecurities"],
        section="investing", indent=1),
    MetricDef("cf_investing", "Net Cash from Investing", _CF, _DUR, "USD",
        ["NetCashProvidedByUsedInInvestingActivities"],
        section="investing"),

    # Financing Activities
    MetricDef("debt_issuance", "Proceeds from Debt Issuance", _CF, _DUR, "USD",
        ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt",
         "ProceedsFromLongTermLinesOfCredit"],
        section="financing", indent=1),
    MetricDef("debt_repayment", "Repayment of Debt", _CF, _DUR, "USD",
        ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt",
         "RepaymentsOfLongTermLinesOfCredit"],
        section="financing", indent=1),
    MetricDef("share_repurchases", "Share Repurchases", _CF, _DUR, "USD",
        ["PaymentsForRepurchaseOfCommonStock"],
        section="financing", indent=1),
    MetricDef("dividends_paid", "Dividends Paid", _CF, _DUR, "USD",
        ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
        section="financing", indent=1),
    MetricDef("cf_financing", "Net Cash from Financing", _CF, _DUR, "USD",
        ["NetCashProvidedByUsedInFinancingActivities"],
        section="financing"),

    # Summary
    MetricDef("free_cash_flow", "Free Cash Flow", _CF, _DUR, "USD",
        [], section="summary",
        is_derived=True, derived_expr="cf_operating - capex"),
    MetricDef("net_change_in_cash", "Net Change in Cash", _CF, _DUR, "USD",
        ["CashAndCashEquivalentsPeriodIncreaseDecrease",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"],
        section="summary"),
]

# Assign sort_order based on list position
for _stmt_list in (INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW):
    for _i, _m in enumerate(_stmt_list):
        _m.sort_order = _i

STATEMENT_METRICS = {
    "income_statement": INCOME_STATEMENT,
    "balance_sheet": BALANCE_SHEET,
    "cash_flow": CASH_FLOW,
}

STATEMENT_TITLES = {
    "income_statement": "Income Statement",
    "balance_sheet": "Balance Sheet",
    "cash_flow": "Cash Flow Statement",
}

ALL_METRICS: List[MetricDef] = INCOME_STATEMENT + BALANCE_SHEET + CASH_FLOW

# Lookup: concept name → list of MetricDef (sorted by priority within statement)
CONCEPT_TO_METRICS: dict = {}
for _m in ALL_METRICS:
    for _priority, _concept in enumerate(_m.concepts):
        if _concept not in CONCEPT_TO_METRICS:
            CONCEPT_TO_METRICS[_concept] = []
        CONCEPT_TO_METRICS[_concept].append((_priority, _m))


def get_metric(name: str) -> Optional[MetricDef]:
    for m in ALL_METRICS:
        if m.name == name:
            return m
    return None


def metric_mappings_rows() -> List[dict]:
    """Flat rows for seeding the metric_mappings DB table."""
    rows = []
    for m in ALL_METRICS:
        for priority, concept in enumerate(m.concepts):
            rows.append({
                "metric_name": m.name,
                "display_name": m.display,
                "statement": m.statement,
                "period_type": m.period_type,
                "unit": m.unit,
                "section": m.section,
                "indent": m.indent,
                "sort_order": m.sort_order,
                "is_derived": 0,
                "concept": concept,
                "taxonomy": "us-gaap",
                "priority": priority,
            })
    return rows
