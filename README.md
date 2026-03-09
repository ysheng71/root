# sec-edgar

Downloads 10-K/10-Q filings from the SEC EDGAR API, parses XBRL data, and stores
everything in a local SQLite database. Generates standardized Income Statement,
Balance Sheet, and Cash Flow reports for any publicly traded US company.

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Setup

The SEC requires a `User-Agent` header on all API requests identifying who you are.
Set it once as an environment variable so you don't have to repeat it:

```bash
export EDGAR_USER_AGENT="Jane Doe jane@example.com"
```

Optionally, also set a default database path:

```bash
export EDGAR_DB="~/data/edgar.db"
```

Both can be overridden per-command with `--user-agent` and `--db`.

---

## Commands

### `fetch` — Download filings

Downloads submissions metadata and XBRL facts for one or more tickers.
Re-runs are safe: only new filings are fetched (incremental).

```bash
# Fetch all 10-K, 10-Q, and amendments for a single ticker
sec-edgar fetch AAPL

# Fetch multiple tickers at once
sec-edgar fetch AAPL MSFT GOOGL AMZN NVDA

# Fetch only annual reports (10-K)
sec-edgar fetch TSLA --forms 10-K

# Fetch only quarterly reports (10-Q, including amendments)
sec-edgar fetch META --forms 10-Q,10-Q/A

# Preview what would be fetched without writing to the database
sec-edgar fetch AAPL --dry-run

# Show detailed output (total facts parsed per company)
sec-edgar fetch AAPL MSFT --verbose

# Use a non-default database file
sec-edgar --db ~/portfolios/tech.db fetch AAPL MSFT GOOGL
```

**Notes:**
- The SEC rate-limits requests to 10/second; the tool stays safely under that limit.
- On first run for a company, one API call fetches the full XBRL history (~5–20 MB).
- Subsequent runs skip the XBRL fetch if all filings are already up to date.

---

### `report` — Standardized financial statements

Generates Income Statement, Balance Sheet, and/or Cash Flow Statement using
standardized metric names mapped from raw XBRL concepts.

**Output formats:** `text` (terminal), `csv` (file), `excel` (.xlsx workbook)

#### Text output (default)

```bash
# All three statements, annual, last 5 years
sec-edgar report AAPL

# Income Statement only
sec-edgar report AAPL --statement income-statement

# Balance Sheet, last 4 years
sec-edgar report AAPL --statement balance-sheet --years 4

# Cash Flow Statement
sec-edgar report AAPL --statement cash-flow

# Quarterly view, most recent 8 quarters (default)
sec-edgar report AAPL --period quarterly

# Quarterly, last 6 quarters
sec-edgar report AAPL --statement income-statement --period quarterly --quarters 6

# Show values in thousands instead of millions
sec-edgar report AAPL --scale thousands

# Show raw values (no scaling)
sec-edgar report AAPL --statement balance-sheet --scale raw

# Save text output to a file
sec-edgar report AAPL -o AAPL_report.txt
```

#### CSV output

```bash
# Single statement to stdout
sec-edgar report AAPL --statement income-statement --format csv

# Single statement to a file
sec-edgar report AAPL --statement income-statement --format csv -o AAPL_income.csv

# All three statements — creates AAPL_income-statement.csv,
# AAPL_balance-sheet.csv, AAPL_cash-flow.csv in current directory
sec-edgar report AAPL --statement all --format csv

# Save to a specific directory
sec-edgar report AAPL --statement all --format csv --output-dir ./reports/

# Multiple tickers — one file per ticker/statement combination
sec-edgar report AAPL MSFT GOOGL --statement all --format csv --output-dir ./reports/

# Quarterly cash flow to CSV
sec-edgar report AAPL --statement cash-flow --period quarterly --quarters 8 \
  --format csv -o AAPL_cf_quarterly.csv
```

The CSV includes metadata rows at the top (company, ticker, statement name, period,
scale) followed by a data table with columns: `Metric`, `Metric ID`, `Unit`, and one
column per period.

#### Excel output

```bash
# All statements in a single workbook (one sheet per statement)
sec-edgar report AAPL --format excel -o AAPL_financials.xlsx

# Annual income statement only
sec-edgar report AAPL --statement income-statement --format excel -o AAPL_IS.xlsx

# Quarterly, all statements
sec-edgar report AAPL --statement all --period quarterly --quarters 8 \
  --format excel -o AAPL_quarterly.xlsx

# Multiple tickers — one workbook per ticker, auto-named
sec-edgar report AAPL MSFT GOOGL --format excel --output-dir ./reports/
# Creates: reports/AAPL_financials.xlsx, reports/MSFT_financials.xlsx, ...

# 10-year annual history
sec-edgar report AAPL --years 10 --format excel -o AAPL_10yr.xlsx
```

Excel workbooks have:
- One sheet per statement (Income Statement, Balance Sheet, Cash Flow Statement)
- Formatted headers, number formatting, alternating row shading
- Frozen header row and label column for easy scrolling

#### `--statement` values

