# Database Reference

The tool stores all data in a single SQLite file (default: `edgar.db`, configurable
via `--db` or `EDGAR_DB`). The database can be queried directly alongside the CLI —
any SQLite client works.

---

## Tables

### `companies`

One row per company. Populated by `sec-edgar fetch`.

| Column           | Type | Description |
|------------------|------|-------------|
| `cik`            | TEXT PK | SEC Central Index Key (zero-padded to 10 digits) |
| `ticker`         | TEXT UNIQUE | Stock ticker (uppercase) |
| `name`           | TEXT | Company legal name |
| `sic`            | TEXT | SIC industry code |
| `sic_desc`       | TEXT | SIC description |
| `ein`            | TEXT | Employer Identification Number |
| `state_inc`      | TEXT | State of incorporation (2-letter) |
| `fiscal_year_end`| TEXT | Fiscal year end month-day, e.g. `"0930"` = Sep 30 |
| `updated_at`     | TEXT | ISO 8601 timestamp of last fetch |

---

### `filings`

One row per filing (10-K, 10-Q, amendments). Populated by `sec-edgar fetch`.

| Column           | Type | Description |
|------------------|------|-------------|
| `id`             | INTEGER PK | Auto-increment |
| `cik`            | TEXT FK | → `companies.cik` |
| `accession_no`   | TEXT UNIQUE | SEC accession number, format `XXXXXXXXXX-YY-ZZZZZZ` |
| `form_type`      | TEXT | e.g. `10-K`, `10-Q`, `10-K/A`, `10-Q/A` |
| `filed_date`     | TEXT | Date filed with SEC (`YYYY-MM-DD`) |
| `report_date`    | TEXT | Period end date covered by the filing |
| `document_count` | INTEGER | Number of documents in the filing package |
| `primary_doc`    | TEXT | Filename of the primary document |
| `xbrl_fetched`   | INTEGER | `0` = XBRL not yet fetched, `1` = fetched |
| `fetched_at`     | TEXT | ISO 8601 timestamp when XBRL was fetched |

**Indexes:**
- `idx_filings_accession` on `accession_no` (unique)
- `idx_filings_cik` on `cik`
- `idx_filings_cik_form` on `(cik, form_type, filed_date)`

---

### `xbrl_facts`

The core data table. Each row is one XBRL data point from a filing.
Populated by `sec-edgar fetch`.

| Column         | Type | Description |
|----------------|------|-------------|
| `id`           | INTEGER PK | Auto-increment |
| `cik`          | TEXT FK | → `companies.cik` |
| `taxonomy`     | TEXT | XBRL taxonomy, usually `us-gaap` or `dei` |
| `concept`      | TEXT | XBRL concept name, e.g. `RevenueFromContractWithCustomerExcludingAssessedTax` |
| `label`        | TEXT | Human-readable label from the taxonomy |
| `unit`         | TEXT | Unit of measurement: `USD`, `shares`, `USD/shares`, `pure` |
| `period_type`  | TEXT | `instant` (balance sheet) or `duration` (income/cash flow) |
| `period_start` | TEXT | Start of reporting period (`YYYY-MM-DD`), NULL for instant facts |
| `period_end`   | TEXT | End of reporting period (`YYYY-MM-DD`) |
| `value`        | REAL | Numeric value (as reported, no scaling) |
| `value_text`   | TEXT | Original string value (for non-numeric facts) |
| `accession_no` | TEXT | Filing this fact came from |
| `fiscal_year`  | INTEGER | Fiscal year integer, e.g. `2024` |
| `fiscal_period`| TEXT | `FY`, `Q1`, `Q2`, `Q3`, or `Q4` |
| `form`         | TEXT | Form type of the source filing |
| `filed_date`   | TEXT | Date the source filing was filed |
| `frame`        | TEXT | SEC frame tag (e.g. `CY2024Q1I`), may be NULL |

**Unique constraint:** `(cik, taxonomy, concept, unit, period_end, accession_no)`
— prevents duplicate facts from re-fetches.

**Indexes:**
- `idx_xbrl_facts_unique` on `(cik, taxonomy, concept, unit, period_end, accession_no)` (unique)
- `idx_xbrl_facts_lookup` on `(cik, concept, period_end)` — fast metric lookups
- `idx_xbrl_facts_accession` on `accession_no`

---

### `metric_mappings`

Maps standardized metric names to their underlying XBRL concepts.
Seeded automatically from code on every `get_connection()` call — do not edit directly.

