"""
SEC EDGAR connector.
Accesses human capital disclosures from 10-K filings, proxy statements,
and 8-K layoff announcements.

No API key required. SEC EDGAR is free and public.
Rate limit: 10 requests/second (enforced by SEC).
"""

import time
from typing import Optional
import pandas as pd
import requests

EDGAR_BASE = "https://data.sec.gov"
FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"

HEADERS = {
    "User-Agent": "WorkforceDataExplorer research@workforce-data.io",
    "Accept-Encoding": "gzip, deflate",
}

_last_request = 0.0
MIN_INTERVAL = 0.15  # 100ms between requests → well under 10/sec limit


def _rate_limit():
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.time()


def _parse_hits(hits: list, limit: int) -> pd.DataFrame:
    """Convert EDGAR full-text-search hits into a tidy DataFrame,
    newest filings first."""
    rows = []
    for hit in hits:
        src = hit.get("_source", {})
        names = src.get("display_names") or [""]
        ciks = src.get("ciks") or [""]
        adsh = src.get("adsh", "")
        doc = hit.get("_id", "").split(":", 1)[-1]
        filing_url = ""
        if adsh and ciks[0] and doc:
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(ciks[0])}/{adsh.replace('-', '')}/{doc}"
            )
        rows.append({
            "company": names[0],
            "form_type": src.get("form", ""),
            "file_date": src.get("file_date", ""),
            "period": src.get("period_ending", ""),
            "location": (src.get("biz_locations") or [""])[0],
            "description": src.get("file_description") or "",
            "filing_url": filing_url,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("file_date", ascending=False).head(limit).reset_index(drop=True)
    return df


def search_filings(
    query: str,
    form_type: str = "10-K",
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None,
    limit: int = 20,
    exact_phrase: bool = False,
) -> pd.DataFrame:
    """
    Full-text search of SEC EDGAR filings.

    Args:
        query: search terms (e.g. 'human capital employees turnover')
        form_type: '10-K', '10-Q', '8-K', 'DEF 14A' (proxy), etc.
        date_range_start: 'YYYY-MM-DD'
        date_range_end: 'YYYY-MM-DD'
        limit: max results
        exact_phrase: quote the query so EDGAR matches it as a phrase

    Returns:
        DataFrame with filing metadata.
    """
    _rate_limit()
    params = {
        "q": f'"{query}"' if exact_phrase else query,
        "forms": form_type,
    }
    if date_range_start or date_range_end:
        from datetime import date
        # EDGAR ignores the range unless BOTH ends are present
        params["dateRange"] = "custom"
        params["startdt"] = date_range_start or "2001-01-01"
        params["enddt"] = date_range_end or str(date.today())

    resp = requests.get(FULL_TEXT_SEARCH, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])
    return _parse_hits(hits, limit)


def search_company_filings(
    company_name: str,
    form_type: str = "10-K",
    limit: int = 10,
) -> pd.DataFrame:
    """
    Search for filings BY a specific company (EDGAR entityName filter),
    rather than filings that merely mention the name.
    """
    _rate_limit()
    params = {
        "q": f'"{company_name}"',
        "entityName": company_name,
        "forms": form_type,
    }
    try:
        resp = requests.get(FULL_TEXT_SEARCH, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return _parse_hits(hits, limit)
    except Exception:
        return pd.DataFrame()


def search_layoff_8k(
    date_range_start: Optional[str] = None,
    date_range_end: Optional[str] = None,
    limit: int = 50,
) -> pd.DataFrame:
    """
    Search for 8-K filings disclosing layoffs and workforce reductions.
    """
    return search_filings(
        query="workforce reduction",
        form_type="8-K",
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        limit=limit,
        exact_phrase=True,
    )
