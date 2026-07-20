"""
Workforce Data MCP server.

Exposes the workforce-data connectors (FRED, BLS, Census, O*NET, DOL, SEC)
as Model Context Protocol tools, so any MCP client — Claude Desktop, claude.ai
custom connectors, ChatGPT developer mode — can query live US labor market data.

Run locally (stdio, for Claude Desktop):
    python mcp_server.py

Run as a remote server (streamable HTTP, for hosted deployment):
    python mcp_server.py --http            # binds 0.0.0.0:$PORT (default 8080)

Claude Desktop config (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "workforce-data": {
          "command": "/path/to/workforce-data/.venv/bin/python",
          "args": ["/path/to/workforce-data/mcp_server.py"]
        }
      }
    }
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

# The chat module's tool functions already return compact, LLM-ready JSON
# (stats + recent sample rows), so the MCP tools reuse them directly.
from workforce_data import chat as impl

INSTRUCTIONS = """Live access to US labor market data: FRED macro time series,
BLS employment/wages/JOLTS, Census ACS demographics, O*NET occupation profiles,
weekly UI claims, and SEC EDGAR workforce filings.

Tips:
- For any macro/labor statistic, try get_fred_data first — FRED covers nearly
  all BLS and Census headline series. If it misses, use search_fred.
- Time series results include summary stats plus the most recent observations.
  Pass full_data=true on get_fred_data when you need every observation
  (e.g. to chart or analyze the series yourself).