| Column         | Type | Description |
|----------------|------|-------------|
| `metric_name`  | TEXT | Standardized name, e.g. `revenue`, `net_income` |
| `display_name` | TEXT | Human-readable label for reports |
| `statement`    | TEXT | `income_statement`, `balance_sheet`, or `cash_flow` |
| `period_type`  | TEXT | `instant` or `duration` |
| `unit`         | TEXT | Expected unit: `USD`, `shares`, `USD/shares` |
| `section`      | TEXT | Report section grouping |
| `indent`       | INTEGER | Display indent level (0 = top-level, 1 = indented) |
| `sort_order`   | INTEGER | Row ordering within the report |
| `is_derived`   | INTEGER | `1` = computed from other metrics (not in XBRL), `0` = direct |
| `concept`      | TEXT | XBRL concept name |
| `taxonomy`     | TEXT | XBRL taxonomy (default `us-gaap`) |
| `priority`     | INTEGER | Lower = preferred when multiple concepts map to the same metric |

**Primary key:** `(metric_name, concept, taxonomy)` — one metric can have multiple
concept mappings (e.g. `revenue` maps to both `Revenues` and
`RevenueFromContractWithCustomerExcludingAssessedTax`; lowest priority wins).

---

## Standardized Metrics

### Income Statement

| Metric ID | Display Name | Unit | Section |
|-----------|-------------|------|---------|
| `revenue` | Revenue | USD | revenue |
| `cost_of_revenue` | Cost of Revenue | USD | revenue |
| `gross_profit` | Gross Profit | USD | revenue |
| `research_development` | Research & Development | USD | opex |
| `selling_general_admin` | Selling, General & Admin | USD | opex |
| `operating_expenses` | Total Operating Expenses | USD | opex |
| `operating_income` | Operating Income (EBIT) | USD | operating |
| `interest_expense` | Interest Expense | USD | below_line |
| `other_income_expense` | Other Income (Expense), net | USD | below_line |
| `income_before_tax` | Income Before Tax | USD | below_line |
| `income_tax` | Income Tax Expense | USD | below_line |
| `net_income` | Net Income | USD | bottom_line |
| `depreciation_amortization` | Depreciation & Amortization | USD | supplemental |
| `ebitda` | EBITDA | USD | supplemental |
| `eps_basic` | EPS (Basic) | USD/shares | per_share |
| `eps_diluted` | EPS (Diluted) | USD/shares | per_share |
| `shares_basic` | Shares Outstanding (Basic) | shares | per_share |
| `shares_diluted` | Shares Outstanding (Diluted) | shares | per_share |

### Balance Sheet

| Metric ID | Display Name | Unit | Section |
|-----------|-------------|------|---------|
| `cash_equivalents` | Cash & Equivalents | USD | current_assets |
| `short_term_investments` | Short-term Investments | USD | current_assets |
| `accounts_receivable` | Accounts Receivable, net | USD | current_assets |
| `inventory` | Inventories | USD | current_assets |
| `other_current_assets` | Other Current Assets | USD | current_assets |
| `total_current_assets` | Total Current Assets | USD | current_assets |
| `ppe_net` | Property, Plant & Equipment, net | USD | noncurrent_assets |
| `goodwill` | Goodwill | USD | noncurrent_assets |
| `intangible_assets` | Intangible Assets, net | USD | noncurrent_assets |
| `long_term_investments` | Long-term Investments | USD | noncurrent_assets |
| `other_noncurrent_assets` | Other Non-Current Assets | USD | noncurrent_assets |
| `total_assets` | Total Assets | USD | noncurrent_assets |
| `accounts_payable` | Accounts Payable | USD | current_liabilities |
| `short_term_debt` | Short-term Debt & Current Portion | USD | current_liabilities |
| `deferred_revenue_current` | Deferred Revenue (Current) | USD | current_liabilities |
| `other_current_liabilities` | Other Current Liabilities | USD | current_liabilities |
| `total_current_liabilities` | Total Current Liabilities | USD | current_liabilities |
| `long_term_debt` | Long-term Debt | USD | noncurrent_liabilities |
| `deferred_tax_liabilities` | Deferred Tax Liabilities | USD | noncurrent_liabilities |
| `other_noncurrent_liabilities` | Other Non-Current Liabilities | USD | noncurrent_liabilities |
| `total_liabilities` | Total Liabilities | USD | noncurrent_liabilities |
| `common_stock_apic` | Common Stock & APIC | USD | equity |
| `retained_earnings` | Retained Earnings (Deficit) | USD | equity |
| `treasury_stock` | Treasury Stock | USD | equity |
| `total_equity` | Total Shareholders' Equity | USD | equity |
| `total_liabilities_equity` | Total Liabilities & Equity | USD | equity |

