"""
Groq-powered chat engine for the Workforce Data Explorer.

Uses GPT-OSS 120B via Groq's free API with tool calling to route natural
language queries to the right data connectors. Token-efficient by design:
  - Short, focused system prompt
  - Tool results summarized (stats + sample rows), not full DataFrames
  - Conversation history capped at last 8 turns
  - Full DataFrames stored in session state separately for chart rendering
"""

import json
import os
from typing import Any, Optional

import pandas as pd
from groq import Groq

MAX_HISTORY_TURNS = 8   # keep last N user+model turn pairs
MAX_ROWS_TO_LLM = 12    # rows sent to LLM (summary only — charts get full data)

MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You are a workforce data analyst with live access to US labor market databases.
Today's date is {today}. Your training data is older than the live data your tools return —
trust the tool results for anything recent, and don't re-fetch just because values postdate
your training. Omit end_date to get the latest available data.

Answer questions using your tools. Be concise. When you fetch data:
- Summarize key findings in 2-4 sentences
- Highlight notable trends or comparisons
- Note the data source and recency
- If the user asks to chart or visualize something, say so and it will be rendered automatically

Available data: BLS employment/wages/JOLTS, FRED macro series, Census ACS state/county data,
O*NET occupation skills/tasks, DOL enforcement, SEC workforce filings.

IMPORTANT — never say data is unavailable without trying these steps first:
1. Call get_fred_data with the topic or a likely FRED series ID
2. If that fails, call search_fred with relevant keywords to find the right series
3. Only after both attempts fail should you say the data isn't accessible

