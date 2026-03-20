"""
Tests for the `fetch` CLI command in sec_edgar/cli.py.

Uses Click's CliRunner and unittest.mock to avoid real network calls or
disk I/O. The pipeline and db_mod functions are patched at the point of
import inside cli.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sec_edgar.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_ARGS = ["--user-agent", "Test User test@example.com", "fetch"]


def _run(*args):
    """Invoke CLI with BASE_ARGS prepended."""
    runner = CliRunner()
    return runner.invoke(cli, BASE_ARGS + list(args), catch_exceptions=False)


# ---------------------------------------------------------------------------
# fetch — normal ticker arguments (existing behaviour)
# ---------------------------------------------------------------------------


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_single_ticker(mock_conn, mock_run):
    result = _run("AAPL")

    assert result.exit_code == 0
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["tickers"] == ["AAPL"]


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_multiple_tickers(mock_conn, mock_run):
    result = _run("AAPL", "MSFT", "GOOGL")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["tickers"] == ["AAPL", "MSFT", "GOOGL"]


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_passes_form_types(mock_conn, mock_run):
    result = _run("AAPL", "--forms", "10-K")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["form_types"] == ["10-K"]


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_dry_run_flag(mock_conn, mock_run):
    result = _run("AAPL", "--dry-run")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["dry_run"] is True


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_verbose_flag(mock_conn, mock_run):
    result = _run("AAPL", "--verbose")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["verbose"] is True


# ---------------------------------------------------------------------------
# fetch --all
# ---------------------------------------------------------------------------


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.list_companies")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_all_calls_pipeline_with_db_tickers(mock_conn, mock_list, mock_run):
    mock_list.return_value = [
        {"ticker": "AAPL"},
        {"ticker": "MSFT"},
        {"ticker": "GOOGL"},
    ]

    result = _run("--all")

    assert result.exit_code == 0
    mock_list.assert_called_once()
    call_kwargs = mock_run.call_args.kwargs
    assert sorted(call_kwargs["tickers"]) == ["AAPL", "GOOGL", "MSFT"]


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.list_companies")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_all_prints_summary(mock_conn, mock_list, mock_run):
    mock_list.return_value = [{"ticker": "AAPL"}, {"ticker": "MSFT"}]

    result = _run("--all")

    assert "2" in result.output
    assert "AAPL" in result.output
    assert "MSFT" in result.output


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.list_companies")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_all_empty_db_exits_with_error(mock_conn, mock_list, mock_run):
    mock_list.return_value = []

    runner = CliRunner()
    result = runner.invoke(cli, BASE_ARGS + ["--all"], catch_exceptions=False)

    assert result.exit_code == 1
    mock_run.assert_not_called()


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.list_companies")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_all_with_dry_run(mock_conn, mock_list, mock_run):
    mock_list.return_value = [{"ticker": "AAPL"}]

    result = _run("--all", "--dry-run")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["dry_run"] is True
    assert call_kwargs["tickers"] == ["AAPL"]


@patch("sec_edgar.cli.pipeline.run")
@patch("sec_edgar.cli.db_mod.list_companies")
@patch("sec_edgar.cli.db_mod.get_connection")
def test_fetch_all_with_verbose(mock_conn, mock_list, mock_run):
    mock_list.return_value = [{"ticker": "TSLA"}]

    result = _run("--all", "--verbose")

    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["verbose"] is True


# ---------------------------------------------------------------------------
# fetch — no tickers and no --all → error
# ---------------------------------------------------------------------------


def test_fetch_no_args_exits_with_error():
    runner = CliRunner()
    result = runner.invoke(cli, BASE_ARGS, catch_exceptions=False)

    assert result.exit_code == 1


def test_fetch_no_args_prints_error_message():
    runner = CliRunner()
    result = runner.invoke(cli, BASE_ARGS, catch_exceptions=False)

    # Error should mention TICKER or --all
    assert "TICKER" in result.output or "--all" in result.output