### Cash Flow Statement

| Metric ID | Display Name | Unit | Section |
|-----------|-------------|------|---------|
| `cf_net_income` | Net Income | USD | operating |
| `cf_depreciation` | Depreciation & Amortization | USD | operating |
| `cf_stock_compensation` | Stock-based Compensation | USD | operating |
| `cf_working_capital` | Changes in Working Capital | USD | operating |
| `cf_operating` | Net Cash from Operations | USD | operating |
| `capex` | Capital Expenditures | USD | investing |
| `acquisitions` | Acquisitions, net of cash | USD | investing |
| `investment_purchases` | Purchases of Investments | USD | investing |
| `investment_proceeds` | Sales/Maturities of Investments | USD | investing |
| `cf_investing` | Net Cash from Investing | USD | investing |
| `debt_issuance` | Proceeds from Debt Issuance | USD | financing |
| `debt_repayment` | Repayment of Debt | USD | financing |
| `share_repurchases` | Share Repurchases | USD | financing |
| `dividends_paid` | Dividends Paid | USD | financing |
| `cf_financing` | Net Cash from Financing | USD | financing |
| `free_cash_flow` | Free Cash Flow | USD | summary |
| `net_change_in_cash` | Net Change in Cash | USD | summary |

### Computed Metrics (Ratios & Valuation)

These are derived at report time and do not live in `xbrl_facts`.

| Metric ID | Section | Format |
|-----------|---------|--------|
| `gross_margin` | Profitability | percent |
| `operating_margin` | Profitability | percent |
| `ebitda_margin` | Profitability | percent |
| `net_margin` | Profitability | percent |
| `rd_pct_revenue` | Profitability | percent |
| `sga_pct_revenue` | Profitability | percent |
| `roe` | Profitability | percent |
| `roa` | Profitability | percent |
| `roic` | Profitability | percent |
| `working_capital` | Liquidity | currency |
| `current_ratio` | Liquidity | times |
| `quick_ratio` | Liquidity | times |
| `cash_ratio` | Liquidity | times |
| `total_debt` | Leverage | currency |
| `net_debt` | Leverage | currency |
| `debt_to_equity` | Leverage | times |
| `net_debt_to_equity` | Leverage | times |
| `net_debt_to_ebitda` | Leverage | times |
| `debt_to_assets` | Leverage | percent |
| `interest_coverage` | Leverage | times |
| `equity_multiplier` | Leverage | times |
| `asset_turnover` | Efficiency | times |
| `inventory_turnover` | Efficiency | times |
| `receivables_turnover` | Efficiency | times |
| `dso` | Efficiency | days |
| `dio` | Efficiency | days |
| `dpo` | Efficiency | days |
| `ccc` | Efficiency | days |
| `capex_pct_revenue` | Efficiency | percent |
| `capex_to_da` | Efficiency | times |
| `operating_cf_margin` | Cash Flow Quality | percent |
| `fcf_margin` | Cash Flow Quality | percent |
| `fcf_conversion` | Cash Flow Quality | percent |
| `fcf_per_share` | Cash Flow Quality | USD/share |
| `sbc_margin` | Cash Flow Quality | percent |
| `repurchase_margin` | Cash Flow Quality | percent |
| `dividend_margin` | Cash Flow Quality | percent |
| `book_value_per_share` | Per Share | USD/share |
| `tangible_bvps` | Per Share | USD/share |
| `revenue_per_share` | Per Share | USD/share |
| `revenue_growth` | Growth | percent (YoY) |
| `revenue_qoq` | Growth | percent (QoQ) |
| `ni_growth` / `ni_qoq` | Growth | percent |
| `eps_growth` / `eps_qoq` | Growth | percent |
| `fcf_growth` / `fcf_qoq` | Growth | percent |
| `cf_operating_yoy` / `cf_operating_qoq` | Growth | percent |
| `revenue_cagr` / `ni_cagr` / `eps_cagr` / `fcf_cagr` | Growth | percent |
| `pe` / `ps` / `pb` / `p_fcf` | Market Multiples | multiple (requires `--price`) |
| `ev_revenue` / `ev_ebitda` / `ev_ebit` / `ev_fcf` | Market Multiples | multiple (requires `--price`) |
| `earnings_yield` / `fcf_yield` | Market Multiples | percent (requires `--price`) |

