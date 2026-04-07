import pytest

from job_scout.orchestrator import _build_page_url


# ---------------------------------------------------------------------------
# _build_page_url
# ---------------------------------------------------------------------------

def test_appends_param_when_not_in_url() -> None:
    url = "https://example.com/jobs"
    result = _build_page_url(url, "start", 20)
    assert "start=20" in result


def test_replaces_existing_param_without_duplicating() -> None:
    url = "https://example.com/jobs?start=0"
    result = _build_page_url(url, "start", 40)
    assert result.count("start=") == 1
    assert "start=40" in result


def test_preserves_fragment_identifier() -> None:
    url = "https://example.com/jobs?pagesize=20#results"
    result = _build_page_url(url, "start", 20)
    assert "#results" in result


def test_handles_url_with_no_query_string() -> None:
    url = "https://example.com/jobs/"
    result = _build_page_url(url, "page", 0)
    assert "page=0" in result
    assert result.startswith("https://example.com/jobs/")


def test_preserves_other_query_params() -> None:
    url = "https://example.com/jobs?country=US&pagesize=20"
    result = _build_page_url(url, "start", 20)
    assert "country=US" in result
    assert "pagesize=20" in result
    assert "start=20" in result


def test_offset_zero_sets_param_to_zero() -> None:
    url = "https://example.com/jobs"
    result = _build_page_url(url, "start", 0)
    assert "start=0" in result