"""

mcp = FastMCP("workforce-data", instructions=INSTRUCTIONS)


# ── Catalog ───────────────────────────────────────────────────────────────────

@mcp.tool()
def search_catalog(query: str) -> str:
    """Search a curated catalog of 200+ workforce data sources by topic or keyword.

    Returns matching source names, providers, descriptions, and update frequency.
    Useful for discovering what data exists on a topic (e.g. 'remote work',
    'gig economy', 'union membership') before fetching it.
    """
    return impl.search_catalog(query)


# ── FRED ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_fred_data(
    topic_or_series_id: str,
    start_date: str = "2015-01-01",
    end_date: str = "",
    full_data: bool = False,
) -> str:
    """Fetch a FRED time series by topic name or series ID. Call this first for
    any US macro or labor statistic — unemployment rate, job openings, quits
    rate, wages, labor force participation, initial claims, payrolls, GDP, CPI,
    and 800,000+ more series.

    Args:
        topic_or_series_id: Topic name (e.g. 'unemployment rate') or FRED series
            ID (e.g. 'UNRATE'). Unknown topics are auto-searched and the top
            match is fetched.
        start_date: YYYY-MM-DD (default 2015-01-01).
        end_date: YYYY-MM-DD (default: latest available).
        full_data: If true, append every observation as CSV instead of only
            summary stats and recent rows. Use when charting or analyzing the
            full series.
    """
    result = impl.get_fred_data(topic_or_series_id, start_date=start_date, end_date=end_date)
    if full_data:
        result = _append_full_data(result)
    return result


@mcp.tool()
def search_fred(query: str) -> str:
    """Search FRED for time series matching a keyword query. Use when
    get_fred_data doesn't find the right series — returns series IDs, titles,
    frequency, and date coverage to pass back into get_fred_data.
    """
    return impl.search_fred(query)


# ── BLS ───────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_bls_data(series_names: str, start_year: int = 2015, end_year: int = 0) -> str:
    """Fetch official BLS series by name, straight from the Bureau of Labor
    Statistics API. Available series: ces_total_nonfarm, ces_private,
    ces_manufacturing, ces_avg_hourly_earnings, ces_avg_weekly_hours,
    cps_unemployment_rate, cps_labor_force_participation, cps_employed,
    cps_unemployed, jolts_openings_total, jolts_hires_total, jolts_quits_total,
    jolts_layoffs_total, jolts_separations_total, eci_total_compensation,
    eci_wages_salaries, eci_benefits, productivity_nonfarm_business,
    unit_labor_costs_nonfarm, oews_all_occupations_mean_wage.

    Args:
        series_names: Comma-separated series names
            (e.g. 'jolts_openings_total,jolts_quits_total').
        start_year: Default 2015.
        end_year: Default current year.
    """
    return impl.get_bls_data(series_names, start_year=start_year, end_year=end_year)


@mcp.tool()
def get_occupation_wages(soc_code: str) -> str:
    """Get national mean annual wage, mean hourly wage, and employment for a
    specific occupation from BLS OEWS (latest survey year).

    Args:
        soc_code: SOC occupation code without hyphen (e.g. '151252' for
            Software Developers, '291141' for Registered Nurses). Find codes
            with search_onet_occupations (drop the hyphen and '.00' suffix).
    """
    from workforce_data.sources import bls

    out = {}
    for dt, label in [("04", "mean_annual_wage"), ("03", "mean_hourly_wage"), ("01", "employment")]:
        try:
            df = bls.get_oews_occupation(soc_code, data_type=dt)
            if not df.empty:
                row = df.iloc[-1]
                out[label] = {"value": row["value"], "year": int(row["year"])}
        except Exception as e:
            out[label] = {"error": str(e)}
    if not out:
        return json.dumps({"error": f"No OEWS data found for SOC {soc_code}."})
    return json.dumps({"soc_code": soc_code, **out})


# ── Census ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_census_data(variables: str, geography: str = "state", year: int = 2023) -> str:
    """Fetch Census ACS data for employment, income, commuting, education, and
    demographics — by state, county, or nationally. Variables: employed,
    unemployed, labor_force, not_in_labor_force, median_household_income,
    per_capita_income, work_from_home, drive_alone, public_transit,
    mean_travel_time, bachelors_or_higher, total_population, median_age,
    below_poverty.

    Args:
        variables: Comma-separated variable names
            (e.g. 'employed,median_household_income').
        geography: One of: national, state, county.
        year: ACS survey year (default 2023).
    """
    return impl.get_census_data(variables, geography=geography, year=year)


# ── O*NET ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_onet_occupations(query: str) -> str:
    """Search O*NET's database of 900+ occupations by job title or description.
    Returns occupation codes and titles — pass a code to get_onet_details or
    get_occupation_wages.
    """
    return impl.search_onet_occupations(query)


@mcp.tool()
def get_onet_details(occupation_code: str, data_type: str = "skills") -> str:
    """Get detailed O*NET data for an occupation: its skills, daily tasks,
    abilities, knowledge areas, work activities, or technology used.

    Args:
        occupation_code: O*NET-SOC code (e.g. '15-1252.00' for Software
            Developers).
        data_type: One of: skills, tasks, abilities, knowledge,
            work_activities, technology.
    """
    return impl.get_onet_details(occupation_code, data_type=data_type)


# ── DOL ───────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_ui_claims(weeks: int = 104) -> str:
    """Fetch weekly US unemployment insurance initial claims (seasonally
    adjusted) — one of the most timely labor market indicators, updated weekly.

    Args:
        weeks: Number of weeks of history (default 104 = 2 years).
    """
    return impl.get_ui_claims_data(weeks=weeks)


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────

@mcp.tool()
def search_layoff_filings(start_date: str = "", end_date: str = "", limit: int = 25) -> str:
    """Search SEC EDGAR for 8-K filings disclosing layoffs and workforce
    reductions at public companies. Returns company names, filing dates, and
    links to the filings.

    Args:
        start_date: Filed after this date, YYYY-MM-DD (default: 90 days ago).
        end_date: Filed before this date, YYYY-MM-DD (default: today).
        limit: Max filings to return (default 25).
    """
    from datetime import date, timedelta
    from workforce_data.sources import sec

    start = start_date or str(date.today() - timedelta(days=90))
    end = end_date or None
    try:
        df = sec.search_layoff_8k(date_range_start=start, date_range_end=end, limit=limit)
        if df.empty:
            return json.dumps({"results": [], "message": "No layoff filings found in this window."})
        return df.head(limit).to_json(orient="records")
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def search_company_filings(company_name: str, form_type: str = "10-K", limit: int = 10) -> str:
    """Search SEC EDGAR for a public company's filings — annual reports (10-K),
    quarterlies (10-Q), current reports (8-K), or proxy statements (DEF 14A).
    10-Ks include human capital disclosures: headcount, workforce strategy,
    diversity, and retention.

    Args:
        company_name: Company name (e.g. 'Apple', 'Microsoft').
        form_type: One of: 10-K, 10-Q, 8-K, DEF 14A.
        limit: Max filings to return (default 10).
    """
    from workforce_data.sources import sec

    try:
        df = sec.search_company_filings(company_name, form_type=form_type, limit=limit)
        if df.empty:
            return json.dumps({"results": [], "message": f"No {form_type} filings found for '{company_name}'."})
        return df.head(limit).to_json(orient="records")
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Helpers ───────────────────────────────────────────────────────────────────

MAX_FULL_ROWS = 2000


def _append_full_data(result_json: str) -> str:
    """Attach the full stored DataFrame (as CSV) to a tool result."""
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        return result_json
    if "error" in result:
        return result_json

    dfs = impl.get_stored_dfs()
    if not dfs:
        return result_json
    # The chat layer stores the frame it just fetched; grab the most recent.
    info = list(dfs.values())[-1]
    df = info.get("df")
    if df is None or df.empty:
        return result_json

    truncated = len(df) > MAX_FULL_ROWS
    result["full_data_csv"] = df.tail(MAX_FULL_ROWS).to_csv(index=False)
    if truncated:
        result["full_data_note"] = f"Truncated to the most recent {MAX_FULL_ROWS} of {len(df)} rows."
    return json.dumps(result)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Workforce Data MCP server")
    parser.add_argument("--http", action="store_true",
                        help="Serve over streamable HTTP instead of stdio (for remote hosting)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