---

## Example Queries

### Inspect what's in the database

```sql
-- List all companies
SELECT ticker, name, sic_desc, fiscal_year_end, updated_at
FROM companies
ORDER BY ticker;

-- Show all filings for one company
SELECT form_type, filed_date, report_date, xbrl_fetched
FROM filings
WHERE cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
ORDER BY filed_date DESC;

-- Check XBRL fetch status summary
SELECT form_type,
       COUNT(*) AS total,
       SUM(xbrl_fetched) AS fetched,
       COUNT(*) - SUM(xbrl_fetched) AS pending
FROM filings
GROUP BY form_type;
```

### Browse available XBRL concepts

```sql
-- All concept/unit pairs for a company with date ranges
SELECT taxonomy, concept, unit, COUNT(*) AS facts,
       MIN(period_end) AS earliest, MAX(period_end) AS latest
FROM xbrl_facts
WHERE cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
GROUP BY taxonomy, concept, unit
ORDER BY concept;

-- Find all concepts that contain "Revenue"
SELECT DISTINCT concept, label
FROM xbrl_facts
WHERE concept LIKE '%Revenue%'
ORDER BY concept;
```

### Browse standardized metric mappings

```sql
-- All standardized metrics with their XBRL concept mappings
SELECT metric_name, display_name, statement, concept, priority
FROM metric_mappings
ORDER BY statement, sort_order, priority;

-- See which concepts map to "revenue" (multiple concepts, priority-ranked)
SELECT concept, taxonomy, priority
FROM metric_mappings
WHERE metric_name = 'revenue'
ORDER BY priority;
```

### Annual financials

```sql
-- Annual revenue for AAPL (most recent filing per year, in billions)
WITH ranked AS (
  SELECT f.fiscal_year,
         f.value / 1e9 AS revenue_bn,
         ROW_NUMBER() OVER (PARTITION BY f.fiscal_year ORDER BY f.filed_date DESC) AS rn
  FROM xbrl_facts f
  JOIN metric_mappings mm
    ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE f.cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
    AND mm.metric_name = 'revenue'
    AND mm.statement = 'income_statement'
    AND f.fiscal_period = 'FY'
    AND f.form IN ('10-K', '10-K/A')
)
SELECT fiscal_year, ROUND(revenue_bn, 2) AS revenue_billions
FROM ranked WHERE rn = 1
ORDER BY fiscal_year DESC;

-- Multi-company annual net income comparison
WITH ranked AS (
  SELECT c.ticker, f.fiscal_year, f.value / 1e9 AS ni_bn,
         ROW_NUMBER() OVER (
           PARTITION BY c.ticker, f.fiscal_year ORDER BY f.filed_date DESC
         ) AS rn
  FROM xbrl_facts f
  JOIN companies c ON c.cik = f.cik
  JOIN metric_mappings mm
    ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE c.ticker IN ('AAPL', 'MSFT', 'GOOGL')
    AND mm.metric_name = 'net_income'
    AND mm.statement = 'income_statement'
    AND f.fiscal_period = 'FY'
    AND f.form IN ('10-K', '10-K/A')
)
SELECT ticker, fiscal_year, ROUND(ni_bn, 2) AS net_income_billions
FROM ranked WHERE rn = 1
ORDER BY fiscal_year DESC, ticker;
```

### Quarterly financials

```sql
-- Quarterly revenue for AAPL (last 8 quarters)
WITH ranked AS (
  SELECT f.fiscal_year, f.fiscal_period, f.period_end,
         f.value / 1e9 AS revenue_bn,
         ROW_NUMBER() OVER (
           PARTITION BY f.fiscal_year, f.fiscal_period ORDER BY f.filed_date DESC
         ) AS rn
  FROM xbrl_facts f
  JOIN metric_mappings mm
    ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE f.cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
    AND mm.metric_name = 'revenue'
    AND mm.statement = 'income_statement'
    AND f.fiscal_period IN ('Q1', 'Q2', 'Q3', 'Q4')
    AND f.form IN ('10-Q', '10-Q/A')
)
SELECT fiscal_year, fiscal_period, period_end, ROUND(revenue_bn, 2) AS revenue_billions
FROM ranked WHERE rn = 1
ORDER BY period_end DESC
LIMIT 8;
```

