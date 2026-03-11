"""
Tests for sec_edgar/parser.py — submissions and company facts parsing.
Uses inline fixture dicts; no network calls.
"""

import pytest

from sec_edgar.parser import (
    _normalize_accession,
    parse_company_facts,
    parse_submissions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _submissions_fixture(**overrides):
    base = {
        "cik": 320193,
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "ein": "94-2404110",
        "stateOfIncorporation": "CA",
        "fiscalYearEnd": "0930",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-24-000123",
                    "0000320193-23-000077",
                    "0000320193-23-000055",  # 8-K (should be filtered)
                ],
                "form": ["10-K", "10-Q", "8-K"],
                "filingDate": ["2024-11-01", "2024-02-02", "2023-12-01"],
                "reportDate": ["2024-09-28", "2023-12-30", "2023-12-01"],
                "size": [120, 80, 10],
                "primaryDocument": ["aapl-20240928.htm", "aapl-20231230.htm", ""],
                "isXBRL": [1, 1, 0],
            }
        },
    }
    base.update(overrides)
    return base


def _facts_fixture():
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            {
                                "start": "2022-10-01",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "accn": "0000320193-23-000077",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "frame": "CY2023",
                            }
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                # Instant fact — no "start" key
                                "end": "2023-09-30",
                                "val": 352583000000,
                                "accn": "0000320193-23-000077",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                            }
                        ]
                    },
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# _normalize_accession
# ---------------------------------------------------------------------------

class TestNormalizeAccession:
    def test_already_dashed(self):
        raw = "0000320193-24-000123"
        assert _normalize_accession(raw) == "0000320193-24-000123"

    def test_undashed_18_chars(self):
        # Remove dashes: "000032019324000123" (18 chars)
        raw = "000032019324000123"
        assert _normalize_accession(raw) == "0000320193-24-000123"

    def test_unexpected_format_passthrough(self):
        raw = "short"
        assert _normalize_accession(raw) == "short"

    def test_roundtrip(self):
        dashed = "0001234567-21-098765"
        undashed = dashed.replace("-", "")
        assert _normalize_accession(undashed) == dashed


# ---------------------------------------------------------------------------
# parse_submissions
# ---------------------------------------------------------------------------

class TestParseSubmissions:
    def test_company_fields(self):
        company, _ = parse_submissions(_submissions_fixture())
        assert company["cik"] == "0000320193"
        assert company["ticker"] == "AAPL"
        assert company["name"] == "Apple Inc."
        assert company["sic"] == "3571"
        assert company["sic_desc"] == "Electronic Computers"
        assert company["fiscal_year_end"] == "0930"
        assert company["state_inc"] == "CA"

    def test_cik_zero_padded(self):
        company, _ = parse_submissions(_submissions_fixture(cik=12345))
        assert company["cik"] == "0000012345"
        assert len(company["cik"]) == 10

    def test_filters_non_10k_10q(self):
        _, filings = parse_submissions(_submissions_fixture())
        form_types = {f["form_type"] for f in filings}
        assert "8-K" not in form_types

    def test_only_10k_and_10q_included(self):
        _, filings = parse_submissions(_submissions_fixture())
        assert len(filings) == 2
        assert filings[0]["form_type"] == "10-K"
        assert filings[1]["form_type"] == "10-Q"

    def test_accession_normalized(self):
        _, filings = parse_submissions(_submissions_fixture())
        for f in filings:
            # Dashed format: XXXXXXXXXX-YY-ZZZZZZ
            parts = f["accession_no"].split("-")
            assert len(parts) == 3

    def test_dates_populated(self):
        _, filings = parse_submissions(_submissions_fixture())
        assert filings[0]["filed_date"] == "2024-11-01"
        assert filings[0]["report_date"] == "2024-09-28"

    def test_empty_filings(self):
        raw = _submissions_fixture()
        raw["filings"]["recent"] = {}
        company, filings = parse_submissions(raw)
        assert filings == []
        assert company["name"] == "Apple Inc."

    def test_updated_at_populated(self):
        company, _ = parse_submissions(_submissions_fixture())
        assert company["updated_at"]  # non-empty ISO timestamp

    def test_amendment_forms_included(self):
        raw = _submissions_fixture()
        raw["filings"]["recent"]["form"] = ["10-K/A", "10-Q/A", "8-K"]
        _, filings = parse_submissions(raw)
        form_types = {f["form_type"] for f in filings}
        assert "10-K/A" in form_types
        assert "10-Q/A" in form_types


# ---------------------------------------------------------------------------
# parse_company_facts
# ---------------------------------------------------------------------------

class TestParseCompanyFacts:
    def test_returns_list(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        assert isinstance(result, list)

    def test_duration_fact(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        revenues = [r for r in result if r["concept"] == "Revenues"]
        assert len(revenues) == 1
        r = revenues[0]
        assert r["period_type"] == "duration"
        assert r["period_start"] == "2022-10-01"
        assert r["period_end"] == "2023-09-30"

    def test_instant_fact(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        assets = [r for r in result if r["concept"] == "Assets"]
        assert len(assets) == 1
        a = assets[0]
        assert a["period_type"] == "instant"
        assert a["period_start"] is None
        assert a["period_end"] == "2023-09-30"

    def test_value_stored_as_float(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        revenues = [r for r in result if r["concept"] == "Revenues"]
        assert revenues[0]["value"] == pytest.approx(383_285_000_000.0)
        assert isinstance(revenues[0]["value"], float)

    def test_cik_zero_padded_in_output(self):
        result = parse_company_facts("320193", _facts_fixture())
        for r in result:
            assert r["cik"] == "0000320193"

    def test_accession_normalized(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        for r in result:
            if r["accession_no"]:
                parts = r["accession_no"].split("-")
                assert len(parts) == 3

    def test_taxonomy_preserved(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        taxonomies = {r["taxonomy"] for r in result}
        assert "us-gaap" in taxonomies

    def test_fiscal_period_and_year(self):
        result = parse_company_facts("0000320193", _facts_fixture())
        revenues = [r for r in result if r["concept"] == "Revenues"]
        assert revenues[0]["fiscal_year"] == 2023
        assert revenues[0]["fiscal_period"] == "FY"

    def test_string_value(self):
        raw = _facts_fixture()
        raw["facts"]["dei"] = {
            "EntityCommonStockSharesOutstanding": {
                "label": "Shares",
                "units": {
                    "shares": [
                        {
                            "end": "2023-09-30",
                            "val": "15441000000",
                            "accn": "0000320193-23-000077",
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2023-11-03",
                        }
                    ]
                },
            }
        }
        result = parse_company_facts("0000320193", raw)
        str_facts = [r for r in result if r["concept"] == "EntityCommonStockSharesOutstanding"]
        assert len(str_facts) == 1
        # String val → value=None, value_text set
        assert str_facts[0]["value"] is None
        assert str_facts[0]["value_text"] == "15441000000"

    def test_missing_end_skipped(self):
        raw = _facts_fixture()
        raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append({
            # No "end" field
            "val": 999,
            "accn": "0000320193-23-000099",
            "fy": 2023,
            "fp": "FY",
            "form": "10-K",
            "filed": "2023-11-03",
        })
        result = parse_company_facts("0000320193", raw)
        revenues = [r for r in result if r["concept"] == "Revenues"]
        # Only the fact with "end" should be included
        assert len(revenues) == 1

    def test_empty_facts(self):
        raw = {"cik": 320193, "entityName": "Test Co", "facts": {}}
        result = parse_company_facts("0000320193", raw)
        assert result == []
