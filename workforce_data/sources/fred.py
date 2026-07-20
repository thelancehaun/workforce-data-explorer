"""
FRED (Federal Reserve Economic Data) connector.
Covers 816,000+ time series including virtually all BLS and Census labor data.

API key: https://fred.stlouisfed.org/docs/api/api_key.html (free, instant)
"""

import os
from typing import Optional
import pandas as pd
import requests

BASE_URL = "https://api.stlouisfed.org/fred"

# Curated map of common topics → FRED series IDs
# These are the most-used labor market series; users can also search FRED directly.
SERIES_MAP = {
    # Unemployment
    "unemployment rate": "UNRATE",
    "unemployment rate men": "LNS14000001",
    "unemployment rate women": "LNS14000002",
    "unemployment rate black": "LNS14000006",
    "unemployment rate hispanic": "LNS14000009",
    "unemployment rate white": "LNS14000003",
    "unemployment rate youth": "LNS14000012",
    "unemployment rate less than high school": "LNS14027659",
    "unemployment rate high school no college": "LNS14027660",
    "unemployment rate some college": "LNS14027689",
    "unemployment rate bachelors degree": "LNS14027662",
    "unemployment rate by education": "LNS14027662",
    "long-term unemployment": "UEMPLT5",
    "u6 underemployment": "U6RATE",
    # Labor force participation
    "labor force participation rate": "CIVPART",
    "labor force participation men": "LNS11300001",
    "labor force participation women": "LNS11300002",
    "labor force participation prime age": "LNS11300060",
    # Employment
    "total nonfarm payrolls": "PAYEMS",
    "private sector payrolls": "USPRIV",
    "government employment": "USGOVT",
    "manufacturing employment": "MANEMP",
    "construction employment": "USCONS",
    "retail employment": "USTRADE",
    "healthcare employment": "HLTHEM",
    "professional services employment": "USPBS",
    "leisure hospitality employment": "USLAH",
    "information employment": "USINFO",
    "financial employment": "USFIRE",
    "transportation employment": "CES4300000001",
    # JOLTS
    "job openings": "JTSJOL",
    "job openings rate": "JTSJOR",
    "hires": "JTSHIL",
    "hires rate": "JTSHLR",
    "quits": "JTSQUL",
    "quits rate": "JTSQUR",
    "layoffs and discharges": "JTSLDL",
    "layoffs rate": "JTSLDR",
    "total separations": "JTSTSL",
    # Wages and compensation
    "average hourly earnings all": "CES0500000003",
    "average hourly earnings private": "AHETPI",
    "average weekly earnings": "CES0500000011",
    "average weekly hours": "AWHAETP",
    "employment cost index": "ECIALLCIV",
    "real compensation per hour": "COMPRNFB",
    "median usual weekly earnings": "LES1252881600Q",
    # Productivity
    "nonfarm business productivity": "OPHNFB",
    "unit labor costs": "ULCNFB",
    "multifactor productivity": "MFPNBS",
    # UI claims
    "initial claims": "ICSA",
    "continued claims": "CCSA",
    "insured unemployment rate": "IURSA",
    # Prices
    "CPI all items": "CPIAUCSL",
    "CPI less food energy": "CPILFESL",
    "PCE inflation": "PCEPI",
    # GDP and output
    "real GDP": "GDPC1",
    "GDP": "GDP",
    "real disposable income": "DSPIC96",
    # Other key series
    "federal funds rate": "FEDFUNDS",
    "prime age employment population ratio": "EMRATIO",
    "not in labor force": "LNS15000000",
    "part time economic reasons": "LNS12032194",
    "discouraged workers": "LNU05026645",
    "atlanta fed wage growth tracker": "WAGEGROWTHNFCPSA",
    "minimum wage federal": "FEDMINNFRWAGE",
}


def _api_key() -> str:
    key = os.getenv("FRED_API_KEY", "")
    if not key:
        raise ValueError(
            "FRED_API_KEY not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html "
            "and add it to your .env file."
        )
    return key


def search_series(query: str, limit: int = 20) -> pd.DataFrame:
    """Search FRED for series matching a query string."""
    params = {
        "search_text": query,
        "api_key": _api_key(),
        "file_type": "json",
        "limit": limit,
        "order_by": "popularity",
        "sort_order": "desc",
    }
    resp = requests.get(f"{BASE_URL}/series/search", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    series = data.get("seriess", [])
    if not series:
        return pd.DataFrame()
    return pd.DataFrame([{
        "series_id": s["id"],
        "title": s["title"],
        "frequency": s.get("frequency_short", ""),
        "units": s.get("units", ""),
        "last_updated": s.get("last_updated", ""),
        "popularity": s.get("popularity", 0),
        "observation_start": s.get("observation_start", ""),
        "observation_end": s.get("observation_end", ""),
    } for s in series])


def get_series(
    series_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    frequency: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch a FRED time series by ID.

    Args:
        series_id: FRED series ID (e.g. 'UNRATE', 'PAYEMS')
        start_date: 'YYYY-MM-DD' format
        end_date: 'YYYY-MM-DD' format
        frequency: aggregation frequency override ('d','w','m','q','sa','a')

    Returns:
        DataFrame with columns: date, value, series_id
    """
    params = {
        "series_id": series_id,
        "api_key": _api_key(),
        "file_type": "json",
    }
    if start_date:
        params["observation_start"] = start_date
    if end_date:
        params["observation_end"] = end_date
    if frequency:
        params["frequency"] = frequency
        params["aggregation_method"] = "avg"

    resp = requests.get(f"{BASE_URL}/series/observations", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observations", [])
    if not obs:
        return pd.DataFrame(columns=["date", "value", "series_id"])

    df = pd.DataFrame(obs)[["date", "value"]]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df["series_id"] = series_id
    df = df.dropna(subset=["value"])
    return df.reset_index(drop=True)


def get_series_info(series_id: str) -> dict:
    """Return metadata for a FRED series."""
    params = {
        "series_id": series_id,
        "api_key": _api_key(),
        "file_type": "json",
    }
    resp = requests.get(f"{BASE_URL}/series", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    series = data.get("seriess", [{}])[0]
    return {
        "series_id": series.get("id", ""),
        "title": series.get("title", ""),
        "frequency": series.get("frequency", ""),
        "units": series.get("units", ""),
        "seasonal_adjustment": series.get("seasonal_adjustment", ""),
        "observation_start": series.get("observation_start", ""),
        "observation_end": series.get("observation_end", ""),
        "last_updated": series.get("last_updated", ""),
        "notes": series.get("notes", ""),
    }


def get_by_topic(
    topic: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch data for a named topic using the curated SERIES_MAP.
    Returns (DataFrame, series_id).
    """
    topic_lower = topic.lower().strip()
    lookup = {k.lower(): v for k, v in SERIES_MAP.items()}
    series_id = lookup.get(topic_lower)

    if not series_id:
        # Try partial match
        for key, sid in lookup.items():
            if topic_lower in key or key in topic_lower:
                series_id = sid
                break

    if not series_id:
        raise ValueError(
            f"Topic '{topic}' not in curated map. "
            f"Use search_series('{topic}') to find a FRED series ID directly."
        )

    df = get_series(series_id, start_date=start_date, end_date=end_date)
    return df, series_id


def list_topics() -> list[str]:
    """Return all curated topic names."""
    return sorted(SERIES_MAP.keys())