### Cross-statement queries

```sql
-- Annual free cash flow yield: FCF / Revenue (requires both statements)
WITH
revenue AS (
  SELECT f.fiscal_year, f.value AS rev,
         ROW_NUMBER() OVER (PARTITION BY f.fiscal_year ORDER BY f.filed_date DESC) AS rn
  FROM xbrl_facts f
  JOIN metric_mappings mm ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE f.cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
    AND mm.metric_name = 'revenue' AND mm.statement = 'income_statement'
    AND f.fiscal_period = 'FY'
),
capex AS (
  SELECT f.fiscal_year, f.value AS capex,
         ROW_NUMBER() OVER (PARTITION BY f.fiscal_year ORDER BY f.filed_date DESC) AS rn
  FROM xbrl_facts f
  JOIN metric_mappings mm ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE f.cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
    AND mm.metric_name = 'capex' AND mm.statement = 'cash_flow'
    AND f.fiscal_period = 'FY'
),
cf_operating AS (
  SELECT f.fiscal_year, f.value AS cfo,
         ROW_NUMBER() OVER (PARTITION BY f.fiscal_year ORDER BY f.filed_date DESC) AS rn
  FROM xbrl_facts f
  JOIN metric_mappings mm ON mm.concept = f.concept AND mm.taxonomy = f.taxonomy
  WHERE f.cik = (SELECT cik FROM companies WHERE ticker = 'AAPL')
    AND mm.metric_name = 'cf_operating' AND mm.statement = 'cash_flow'
    AND f.fiscal_period = 'FY'
)
SELECT r.fiscal_year,
       ROUND(r.rev / 1e9, 1) AS revenue_bn,
       ROUND((c.cfo - cx.capex) / 1e9, 1) AS fcf_bn,
       ROUND((c.cfo - cx.capex) * 100.0 / r.rev, 1) AS fcf_margin_pct
FROM revenue r
JOIN cf_operating c ON c.fiscal_year = r.fiscal_year AND c.rn = 1
JOIN capex cx ON cx.fiscal_year = r.fiscal_year AND cx.rn = 1
WHERE r.rn = 1
ORDER BY r.fiscal_year DESC;
```

### Raw XBRL exploration

```sql
-- All facts for a specific concept, any company
SELECT c.ticker, f.fiscal_year, f.fiscal_period, f.form,
       f.value / 1e9 AS value_bn, f.filed_date
FROM xbrl_facts f
JOIN companies c ON c.cik = f.cik
WHERE f.concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'
  AND f.fiscal_period = 'FY'
ORDER BY c.ticker, f.fiscal_year DESC;

-- Find duplicate/restated facts (multiple filed_dates for same period)
SELECT cik, concept, fiscal_year, fiscal_period, COUNT(*) AS versions,
       MIN(filed_date) AS first_filed, MAX(filed_date) AS last_filed
FROM xbrl_facts
WHERE fiscal_period = 'FY'
GROUP BY cik, concept, fiscal_year, fiscal_period
HAVING COUNT(*) > 1
ORDER BY versions DESC
LIMIT 20;

-- Database size summary
SELECT
  (SELECT COUNT(*) FROM companies)     AS companies,
  (SELECT COUNT(*) FROM filings)       AS filings,
  (SELECT SUM(xbrl_fetched) FROM filings) AS filings_with_xbrl,
  (SELECT COUNT(*) FROM xbrl_facts)    AS total_facts,
  (SELECT COUNT(DISTINCT concept) FROM xbrl_facts) AS unique_concepts;
```

---

## Notes

- **Values are stored unscaled** — exactly as reported to the SEC (e.g. Apple reports
  in USD, so `value = 391035000000` for $391B revenue). Divide by `1e6` for millions,
  `1e9` for billions.
- **Restatements**: When a company files an amendment (10-K/A, 10-Q/A), both the
  original and amended facts are stored. The report system picks the most recently
  filed version via `ROW_NUMBER() OVER (... ORDER BY filed_date DESC)`.
- **Multiple concept mappings**: Some metrics (e.g. `revenue`) map to several XBRL
  concepts with different priorities. The lowest-priority concept wins; this handles
  companies that use non-standard concept names.
- **Derived metrics** (`ebitda`, `free_cash_flow`) are not stored in `xbrl_facts` —
  they are computed at report time from their component metrics.
- **WAL mode** is enabled on every connection for safe concurrent reads during writes.