| Value              | Description                        |
|--------------------|------------------------------------|
| `all` (default)    | All three statements               |
| `income-statement` | Revenue, expenses, net income      |
| `balance-sheet`    | Assets, liabilities, equity        |
| `cash-flow`        | Operating, investing, financing CF |

#### `--scale` values

| Value      | Description                          |
|------------|--------------------------------------|
| `millions` (default) | USD values divided by 1,000,000 |
| `thousands`| USD values divided by 1,000          |
| `billions` | USD values divided by 1,000,000,000  |
| `raw`      | Exact values as reported to the SEC  |

---

### `ls` — List companies in the database

```bash
# Show all companies fetched so far
sec-edgar ls

# Use a non-default database
sec-edgar --db ~/portfolios/tech.db ls
```

Output columns: ticker, CIK, company name, SIC code, fiscal year end.

---

### `info` — Filing and concept summary for a ticker

```bash
# Show filing history and available XBRL concepts for Apple
sec-edgar info AAPL

# Use a non-default database
sec-edgar --db ~/portfolios/tech.db info MSFT
```

Shows:
- Company metadata (name, CIK, SIC, fiscal year end)
- Most recent 20 filings with form type, dates, and XBRL fetch status
- All XBRL concept/unit pairs available for the company, with fact counts
  and date ranges — useful for knowing which concepts are populated before
  running `export`

---

### `export` — Raw XBRL fact export

Exports raw XBRL facts (before standardized metric mapping) to CSV or JSON.
Useful for custom analysis or accessing concepts not covered by the standard reports.

```bash
# Export all facts for AAPL to stdout (CSV)
sec-edgar export AAPL

# Export specific concepts
sec-edgar export AAPL --concepts Revenues,NetIncomeLoss

# Export to a file
sec-edgar export AAPL --concepts Revenues,NetIncomeLoss -o aapl_revenue.csv

# Export as JSON
sec-edgar export AAPL --concepts Assets,AssetsCurrent --format json -o aapl_assets.json

# Export from 10-K only (exclude 10-Q)
sec-edgar export AAPL --concepts NetIncomeLoss --forms 10-K -o aapl_annual_ni.csv

# Export multiple tickers to stdout
sec-edgar export AAPL MSFT --concepts RevenueFromContractWithCustomerExcludingAssessedTax

# Save to a file
sec-edgar export AAPL MSFT GOOGL \
  --concepts Revenues,RevenueFromContractWithCustomerExcludingAssessedTax,NetIncomeLoss \
  --format csv -o faang_revenue.csv
```

Output columns: `ticker`, `name`, `taxonomy`, `concept`, `label`, `unit`,
`period_type`, `period_start`, `period_end`, `value`, `value_text`,
`fiscal_year`, `fiscal_period`, `form`, `filed_date`, `frame`, `accession_no`.

---

## Global options

These apply to all commands and can be placed before the command name:

```bash
sec-edgar --db PATH --user-agent "Name email" COMMAND [OPTIONS]
```

| Option          | Env var              | Default      | Description                              |
|-----------------|----------------------|--------------|------------------------------------------|
| `--db PATH`     | `EDGAR_DB`           | `edgar.db`   | SQLite database file path                |
| `--user-agent`  | `EDGAR_USER_AGENT`   | *(required)* | `"Name email"` as required by SEC policy |

---

## Typical workflow

```bash
# 1. Set credentials once
export EDGAR_USER_AGENT="Jane Doe jane@example.com"
export EDGAR_DB="edgar.db"

# 2. Fetch filings for companies of interest
sec-edgar fetch AAPL MSFT GOOGL AMZN NVDA META

# 3. Verify what was collected
sec-edgar ls
sec-edgar info AAPL

# 4. View reports in terminal
sec-edgar report AAPL
sec-edgar report AAPL --statement cash-flow --period quarterly

# 5. Export for further analysis
sec-edgar report AAPL MSFT GOOGL --statement all --format excel --output-dir ./reports/

# 6. Re-run fetch anytime to pick up new filings — already-fetched data is skipped
sec-edgar fetch AAPL MSFT GOOGL AMZN NVDA META
```

---

## Database schema

The SQLite database contains four tables:

| Table             | Description                                              |
|-------------------|----------------------------------------------------------|
| `companies`       | Company metadata (CIK, ticker, name, SIC, fiscal year end) |
| `filings`         | Filing index (accession number, form type, dates, fetch status) |
| `xbrl_facts`      | All raw XBRL facts (concept, unit, period, value)        |
| `metric_mappings` | Standardized metric → XBRL concept mapping table        |

The database can be queried directly with any SQLite tool:

```bash
sqlite3 edgar.db "
  SELECT ticker, concept, fiscal_year, value / 1e9 as billions
  FROM xbrl_facts f JOIN companies c ON c.cik = f.cik
  WHERE ticker = 'AAPL'
    AND concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'
    AND fiscal_period = 'FY'
    AND form = '10-K'
  ORDER BY fiscal_year DESC
  LIMIT 5;
"

# Browse available standardized metrics
sqlite3 edgar.db "
  SELECT DISTINCT metric_name, display_name, statement
  FROM metric_mappings
  ORDER BY statement, sort_order;
"
```
