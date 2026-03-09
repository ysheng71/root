"""
Parse SEC EDGAR API responses into flat dicts ready for database insertion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


FILING_FORM_TYPES = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def _normalize_accession(raw: str) -> str:
    """
    Normalize accession number to dashed format: XXXXXXXXXX-YY-ZZZZZZ.
    Input may be 'XXXXXXXXXX-YY-ZZZZZZ' (already dashed) or 'XXXXXXXXXXYYYYZZZZZZ' (no dashes).
    """
    clean = raw.replace("-", "")
    if len(clean) == 18:
        return f"{clean[:10]}-{clean[10:12]}-{clean[12:]}"
    return raw  # return as-is if unexpected format


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_submissions(raw: dict) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Parse company submissions response.

    Returns:
        (company_data, filings_list) where company_data maps to the companies
        table and filings_list is a list of dicts for the filings table.
    """
    cik = str(raw.get("cik", "")).zfill(10)

    company_data: dict[str, Any] = {
        "cik": cik,
        "ticker": _extract_primary_ticker(raw),
        "name": raw.get("name", ""),
        "sic": raw.get("sic", None),
        "sic_desc": raw.get("sicDescription", None),
        "ein": raw.get("ein", None),
        "state_inc": raw.get("stateOfIncorporation", None),
        "fiscal_year_end": raw.get("fiscalYearEnd", None),
        "updated_at": _now_iso(),
    }

    filings_list: list[dict[str, Any]] = []
    recent = raw.get("filings", {}).get("recent", {})
    if not recent:
        return company_data, filings_list

    # All fields in recent are parallel arrays of the same length
    accessions = recent.get("accessionNumber", [])
    form_types = recent.get("form", [])
    filed_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    doc_counts = recent.get("size", [])  # 'size' is file count in recent
    primary_docs = recent.get("primaryDocument", [])
    # isXBRL flag: 1 if filing has inline XBRL
    is_xbrl = recent.get("isXBRL", [0] * len(accessions))

    for i, accession_raw in enumerate(accessions):
        form = form_types[i] if i < len(form_types) else ""
        # Only store 10-K and 10-Q (including amendments)
        if form not in FILING_FORM_TYPES:
            continue

        filings_list.append({
            "cik": cik,
            "accession_no": _normalize_accession(accession_raw),
            "form_type": form,
            "filed_date": filed_dates[i] if i < len(filed_dates) else None,
            "report_date": report_dates[i] if i < len(report_dates) else None,
            "document_count": doc_counts[i] if i < len(doc_counts) else None,
            "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
        })

    return company_data, filings_list


def _extract_primary_ticker(raw: dict) -> str:
    """Extract the primary ticker from submissions response."""
    tickers = raw.get("tickers", [])
    if tickers:
        return tickers[0].upper()
    # Fallback: try exchanges list
    return raw.get("name", "UNKNOWN")[:10].upper()


def parse_company_facts(cik: str, raw: dict) -> list[dict[str, Any]]:
    """
    Parse companyfacts response into a flat list of fact dicts.

    The API response shape:
      {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
          "us-gaap": {
            "ConceptName": {
              "label": "...",
              "description": "...",
              "units": {
                "USD": [
                  {
                    "end": "2023-09-30",
                    "val": 394328000000,
                    "accn": "0000320193-23-000077",
                    "fy": 2023,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2023-11-03",
                    "start": "2022-10-01",   # present for duration facts only
                    "frame": "CY2023"        # optional
                  }, ...
                ]
              }
            }
          },
          "dei": { ... }
        }
      }
    """
    cik10 = str(cik).zfill(10)
    facts_section = raw.get("facts", {})
    result: list[dict[str, Any]] = []

    for taxonomy, concepts in facts_section.items():
        for concept, concept_data in concepts.items():
            label = concept_data.get("label")
            units_map = concept_data.get("units", {})

            for unit, entries in units_map.items():
                for entry in entries:
                    period_end = entry.get("end")
                    if not period_end:
                        continue

                    period_start = entry.get("start")  # None for instant facts
                    period_type = "duration" if period_start else "instant"

                    raw_val = entry.get("val")
                    if isinstance(raw_val, (int, float)):
                        value = float(raw_val)
                        value_text = None
                    elif isinstance(raw_val, str):
                        value = None
                        value_text = raw_val
                    else:
                        value = None
                        value_text = None

                    accn = entry.get("accn", "")

                    result.append({
                        "cik": cik10,
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "label": label,
                        "unit": unit,
                        "period_type": period_type,
                        "period_start": period_start,
                        "period_end": period_end,
                        "value": value,
                        "value_text": value_text,
                        "accession_no": _normalize_accession(accn) if accn else None,
                        "fiscal_year": entry.get("fy"),
                        "fiscal_period": entry.get("fp"),
                        "form": entry.get("form"),
                        "filed_date": entry.get("filed"),
                        "frame": entry.get("frame"),
                    })

    return result