FRED covers nearly all BLS and Census labor statistics. When in doubt, search FRED first."""

# ── Tool schemas (OpenAI/Groq format) ────────────────────────────────────────

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": "Search the workforce data catalog for sources matching a topic or keyword. Returns matching source names, descriptions, and IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to search for (e.g. 'remote work', 'gig economy', 'occupation wages')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fred_data",
            "description": "Fetch a FRED time series by topic name or series ID. Topics: unemployment rate, job openings, quits rate, average hourly earnings, labor force participation rate, initial claims, nonfarm payrolls, GDP, CPI, employment cost index, productivity, and 60+ more.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_or_series_id": {"type": "string", "description": "Topic name (e.g. 'unemployment rate') or FRED series ID (e.g. 'UNRATE')"},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD (default 2015-01-01)"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD (default: latest available)"},
                },
                "required": ["topic_or_series_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_fred",
            "description": "Search FRED for time series matching a keyword query. Use when you don't know the exact series ID or topic name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms (e.g. 'small business employment', 'prime age workers')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bls_data",
            "description": "Fetch BLS data by popular series name. Available: ces_total_nonfarm, ces_avg_hourly_earnings, cps_unemployment_rate, cps_labor_force_participation, jolts_openings_total, jolts_quits_total, jolts_hires_total, jolts_layoffs_total, eci_total_compensation, productivity_nonfarm_business, unit_labor_costs_nonfarm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "series_names": {"type": "string", "description": "Comma-separated series names (e.g. 'jolts_openings_total,jolts_quits_total')"},
                    "start_year": {"type": "integer", "description": "Start year (default 2015)"},
                    "end_year": {"type": "integer", "description": "End year (default: current year)"},
                },
                "required": ["series_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_onet_occupations",
            "description": "Search O*NET for occupations matching a job title or description. Returns occupation codes and titles. Use the code with get_onet_details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Job title or description (e.g. 'software developer', 'registered nurse')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_onet_details",
            "description": "Get detailed O*NET data for a specific occupation code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "occupation_code": {"type": "string", "description": "O*NET-SOC code (e.g. '15-1252.00' for Software Developers)"},
                    "data_type": {"type": "string", "description": "One of: skills, tasks, abilities, knowledge, work_activities, technology"},
                },
                "required": ["occupation_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_census_data",
            "description": "Fetch Census ACS data for employment, income, commuting, and demographics. Variables: employed, unemployed, labor_force, not_in_labor_force, median_household_income, per_capita_income, work_from_home, drive_alone, public_transit, mean_travel_time, bachelors_or_higher, total_population, median_age, below_poverty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "variables": {"type": "string", "description": "Comma-separated variable names (e.g. 'employed,median_household_income')"},
                    "geography": {"type": "string", "description": "One of: national, state, county"},
                    "year": {"type": "integer", "description": "ACS survey year (default 2023)"},
                },
                "required": ["variables"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ui_claims_data",
            "description": "Fetch weekly unemployment insurance initial claims data (seasonally adjusted). One of the most timely labor market indicators, updated weekly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weeks": {"type": "integer", "description": "Number of weeks of history (default 104 = 2 years)"},
                },
                "required": [],
            },
        },
    },
]


# ── Tool functions ────────────────────────────────────────────────────────────

def search_catalog(query: str) -> str:
    from .catalog import search
    results = search(query)[:8]
    if not results:
        return json.dumps({"results": [], "message": "No catalog sources found for this query."})
    return json.dumps([{
        "id": r["id"],
        "name": r["name"],
        "provider": r["provider"],
        "description": r["description"][:200],
        "connector": r["connector"],
        "frequency": r["frequency"],
    } for r in results])


def get_fred_data(topic_or_series_id: str, start_date: str = "2015-01-01", end_date: str = "") -> str:
    from .sources.fred import get_by_topic, get_series, get_series_info, list_topics, search_series
    end = end_date or None
    topic_lower = topic_or_series_id.lower()

    # Special case: education-level unemployment — fetch all 4 levels and combine
    if "education" in topic_lower and ("unemployment" in topic_lower or "jobless" in topic_lower):
        education_series = {
            "Less than High School": "LNS14027659",
            "High School Graduates": "LNS14027660",
            "Some College / Associate": "LNS14027689",
            "Bachelor's Degree and Higher": "LNS14027662",
        }
        frames = []
        for label, sid in education_series.items():
            try:
                df = get_series(sid, start_date=start_date, end_date=end)
                val_col = [c for c in df.columns if c != "date"][0]
                df = df.rename(columns={val_col: label})
                frames.append(df.set_index("date"))
            except Exception:
                pass
        if frames:
            combined = pd.concat(frames, axis=1).reset_index()
            _store_df("fred_unemployment_by_education", combined, "Unemployment Rate by Education Level", "line")
            return json.dumps(_df_summary(combined, "Unemployment Rate by Education Level (%)"))
        return json.dumps({"error": "Could not fetch education unemployment series."})

    # 1. Try as explicit series ID (all caps, no spaces)
    if topic_or_series_id.upper() == topic_or_series_id.replace(" ", ""):
        try:
            df = get_series(topic_or_series_id.upper(), start_date=start_date, end_date=end)
            info = get_series_info(topic_or_series_id.upper())
            _store_df(f"fred_{topic_or_series_id.upper()}", df, info.get("title", topic_or_series_id), "line")
            return json.dumps({"series_id": topic_or_series_id.upper(), **_df_summary(df, info.get("title", "")), "units": info.get("units", ""), "frequency": info.get("frequency", "")})
        except Exception:
            pass

    # 2. Try as a known topic name
    try:
        df, series_id = get_by_topic(topic_or_series_id, start_date=start_date, end_date=end)
        info = get_series_info(series_id)
        _store_df(f"fred_{series_id}", df, info.get("title", topic_or_series_id), "line")
        return json.dumps({
            "series_id": series_id,
            **_df_summary(df, info.get("title", topic_or_series_id)),
            "units": info.get("units", ""),
            "frequency": info.get("frequency", ""),
        })
    except ValueError:
        pass
    except Exception as e:
        return json.dumps({"error": str(e)})

    # 3. Auto-search FRED and fetch the top result automatically
    try:
        hits = search_series(topic_or_series_id, limit=5)
        if hits.empty:
            return json.dumps({"error": f"No FRED series found for '{topic_or_series_id}'."})

        top_id = hits.iloc[0]["series_id"]
        try:
            df = get_series(top_id, start_date=start_date, end_date=end)
            info = get_series_info(top_id)
            _store_df(f"fred_{top_id}", df, info.get("title", top_id), "line")
            other = hits[["series_id", "title"]].iloc[1:].to_dict(orient="records")
            return json.dumps({
                "note": f"Auto-fetched top result for '{topic_or_series_id}'.",
                "series_id": top_id,
                **_df_summary(df, info.get("title", top_id)),
                "units": info.get("units", ""),
                "other_matches": other,
            })
        except Exception:
            results = hits[["series_id", "title", "frequency", "units"]].to_dict(orient="records")
            return json.dumps({"note": "Found series but could not fetch data.", "matches": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


def search_fred(query: str) -> str:
    from .sources.fred import search_series
    try:
        df = search_series(query, limit=8)
        if df.empty:
            return json.dumps({"results": []})
        return df[["series_id", "title", "frequency", "units", "observation_start", "observation_end"]].to_json(orient="records")
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_bls_data(series_names: str, start_year: int = 2015, end_year: int = 0) -> str:
    from .sources.bls import get_popular, list_popular
    from datetime import datetime
    end = end_year or datetime.now().year
    names = [n.strip() for n in series_names.split(",")]
    results = []
    errors = []
    for name in names:
        try:
            df = get_popular(name, start_year=start_year, end_year=end)
            _store_df(f"bls_{name}", df, name.replace("_", " ").title(), "line")
            results.append({name: _df_summary(df, name)})
        except Exception as e:
            errors.append({name: str(e)})
    available = list_popular()
    return json.dumps({"results": results, "errors": errors, "available_series": available})


def search_onet_occupations(query: str) -> str:
    from .sources.onet import search_occupations
    try:
        df = search_occupations(query, end=10)
        if df.empty:
            return json.dumps({"occupations": [], "message": "No occupations found."})
        _store_df("onet_search", df, f"O*NET search: {query}", None)
        return df.to_json(orient="records")
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_onet_details(occupation_code: str, data_type: str = "skills") -> str:
    from .sources import onet
    fn_map = {
        "skills": onet.get_skills,
        "tasks": onet.get_tasks,
        "abilities": onet.get_abilities,
        "knowledge": onet.get_knowledge,
        "work_activities": onet.get_work_activities,
        "technology": onet.get_technology,
    }
    if data_type not in fn_map:
        return json.dumps({"error": f"data_type must be one of {list(fn_map)}"})
    try:
        df = fn_map[data_type](occupation_code)
        if df.empty:
            return json.dumps({"message": f"No {data_type} data for {occupation_code}."})
        label = f"{occupation_code} — {data_type}"
        _store_df(f"onet_{occupation_code}_{data_type}", df, label, "bar" if "importance_value" in df.columns else None)
        return json.dumps(_df_summary(df, label))
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_census_data(variables: str, geography: str = "state", year: int = 2023) -> str:
    from .sources.census import get_acs, list_acs_variables
    var_list = [v.strip() for v in variables.split(",")]
    dataset = "acs/acs5" if geography == "county" else "acs/acs1"
    try:
        df = get_acs(var_list, year=year, geography=geography, dataset=dataset)
        if df.empty:
            return json.dumps({"message": "No data returned.", "available_variables": list(list_acs_variables().keys())})
        label = f"ACS {year} — {', '.join(var_list)} by {geography}"
        chart_type = "bar" if geography in ("state", "county") else None
        _store_df(f"census_{geography}_{year}", df, label, chart_type)
        return json.dumps(_df_summary(df, label))
    except Exception as e:
        return json.dumps({"error": str(e), "available_variables": list(list_acs_variables().keys())})


def get_ui_claims_data(weeks: int = 104) -> str:
    from .sources.dol import get_bls_ui_claims
    try:
        df = get_bls_ui_claims(weeks=weeks)
        if df.empty:
            return json.dumps({"error": "No data returned."})
        _store_df("ui_claims", df, "Weekly Initial UI Claims (Seasonally Adjusted, Thousands)", "line")
        return json.dumps(_df_summary(df, "Weekly Initial UI Claims"))
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOL_MAP = {
    "search_catalog": search_catalog,
    "get_fred_data": get_fred_data,
    "search_fred": search_fred,
    "get_bls_data": get_bls_data,
    "search_onet_occupations": search_onet_occupations,
    "get_onet_details": get_onet_details,
    "get_census_data": get_census_data,
    "get_ui_claims_data": get_ui_claims_data,
}


# ── DataFrame store ───────────────────────────────────────────────────────────
# Thread-local: one Python process serves many Streamlit sessions (and many MCP
# requests), so a module-global dict would let concurrent users see each
# other's data. Tool calls run synchronously on the caller's thread, so
# thread-local isolation is sufficient.

import threading

_df_local = threading.local()


def _store() -> dict[str, dict]:
    if not hasattr(_df_local, "store"):
        _df_local.store = {}
    return _df_local.store


def _df_summary(df: pd.DataFrame, label: str = "") -> dict:
    if df.empty:
        return {"status": "no_data", "label": label}
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    # For time series, the most recent rows are what questions are about
    sample = df.tail(MAX_ROWS_TO_LLM) if "date" in df.columns else df.head(MAX_ROWS_TO_LLM)
    summary: dict[str, Any] = {
        "label": label,
        "rows": len(df),
        "columns": list(df.columns),
        # Round-trip through pandas JSON so Timestamps/numpy types are serializable
        "sample": json.loads(sample.to_json(orient="records", date_format="iso")),
    }
    if numeric_cols and len(df) > 1:
        stats = df[numeric_cols].agg(["min", "max", "mean"]).round(2)
        summary["stats"] = stats.to_dict()
    if "date" in df.columns and numeric_cols:
        val_col = numeric_cols[0]
        first_val = df[val_col].dropna().iloc[0] if not df[val_col].dropna().empty else None
        last_val = df[val_col].dropna().iloc[-1] if not df[val_col].dropna().empty else None
        if first_val is not None and last_val is not None:
            summary["first_value"] = round(float(first_val), 3)
            summary["last_value"] = round(float(last_val), 3)
            summary["change"] = round(float(last_val - first_val), 3)
            summary["date_range"] = f"{df['date'].min().strftime('%Y-%m')} to {df['date'].max().strftime('%Y-%m')}"
    return summary


def _store_df(key: str, df: pd.DataFrame, label: str, chart_type: Optional[str]):
    _store()[key] = {"df": df, "label": label, "chart_type": chart_type}


def get_stored_dfs() -> dict:
    return _store()


def clear_stored_dfs():
    _store().clear()


# ── Chat ──────────────────────────────────────────────────────────────────────

def _create_with_retry(client, messages, **kwargs):
    """
    Call Groq chat completions, retrying transient failures:
    - "tool_use_failed" 400s (the model emitted a malformed tool call)
    - 429 rate limits (free tier is 8k tokens/min — brief backoff usually clears it)
    """
    import time

    last_err = None
    for attempt in range(4):
        try:
            return client.chat.completions.create(model=MODEL, messages=messages, **kwargs)
        except Exception as e:
            last_err = e
            err_text = str(e)
            if "tool_use_failed" in err_text:
                continue
            if "rate_limit" in err_text or "429" in err_text:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_err


def chat(history: list[dict], user_message: str, api_key: Optional[str] = None) -> tuple[str, list[dict], dict]:
    """
    Send a message and get a response. Handles multi-step tool calls automatically.

    Args:
        history: List of {"role": "user"|"assistant", "content": str} dicts
        user_message: The new user message
        api_key: Groq API key; falls back to the GROQ_API_KEY env var

    Returns:
        (assistant_reply_text, updated_history, dataframes) where dataframes
        maps store keys to {"df", "label", "chart_type"} for chart rendering
    """
    api_key = api_key or os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in .env")

    client = Groq(api_key=api_key)
    clear_stored_dfs()

    # Build message list: system + capped history + new user message
    from datetime import date as _date
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=_date.today().isoformat())}]
    messages.extend(history[-(MAX_HISTORY_TURNS * 2):])
    messages.append({"role": "user", "content": user_message})

    # Agentic loop — capped so a tool-happy model can't spin forever.
    # tool_choice stays "auto": forcing a call breaks questions that don't
    # need data (Groq 400s when a forced model answers in text).
    for _round in range(8):
        response = _create_with_retry(client, messages, tools=TOOL_DEFS, tool_choice="auto")

        msg = response.choices[0].message

        if not msg.tool_calls:
            break

        # Append assistant turn (with tool calls) to messages
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        # Execute each tool call and append results
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            tool_fn = TOOL_MAP.get(fn_name)
            if tool_fn:
                try:
                    result = tool_fn(**fn_args)
                except Exception as e:
                    result = json.dumps({"error": str(e)})
            else:
                result = json.dumps({"error": f"Unknown tool: {fn_name}"})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    else:
        # Round cap reached with the model still requesting tools —
        # ask for a plain-text answer from what it has so far. Tools stay in the
        # request (Groq errors if the model emits a call with tool_choice=none),
        # but any further calls are ignored.
        messages.append({
            "role": "user",
            "content": "Stop calling tools. Answer now in plain text using the tool results above.",
        })
        response = _create_with_retry(client, messages, tools=TOOL_DEFS, tool_choice="auto")
        msg = response.choices[0].message

    reply = msg.content or ""

    # Build updated history: only user/assistant text turns (no tool messages)
    updated_history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[1:]  # skip system prompt
        if m["role"] in ("user", "assistant") and m.get("content")
    ]

    return reply.strip(), updated_history, dict(get_stored_dfs())
