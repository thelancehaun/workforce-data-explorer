"""
Workforce Data Explorer — Streamlit app.
Run with: streamlit run app.py
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional

import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))

import ui_theme
from workforce_data import catalog
from workforce_data.sources import bls as bls_connector
from workforce_data.sources import census as census_connector
from workforce_data.sources import dol as dol_connector
from workforce_data.sources import fred as fred_connector
from workforce_data.sources import indeed as indeed_connector
from workforce_data.sources import onet as onet_connector
from workforce_data.sources import sec as sec_connector

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Workforce Data Explorer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Sidebar (navigation renders itself via st.navigation at the bottom) ───────

MCP_URL = "https://workforce-data-mcp.onrender.com/mcp"
GITHUB_URL = "https://github.com/thelancehaun/workforce-data-explorer"

with st.sidebar:
    _n_live = sum(1 for s in catalog.SOURCES if s.get("connector") != "external")
    st.caption(f"{len(catalog.SOURCES)} curated data sources — {_n_live} with live API access")

    with st.expander("API key status"):
        _keys = [
            ("FRED", "FRED_API_KEY"), ("BLS", "BLS_API_KEY"), ("Census", "CENSUS_API_KEY"),
            ("O*NET", "ONET_API_KEY"), ("DOL", "DOL_API_KEY"), ("Groq (chat)", "GROQ_API_KEY"),
        ]
        st.markdown("\n".join(
            f"- {':green[●]' if os.getenv(v, '') else ':gray[○]'} {n}" for n, v in _keys
        ))
        st.caption("All free — see the About page for signup links.")


LIVE_CONNECTORS = ("fred", "bls", "census", "onet", "dol", "sec", "indeed")


# ── Cached data access ────────────────────────────────────────────────────────
# One process serves every visitor, so st.cache_data turns repeat queries into
# instant, API-quota-free responses. TTLs track how often the source updates.

HOUR, DAY = 3600, 86400


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_fred_topic(topic: str, start_date: str, end_date: str):
    return fred_connector.get_by_topic(topic, start_date=start_date, end_date=end_date)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_fred_series(series_id: str, start_date: str):
    return fred_connector.get_series(series_id, start_date=start_date)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_fred_info(series_id: str) -> dict:
    return fred_connector.get_series_info(series_id)


@st.cache_data(ttl=DAY, show_spinner=False)
def search_fred_series(query: str, limit: int = 25):
    return fred_connector.search_series(query, limit=limit)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_bls_popular(name: str, start_year: int, end_year: int):
    return bls_connector.get_popular(name, start_year=start_year, end_year=end_year)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_bls_series(series_ids: tuple, start_year: int, end_year: int):
    return bls_connector.get_series(list(series_ids), start_year=start_year, end_year=end_year)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_oews(soc_code: str, data_type: str, start_year: int):
    return bls_connector.get_oews_occupation(soc_code, data_type=data_type, start_year=start_year)


@st.cache_data(ttl=DAY, show_spinner=False)
def search_onet(query: str):
    return onet_connector.search_occupations(query, end=30)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_onet_detail(data_type: str, occ_code: str):
    fn_map = {
        "skills": onet_connector.get_skills,
        "tasks": onet_connector.get_tasks,
        "abilities": onet_connector.get_abilities,
        "knowledge": onet_connector.get_knowledge,
        "work_activities": onet_connector.get_work_activities,
        "technology": onet_connector.get_technology,
        "related": onet_connector.get_related_occupations,
    }
    return fn_map[data_type](occ_code)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_onet_list(kind: str):
    if kind == "bright":
        return onet_connector.get_bright_outlook_occupations()
    return onet_connector.get_green_occupations()


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_ui_claims(weeks: int):
    return dol_connector.get_bls_ui_claims(weeks=weeks)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_osha(state, start_date: str, end_date: str):
    return dol_connector.get_osha_inspections(state=state, start_date=start_date, end_date=end_date)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_whd(state):
    return dol_connector.get_whd_enforcement(state=state)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_sec_filings(query: str, form_type: str, start_date: str, limit: int):
    return sec_connector.search_filings(query, form_type=form_type, date_range_start=start_date, limit=limit)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_layoff_8k(start_date: str, end_date: str):
    return sec_connector.search_layoff_8k(date_range_start=start_date, date_range_end=end_date)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_company_filings(company: str, form_type: str):
    return sec_connector.search_company_filings(company, form_type=form_type)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_acs(variables: tuple, year: int, geography: str, state_fips=None):
    dataset = "acs/acs5" if geography == "county" else "acs/acs1"
    return census_connector.get_acs(list(variables), year=year, geography=geography,
                                    state_fips=state_fips, dataset=dataset)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_qwi(indicators: tuple, state_fips: str, year_start: int, year_end: int):
    return census_connector.get_qwi(list(indicators), state_fips=state_fips,
                                    year_start=year_start, year_end=year_end)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_cbp(year: int, geography: str):
    return census_connector.get_cbp(year=year, geography=geography)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_postings_national(start_date: str, new_postings: bool = False):
    return indeed_connector.get_national_postings(start_date=start_date, new_postings=new_postings)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_postings_states(start_date: str):
    return indeed_connector.get_state_postings(start_date=start_date)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_postings_sectors(start_date: str):
    return indeed_connector.get_sector_postings(start_date=start_date)


@st.cache_data(ttl=HOUR, show_spinner=False)
def fetch_postings_metro(metro: str, start_date: str):
    return indeed_connector.get_metro_postings(metro=metro, start_date=start_date)


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_indeed_sectors() -> list:
    return indeed_connector.list_sectors()


@st.cache_data(ttl=DAY, show_spinner=False)
def fetch_ai_share(start_date: str):
    return indeed_connector.get_ai_postings_share(start_date=start_date)


US_STATES = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05", "California": "06",
    "Colorado": "08", "Connecticut": "09", "Delaware": "10", "District of Columbia": "11",
    "Florida": "12", "Georgia": "13", "Hawaii": "15", "Idaho": "16", "Illinois": "17",
    "Indiana": "18", "Iowa": "19", "Kansas": "20", "Kentucky": "21", "Louisiana": "22",
    "Maine": "23", "Maryland": "24", "Massachusetts": "25", "Michigan": "26", "Minnesota": "27",
    "Mississippi": "28", "Missouri": "29", "Montana": "30", "Nebraska": "31", "Nevada": "32",
    "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35", "New York": "36",
    "North Carolina": "37", "North Dakota": "38", "Ohio": "39", "Oklahoma": "40", "Oregon": "41",
    "Pennsylvania": "42", "Rhode Island": "44", "South Carolina": "45", "South Dakota": "46",
    "Tennessee": "47", "Texas": "48", "Utah": "49", "Vermont": "50", "Virginia": "51",
    "Washington": "53", "West Virginia": "54", "Wisconsin": "55", "Wyoming": "56",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Overview
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_QUESTIONS = [
    "How have quits and job openings moved since 2022?",
    "What's happening with layoffs at public companies this month?",
    "Compare software developer and registered nurse wages",
]


def _overview_series(series_id: str) -> pd.DataFrame:
    from datetime import timedelta
    start = (date.today() - timedelta(days=730)).isoformat()
    return fetch_fred_series(series_id, start_date=start)


def _sparkline(df: pd.DataFrame):
    fig = ui_theme.line(df, x="date", y="value", height=88)
    fig.update_layout(
        margin=dict(t=4, b=4, l=4, r=4), showlegend=False, hovermode=False,
        xaxis_visible=False, yaxis_visible=False,
    )
    return fig


def render_overview():
    st.title("The US labor market, right now")
    st.caption(
        "Live data from FRED, BLS, Census, O*NET, DOL, and SEC — "
        f"{len(catalog.SOURCES)} curated sources behind one interface."
    )

    try:
        unrate = _overview_series("UNRATE")
        payems = _overview_series("PAYEMS")
        jtsjol = _overview_series("JTSJOL")
        icsa = _overview_series("ICSA")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            latest, prev = unrate["value"].iloc[-1], unrate["value"].iloc[-2]
            st.metric("Unemployment rate", f"{latest:.1f}%", f"{latest - prev:+.1f}pp",
                      delta_color="inverse", help="U-3, seasonally adjusted (UNRATE)")
            st.plotly_chart(_sparkline(unrate), use_container_width=True, key="spark_unrate")
        with c2:
            chg = payems["value"].iloc[-1] - payems["value"].iloc[-2]
            st.metric("Payrolls, monthly change", f"{chg:+,.0f}K",
                      help="Total nonfarm payrolls, month-over-month (PAYEMS)")
            st.plotly_chart(_sparkline(payems), use_container_width=True, key="spark_payems")
        with c3:
            latest, prev = jtsjol["value"].iloc[-1], jtsjol["value"].iloc[-2]
            st.metric("Job openings", f"{latest / 1000:.1f}M", f"{(latest - prev) / 1000:+.2f}M",
                      help="JOLTS total nonfarm openings (JTSJOL)")
            st.plotly_chart(_sparkline(jtsjol), use_container_width=True, key="spark_jtsjol")
        with c4:
            latest, prev = icsa["value"].iloc[-1], icsa["value"].iloc[-2]
            st.metric("Weekly UI claims", f"{latest / 1000:.0f}K", f"{(latest - prev) / 1000:+.0f}K",
                      delta_color="inverse", help="Initial claims, seasonally adjusted (ICSA)")
            st.plotly_chart(_sparkline(icsa), use_container_width=True, key="spark_icsa")
        st.caption(f"Sparklines show the last two years. Latest data through {unrate['date'].iloc[-1]:%B %Y}.")
    except Exception:
        st.info("Headline stats need a FRED API key — free at fred.stlouisfed.org. "
                "Everything else on this page still works.")

    st.divider()
    st.subheader("Ask the data")
    st.caption("The AI Assistant answers in plain English, with charts, from the live sources.")
    qcols = st.columns(len(SAMPLE_QUESTIONS))
    for col, q in zip(qcols, SAMPLE_QUESTIONS):
        with col:
            if st.button(q, use_container_width=True, key=f"sample_{hash(q)}"):
                st.session_state["pending_chat_prompt"] = q
                st.switch_page(PAGE_ASSISTANT)

    st.divider()
    st.subheader("Three ways to use this")
    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown("**🖥️ This dashboard**")
        st.caption("Browse, chart, and download any series — no setup needed. Start with the Catalog.")
    with t2:
        st.markdown("**🤖 Your own AI**")
        st.caption(f"Add the MCP connector to Claude or ChatGPT and just ask: `{MCP_URL}`")
    with t3:
        st.markdown(f"**⚙️ Run it yourself**")
        st.caption(f"MIT-licensed on [GitHub]({GITHUB_URL}) — dashboard, connector, and API layer.")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Catalog
# ═══════════════════════════════════════════════════════════════════════════════

def render_catalog():
    st.header("Data Catalog")
    st.markdown(f"**{len(catalog.SOURCES)} curated sources** — US federal statistics, academic datasets, private-sector releases, and international databases.")

    col1, col2, col3 = st.columns([3, 1.2, 1.2])
    with col1:
        query = st.text_input(
            "Search",
            placeholder='e.g. "job openings", "remote work", "wages by occupation"',
            label_visibility="collapsed",
        )
    with col2:
        section_opts = ["All sections"] + catalog.list_sections()
        section_filter = st.selectbox("Section", section_opts, label_visibility="collapsed")
    with col3:
        conn_opts = ["All connectors"] + catalog.list_connectors()
        conn_filter = st.selectbox("Connector", conn_opts, label_visibility="collapsed")

    section = None if section_filter == "All sections" else section_filter
    connector = None if conn_filter == "All connectors" else conn_filter

    results = catalog.search(query, section=section, connector=connector) if query else catalog.filter_sources(section=section, connector=connector)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matching sources", len(results))
    c2.metric("API-connected", sum(1 for r in results if r.get("connector") in LIVE_CONNECTORS))
    c3.metric("Free to access", sum(1 for r in results if r.get("free")))
    c4.metric("Sections covered", len(set(r.get("section", "") for r in results)))
    st.divider()

    if not results:
        st.info("No sources match your search. Try broader terms.")
        return

    by_section: dict[str, list] = {}
    for r in results:
        by_section.setdefault(r.get("section", "Other"), []).append(r)

    for section_name, sources in by_section.items():
        n = len(sources)
        with st.expander(f"**{section_name}** — {n} source{'s' if n != 1 else ''}", expanded=len(by_section) == 1):
            for src in sources:
                _source_card(src)


def _source_card(src: dict):
    has_api = src.get("connector") in LIVE_CONNECTORS
    topics = " · ".join(src.get("topics", [])[:6])

    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(f"**{src['name']}**")
        b1, b2, b3 = st.columns([1, 1, 4])
        b1.badge("Live API" if has_api else "External",
                 color="green" if has_api else "gray",
                 icon=":material/api:" if has_api else ":material/open_in_new:")
        b2.badge(src.get("frequency", "—"), color="blue")
        if src.get("free"):
            b3.badge("Free", color="violet")
        st.caption(f"*{src.get('provider', '')}* — {src.get('description', '')}")
        st.caption(f"{topics}")
        if src.get("notes"):
            st.caption(f"Note: {src['notes']}")
    with col2:
        if src.get("url"):
            st.markdown(f"[Source ↗]({src['url']})")
    st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# Page: FRED Time Series
# ═══════════════════════════════════════════════════════════════════════════════

def render_fred():
    st.header("FRED Time Series")
    st.markdown("816,000+ time series from the Federal Reserve — includes virtually all BLS and Census labor data.")

    tab1, tab2 = st.tabs(["Browse Popular Series", "Search Any Series"])

    with tab1:
        topics = fred_connector.list_topics()
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_topic = st.selectbox("Select a topic", topics, format_func=lambda x: x.replace("_", " ").title())
        with col2:
            freq_label = st.selectbox("Aggregate to", ["(source frequency)", "Monthly", "Quarterly", "Annual"])

        col_d1, col_d2, col_btn = st.columns([2, 2, 1])
        with col_d1:
            start_date = st.date_input("Start date", value=date(2015, 1, 1))
        with col_d2:
            end_date = st.date_input("End date", value=date.today())
        with col_btn:
            st.write("")
            fetch = st.button("Fetch Data", type="primary", use_container_width=True)

        if fetch and selected_topic:
            freq_map = {"Monthly": "m", "Quarterly": "q", "Annual": "a", "(source frequency)": None}
            with st.spinner(f"Fetching '{selected_topic}'…"):
                try:
                    df, series_id = fetch_fred_topic(selected_topic, str(start_date), str(end_date))
                    info = fetch_fred_info(series_id)
                    _render_timeseries(df, info, series_id)
                except Exception as e:
                    st.error(f"{e}")

    with tab2:
        col1, col2 = st.columns([4, 1])
        with col1:
            search_q = st.text_input("Search FRED", placeholder='e.g. "wage growth", "remote work", "small business"')
        with col2:
            st.write("")
            search_btn = st.button("Search", type="primary", use_container_width=True)

        if search_btn and search_q:
            with st.spinner("Searching…"):
                try:
                    results = search_fred_series(search_q, limit=25)
                    if results.empty:
                        st.info("No results.")
                    else:
                        st.dataframe(
                            results[["series_id", "title", "frequency", "units", "observation_start", "observation_end", "last_updated"]],
                            use_container_width=True, hide_index=True,
                        )
                        st.caption("Copy a Series ID below to fetch it directly.")
                except Exception as e:
                    st.error(str(e))

        st.divider()
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            manual_id = st.text_input("Series ID", placeholder="e.g. UNRATE, JTSQUR, AHETPI")
        with col2:
            manual_start = st.date_input("Start", value=date(2015, 1, 1), key="manual_start")
        with col3:
            st.write("")
            manual_fetch = st.button("Fetch", key="manual_fetch", use_container_width=True)

        if manual_fetch and manual_id:
            with st.spinner(f"Fetching {manual_id.upper()}…"):
                try:
                    sid = manual_id.strip().upper()
                    df = fetch_fred_series(sid, start_date=str(manual_start))
                    info = fetch_fred_info(sid)
                    _render_timeseries(df, info, sid)
                except Exception as e:
                    st.error(str(e))


def _render_timeseries(df: pd.DataFrame, info: dict, series_id: str):
    if df.empty:
        st.warning("No data returned for this series / date range.")
        return

    title = info.get("title", series_id)
    units = info.get("units", "Value")

    st.success(f"**{title}** ({series_id}) — {len(df):,} observations")

    c1, c2, c3, c4 = st.columns(4)
    latest = df["value"].iloc[-1]
    prev = df["value"].iloc[-2] if len(df) > 1 else latest
    c1.metric("Latest", f"{latest:,.2f}", delta=f"{latest - prev:+.2f}")
    c2.metric("Units", units)
    c3.metric("Frequency", info.get("frequency", "—"))
    c4.metric("Last updated", (info.get("last_updated") or "—")[:10])

    chart_tab, table_tab, notes_tab = st.tabs(["Chart", "Table", "Series Notes"])

    with chart_tab:
        fig = ui_theme.line(df, x="date", y="value", title=title, labels={"value": units, "date": ""})
        st.plotly_chart(fig, use_container_width=True)

    with table_tab:
        display = df[["date", "value"]].copy()
        display["date"] = display["date"].dt.strftime("%Y-%m-%d")
        display.columns = ["Date", units]
        st.dataframe(display.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            display.to_csv(index=False),
            file_name=f"{series_id}_{date.today()}.csv",
            mime="text/csv",
        )

    with notes_tab:
        notes = info.get("notes", "")
        if notes:
            st.markdown(notes[:3000])
        for field in ["seasonal_adjustment", "observation_start", "observation_end"]:
            if info.get(field):
                st.text(f"{field.replace('_', ' ').title()}: {info[field]}")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: BLS Series
# ═══════════════════════════════════════════════════════════════════════════════

def render_bls():
    st.header("BLS Series")
    st.markdown("Bureau of Labor Statistics data — JOLTS, OEWS occupation wages, ECI, productivity, and more.")

    tab1, tab2, tab3 = st.tabs(["Popular Series", "Custom Series IDs", "OEWS Occupation Wages"])

    with tab1:
        popular = bls_connector.list_popular()
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            selected = st.selectbox("Series", popular, format_func=lambda x: x.replace("_", " ").title())
        with col2:
            sy = st.number_input("Start year", min_value=1990, max_value=2030, value=2015, key="pop_sy")
        with col3:
            ey = st.number_input("End year", min_value=1990, max_value=2030, value=datetime.now().year, key="pop_ey")
        with col4:
            st.write("")
            fetch = st.button("Fetch", type="primary", key="pop_fetch", use_container_width=True)

        if fetch and selected:
            with st.spinner(f"Fetching {selected}…"):
                try:
                    df = fetch_bls_popular(selected, int(sy), int(ey))
                    _render_bls_df(df, selected)
                except Exception as e:
                    st.error(str(e))

    with tab2:
        st.caption("Enter one or more BLS series IDs, comma-separated. Max 25 with a registered key.")
        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            ids_input = st.text_input("Series IDs", placeholder="CES0000000001, LNS14000000")
        with col2:
            sy2 = st.number_input("Start year", min_value=1990, max_value=2030, value=2015, key="cust_sy")
        with col3:
            ey2 = st.number_input("End year", min_value=1990, max_value=2030, value=datetime.now().year, key="cust_ey")
        with col4:
            st.write("")
            fetch2 = st.button("Fetch", type="primary", key="cust_fetch", use_container_width=True)

        if fetch2 and ids_input:
            ids = [s.strip().upper() for s in ids_input.split(",") if s.strip()]
            with st.spinner(f"Fetching {len(ids)} series…"):
                try:
                    df = fetch_bls_series(tuple(ids), int(sy2), int(ey2))
                    _render_bls_df(df, ", ".join(ids))
                except Exception as e:
                    st.error(str(e))

    with tab3:
        st.caption("Wage and employment statistics for a specific occupation (SOC code). Find SOC codes at onetonline.org.")
        col1, col2, col3, col4 = st.columns([2, 1.5, 1, 1])
        with col1:
            soc = st.text_input("SOC code (no hyphen)", placeholder="151252 = Software Developers")
        with col2:
            oews_metric = st.selectbox("Measure", ["Mean Annual Wage (M04)", "Employment (M01)", "Mean Hourly Wage (M03)"])
            metric_code = oews_metric.split("(")[1].rstrip(")")
        with col3:
            oews_sy = st.number_input("Start year", min_value=2000, max_value=2030, value=2018, key="oews_sy")
        with col4:
            st.write("")
            oews_fetch = st.button("Fetch OEWS", type="primary", use_container_width=True)

        if oews_fetch and soc:
            with st.spinner(f"Fetching OEWS for SOC {soc}…"):
                try:
                    df = fetch_oews(soc.strip(), metric_code, int(oews_sy))
                    _render_bls_df(df, f"OEWS — SOC {soc} — {oews_metric}")
                except Exception as e:
                    st.error(str(e))


def _render_bls_df(df: pd.DataFrame, label: str):
    if df.empty:
        st.warning("No data returned. Verify series IDs and that your BLS_API_KEY is set.")
        return

    st.success(f"**{label}** — {len(df):,} observations")

    if "date" in df.columns and "value" in df.columns:
        if "series_id" in df.columns and df["series_id"].nunique() > 1:
            fig = ui_theme.line(df, x="date", y="value", color="series_id", title=label)
        else:
            fig = ui_theme.line(df, x="date", y="value", title=label)
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download CSV",
        df.to_csv(index=False),
        file_name=f"bls_{date.today()}.csv",
        mime="text/csv",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Page: O*NET
# ═══════════════════════════════════════════════════════════════════════════════

def render_onet():
    st.header("O*NET Occupations")
    st.markdown("Explore 923 occupations — skills, tasks, abilities, knowledge, work activities, and technology used.")

    col1, col2 = st.columns([4, 1])
    with col1:
        search_term = st.text_input("Search occupations", placeholder='e.g. "software developer", "registered nurse", "data scientist"')
    with col2:
        st.write("")
        search_btn = st.button("Search O*NET", type="primary", use_container_width=True)

    if search_btn and search_term:
        with st.spinner("Searching O*NET…"):
            try:
                results = search_onet(search_term)
                if results.empty:
                    st.info("No occupations found.")
                else:
                    st.session_state["onet_results"] = results
            except Exception as e:
                st.error(str(e))

    if "onet_results" in st.session_state:
        results = st.session_state["onet_results"]
        st.success(f"Found {len(results)} occupations")
        st.dataframe(results, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Explore an occupation in detail**")

        codes = results["code"].tolist()
        titles = results["title"].tolist()
        options = [f"{c} — {t}" for c, t in zip(codes, titles)]
        selected = st.selectbox("Select occupation", options)

        if selected:
            occ_code = selected.split(" — ")[0]
            col1, col2 = st.columns([3, 1])
            with col1:
                data_type = st.radio(
                    "Data to load",
                    ["skills", "tasks", "abilities", "knowledge", "work_activities", "technology", "related"],
                    horizontal=True,
                )
            with col2:
                st.write("")
                load_btn = st.button("Load Data", type="primary", use_container_width=True)

            if load_btn:
                with st.spinner(f"Loading {data_type} for {occ_code}…"):
                    try:
                        df = fetch_onet_detail(data_type, occ_code)

                        if df.empty:
                            st.info("No data returned for this occupation/data type.")
                        else:
                            if "importance_value" in df.columns and "name" in df.columns:
                                top = df.nlargest(15, "importance_value")
                                fig = px.bar(
                                    top, x="importance_value", y="name", orientation="h",
                                    title=f"Top {data_type.replace('_', ' ').title()} by Importance — {occ_code}",
                                    labels={"importance_value": "Importance Score", "name": ""},
                                    color="importance_value",
                                    color_continuous_scale=ui_theme.SEQ_BLUE,
                                )
                                ui_theme.style_fig(fig, hovermode="closest")
                                fig.update_layout(coloraxis_showscale=False)
                                fig.update_yaxes(autorange="reversed", showgrid=False)
                                st.plotly_chart(fig, use_container_width=True)

                            st.dataframe(df, use_container_width=True, hide_index=True)
                            st.download_button(
                                "Download CSV",
                                df.to_csv(index=False),
                                file_name=f"onet_{occ_code}_{data_type}.csv",
                                mime="text/csv",
                            )
                    except Exception as e:
                        st.error(str(e))

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Load High-Preparation Occupations (Job Zones 4–5)", use_container_width=True):
            with st.spinner("Loading…"):
                try:
                    df = fetch_onet_list("bright")
                    st.success(f"{len(df)} high-preparation occupations")
                    st.caption("Approximate list derived from O*NET Job Zone data — "
                               "not the official BLS Bright Outlook designation.")
                    st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))
    with col2:
        if st.button("Load Green-Economy-Related Occupations (keyword match)", use_container_width=True):
            with st.spinner("Loading…"):
                try:
                    df = fetch_onet_list("green")
                    st.success(f"{len(df)} green-economy-related occupations")
                    st.caption("Keyword-derived from occupation titles and descriptions — "
                               "not O*NET's official Green Economy taxonomy.")
                    st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Job Postings (Indeed Hiring Lab)
# ═══════════════════════════════════════════════════════════════════════════════

def render_postings():
    st.header("Job Postings — Real-Time")
    st.markdown(
        "Daily job postings indexes from Indeed, about one week behind real time — "
        "the timeliest public read on US labor demand. 100 = the pre-pandemic "
        "baseline (Feb 1, 2020)."
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["National", "States", "Sectors", "Metros", "AI in Postings"])
    default_start = "2022-01-01"

    with tab1:
        try:
            df = fetch_postings_national(default_start)
            latest = df.iloc[-1]
            month_ago = df[df["date"] <= latest["date"] - pd.Timedelta(days=30)].iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("Postings index (SA)", f"{latest['postings_index_sa']:.1f}",
                      f"{latest['postings_index_sa'] - month_ago['postings_index_sa']:+.1f} vs month ago")
            c2.metric("vs pre-pandemic baseline", f"{latest['postings_index_sa'] - 100:+.1f}%")
            c3.metric("Data through", f"{latest['date']:%b %d, %Y}")
            fig = ui_theme.line(df, x="date", y="postings_index_sa",
                                title="US job postings on Indeed (seasonally adjusted)",
                                labels={"postings_index_sa": "Index (Feb 2020 = 100)", "date": ""})
            st.plotly_chart(fig, use_container_width=True)
            st.download_button("Download CSV", df.to_csv(index=False),
                               file_name="indeed_postings_us.csv", mime="text/csv")
        except Exception as e:
            st.error(str(e))

    with tab2:
        try:
            states_df = fetch_postings_states(default_start)
            mode = st.radio("View", ["Latest snapshot (all states)", "Compare states over time"],
                            horizontal=True, label_visibility="collapsed")
            if mode.startswith("Latest"):
                latest_date = states_df["date"].max()
                snap = states_df[states_df["date"] == latest_date].sort_values("postings_index", ascending=False)
                fig = ui_theme.bar(snap, x="postings_index", y="state", horizontal=True, height=1000,
                                   title=f"Postings index by state — {latest_date:%b %d, %Y}",
                                   labels={"postings_index": "Index (Feb 2020 = 100)", "state": ""})
                fig.update_yaxes(autorange="reversed", showgrid=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                picks = st.multiselect("States", sorted(states_df["state"].unique()),
                                       default=["TX", "CA", "NY", "FL"])
                if picks:
                    sel = states_df[states_df["state"].isin(picks)]
                    fig = ui_theme.line(sel, x="date", y="postings_index", color="state",
                                        title="Postings index by state",
                                        labels={"postings_index": "Index (Feb 2020 = 100)", "date": ""})
                    st.plotly_chart(fig, use_container_width=True)
            st.download_button("Download CSV", states_df.to_csv(index=False),
                               file_name="indeed_postings_states.csv", mime="text/csv")
        except Exception as e:
            st.error(str(e))

    with tab3:
        try:
            sectors_df = fetch_postings_sectors(default_start)
            mode = st.radio("View", ["Latest snapshot (all sectors)", "Compare sectors over time"],
                            horizontal=True, label_visibility="collapsed", key="sector_mode")
            if mode.startswith("Latest"):
                latest_date = sectors_df["date"].max()
                snap = sectors_df[sectors_df["date"] == latest_date].sort_values("postings_index", ascending=False)
                fig = ui_theme.bar(snap, x="postings_index", y="sector", horizontal=True, height=900,
                                   title=f"Postings index by sector — {latest_date:%b %d, %Y}",
                                   labels={"postings_index": "Index (Feb 2020 = 100)", "sector": ""})
                fig.update_yaxes(autorange="reversed", showgrid=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                picks = st.multiselect("Sectors", fetch_indeed_sectors(),
                                       default=["Software Development", "Nursing", "Retail"])
                if picks:
                    sel = sectors_df[sectors_df["sector"].isin(picks)]
                    fig = ui_theme.line(sel, x="date", y="postings_index", color="sector",
                                        title="Postings index by sector",
                                        labels={"postings_index": "Index (Feb 2020 = 100)", "date": ""})
                    st.plotly_chart(fig, use_container_width=True)
            st.download_button("Download CSV", sectors_df.to_csv(index=False),
                               file_name="indeed_postings_sectors.csv", mime="text/csv")
        except Exception as e:
            st.error(str(e))

    with tab4:
        metro_q = st.text_input("Metro area", placeholder='e.g. "Seattle", "Columbus", "Miami"')
        if metro_q:
            try:
                mdf = fetch_postings_metro(metro_q, default_start)
                if mdf.empty:
                    st.info("No metro matched — postings cover metro areas with 500k+ population.")
                else:
                    fig = ui_theme.line(mdf, x="date", y="postings_index", color="metro",
                                        title=f"Postings index — metros matching '{metro_q}'",
                                        labels={"postings_index": "Index (Feb 2020 = 100)", "date": ""})
                    st.plotly_chart(fig, use_container_width=True)
                    st.download_button("Download CSV", mdf.to_csv(index=False),
                                       file_name="indeed_postings_metro.csv", mime="text/csv")
            except Exception as e:
                st.error(str(e))

    with tab5:
        st.caption("Share of US job postings mentioning AI terms — 7-day trailing average, updated monthly.")
        try:
            ai = fetch_ai_share("2019-01-01")
            latest = ai.iloc[-1]
            c1, c2 = st.columns(2)
            c1.metric("AI share of postings", f"{latest['ai_share_pct']:.2f}%")
            yr_ago = ai[ai["date"] <= latest["date"] - pd.Timedelta(days=365)].iloc[-1]
            c2.metric("A year earlier", f"{yr_ago['ai_share_pct']:.2f}%",
                      f"{latest['ai_share_pct'] - yr_ago['ai_share_pct']:+.2f}pp since")
            fig = ui_theme.line(ai, x="date", y="ai_share_pct",
                                title="Share of US job postings mentioning AI (%)",
                                labels={"ai_share_pct": "% of postings", "date": ""})
            st.plotly_chart(fig, use_container_width=True)
            st.download_button("Download CSV", ai.to_csv(index=False),
                               file_name="indeed_ai_share.csv", mime="text/csv")
        except Exception as e:
            st.error(str(e))

    st.caption(f"{indeed_connector.ATTRIBUTION} — [github.com/hiring-lab](https://github.com/hiring-lab)")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Census
# ═══════════════════════════════════════════════════════════════════════════════

def render_census():
    st.header("Census Workforce Data")
    st.markdown("American Community Survey demographics, Quarterly Workforce Indicators, and County Business Patterns.")

    tab1, tab2, tab3 = st.tabs(["ACS Demographics", "QWI Workforce Flows", "Business Patterns"])

    with tab1:
        st.caption("Employment, income, commuting, and education by state or county (American Community Survey).")
        variables = census_connector.list_acs_variables()
        col1, col2, col3 = st.columns([3, 1, 1.4])
        with col1:
            sel_vars = st.multiselect(
                "Variables", list(variables), default=["employed", "median_household_income"],
                format_func=lambda v: v.replace("_", " ").title(),
            )
        with col2:
            acs_year = st.selectbox("Year", [2023, 2022, 2021, 2019])
        with col3:
            geography = st.selectbox("Geography", ["state", "county", "national"])

        state_fips = None
        if geography == "county":
            state_name = st.selectbox("State", list(US_STATES))
            state_fips = US_STATES[state_name]

        if st.button("Fetch ACS Data", type="primary") and sel_vars:
            with st.spinner("Fetching from the Census API…"):
                try:
                    df = fetch_acs(tuple(sel_vars), acs_year, geography, state_fips)
                    if df.empty:
                        st.info("No data returned — this year/geography combination may not be "
                                "available. Try 5-year data via county geography, or another year.")
                    else:
                        st.success(f"{len(df):,} rows")
                        first_var = sel_vars[0]
                        if geography in ("state", "county") and first_var in df.columns:
                            top = df.nlargest(15, first_var)
                            fig = ui_theme.bar(
                                top, x=first_var, y="NAME", horizontal=True,
                                title=f"Top 15 by {first_var.replace('_', ' ')} — ACS {acs_year}",
                                labels={first_var: first_var.replace("_", " "), "NAME": ""},
                            )
                            fig.update_yaxes(autorange="reversed", showgrid=False)
                            st.plotly_chart(fig, use_container_width=True)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False),
                                           file_name=f"acs_{acs_year}_{geography}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))

    with tab2:
        st.caption("Hires, separations, and earnings by state over time (LEHD Quarterly Workforce Indicators).")
        indicators = census_connector.list_qwi_indicators()
        col1, col2, col3 = st.columns([3, 1.5, 2])
        with col1:
            sel_ind = st.multiselect(
                "Indicators", list(indicators), default=["hires_all", "separations"],
                format_func=lambda v: v.replace("_", " ").title(),
            )
        with col2:
            qwi_state = st.selectbox("State", list(US_STATES), index=list(US_STATES).index("California"))
        with col3:
            qwi_years = st.slider("Years", 2010, 2024, (2018, 2024))

        if st.button("Fetch QWI Data", type="primary") and sel_ind:
            with st.spinner("Fetching from the Census API…"):
                try:
                    df = fetch_qwi(tuple(sel_ind), US_STATES[qwi_state], qwi_years[0], qwi_years[1])
                    if df.empty:
                        st.info("No data returned — QWI coverage varies by state and year.")
                    else:
                        st.success(f"{len(df):,} quarterly observations — {qwi_state}")
                        code_to_name = {v: k.replace("_", " ").title() for k, v in indicators.items()}
                        value_cols = [c for c in df.columns if c in code_to_name]
                        long = df.melt(id_vars=["date"], value_vars=value_cols,
                                       var_name="indicator", value_name="value")
                        long["indicator"] = long["indicator"].map(code_to_name)
                        fig = ui_theme.line(long, x="date", y="value", color="indicator",
                                            title=f"Quarterly workforce flows — {qwi_state}")
                        st.plotly_chart(fig, use_container_width=True)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False),
                                           file_name=f"qwi_{US_STATES[qwi_state]}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))

    with tab3:
        st.caption("Establishments, employment, and payroll by industry (County Business Patterns).")
        col1, col2 = st.columns([1, 3])
        with col1:
            cbp_year = st.selectbox("Year", [2023, 2022, 2021], key="cbp_year")
        if st.button("Fetch Business Patterns", type="primary"):
            with st.spinner("Fetching from the Census API…"):
                try:
                    df = fetch_cbp(cbp_year, "national")
                    if df.empty:
                        st.info(f"No CBP data for {cbp_year} yet — try an earlier year.")
                    else:
                        sectors = df[(df["NAICS2017"].str.len() == 2) & (df["NAICS2017"] != "00")].nlargest(15, "EMP")
                        if not sectors.empty:
                            fig = ui_theme.bar(
                                sectors, x="EMP", y="NAICS2017_LABEL", horizontal=True,
                                title=f"US employment by sector — CBP {cbp_year}",
                                labels={"EMP": "Employees", "NAICS2017_LABEL": ""},
                            )
                            fig.update_yaxes(autorange="reversed", showgrid=False)
                            st.plotly_chart(fig, use_container_width=True)
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False),
                                           file_name=f"cbp_{cbp_year}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Page: DOL Enforcement
# ═══════════════════════════════════════════════════════════════════════════════

def render_dol():
    st.header("DOL Enforcement & Labor Data")
    st.markdown("OSHA inspections, Wage & Hour enforcement, H-1B disclosures, and weekly UI claims.")

    tab1, tab2, tab3, tab4 = st.tabs(["UI Claims", "OSHA Inspections", "Wage & Hour", "H-1B Disclosures"])

    with tab1:
        st.subheader("Weekly Unemployment Insurance Claims")
        st.caption("Initial claims via FRED — one of the most timely labor market indicators available.")
        col1, col2 = st.columns([3, 1])
        with col1:
            weeks = st.slider("Weeks of history", 8, 260, 104)
        with col2:
            st.write("")
            fetch = st.button("Fetch UI Claims", type="primary", use_container_width=True)

        if fetch:
            with st.spinner("Fetching from FRED…"):
                try:
                    df = fetch_ui_claims(weeks)
                    if df.empty:
                        st.warning("No data returned. Check that FRED_API_KEY is set in .env")
                    else:
                        st.success(f"{len(df):,} weekly observations")
                        fig = ui_theme.line(
                            df, x="date", y="initial_claims_thousands",
                            title="Weekly Initial Unemployment Insurance Claims (Seasonally Adjusted, Thousands)",
                            labels={"initial_claims_thousands": "Claims (thousands)", "date": ""},
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        st.download_button("Download CSV", df.to_csv(index=False), file_name=f"ui_claims_{date.today()}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))

    with tab2:
        st.subheader("OSHA Inspections")
        st.caption("3M+ inspections since 1972 — violations, penalties, fatalities by employer and location.")
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            state = st.text_input("State (optional)", placeholder="CA, TX, NY…", key="osha_state")
        with col2:
            osha_start = st.date_input("Start date", value=date(2023, 1, 1), key="osha_start")
        with col3:
            osha_end = st.date_input("End date", value=date.today(), key="osha_end")
        with col4:
            st.write("")
            osha_fetch = st.button("Fetch", type="primary", key="osha_fetch", use_container_width=True)

        if osha_fetch:
            with st.spinner("Fetching OSHA inspections…"):
                try:
                    df = fetch_osha(state.upper() if state else None, str(osha_start), str(osha_end))
                    if df.empty:
                        st.info("No data returned via API. Download bulk data directly at [osha.gov/data](https://www.osha.gov/data)")
                    else:
                        st.success(f"{len(df):,} inspection records")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False), file_name=f"osha_{date.today()}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))

    with tab3:
        st.subheader("Wage & Hour Division Enforcement")
        st.caption("FLSA violations, back wages assessed, employees affected — by employer, industry, and state.")
        col1, col2 = st.columns([3, 1])
        with col1:
            whd_state = st.text_input("State (optional)", placeholder="CA, TX, NY…", key="whd_state")
        with col2:
            st.write("")
            whd_fetch = st.button("Fetch WHD Data", type="primary", key="whd_fetch", use_container_width=True)

        if whd_fetch:
            with st.spinner("Fetching WHD enforcement data…"):
                try:
                    df = fetch_whd(whd_state.upper() if whd_state else None)
                    if df.empty:
                        st.info("No data returned via API. Access directly at [enforcedata.dol.gov](https://enforcedata.dol.gov)")
                    else:
                        st.success(f"{len(df):,} enforcement records")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False), file_name=f"whd_{date.today()}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))

    with tab4:
        st.subheader("H-1B Labor Condition Applications")
        st.caption("Employer name, job title, wage offered, and case status for H-1B visa applications.")
        col1, col2 = st.columns([3, 1])
        with col1:
            h1b_year = st.selectbox("Fiscal year", list(range(2024, 2018, -1)))
        with col2:
            st.write("")
            h1b_fetch = st.button("Fetch H-1B Data", type="primary", key="h1b_fetch", use_container_width=True)

        if h1b_fetch:
            with st.spinner(f"Fetching H-1B data for FY{h1b_year}…"):
                try:
                    df = dol_connector.get_h1b_disclosures(year=h1b_year)
                    if df.empty:
                        st.info(f"H-1B data for FY{h1b_year} not available via API. Download quarterly files at [dol.gov/agencies/eta/foreign-labor/performance](https://www.dol.gov/agencies/eta/foreign-labor/performance)")
                    else:
                        st.success(f"{len(df):,} H-1B applications")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.download_button("Download CSV", df.to_csv(index=False), file_name=f"h1b_{h1b_year}.csv", mime="text/csv")
                except Exception as e:
                    st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Page: SEC Filings
# ═══════════════════════════════════════════════════════════════════════════════

def render_sec():
    st.header("SEC EDGAR Filings")
    st.markdown("Search public company filings for human capital disclosures, executive compensation, and layoff announcements.")

    tab1, tab2, tab3 = st.tabs(["Human Capital (10-K)", "Layoff Announcements (8-K)", "Company Search"])

    with tab1:
        st.subheader("Human Capital Disclosures")
        st.caption("Required since November 2020 (Reg S-K Item 101(c)) — headcount, workforce strategy, diversity, retention.")
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            hc_start = st.date_input("Filed after", value=date(2022, 1, 1))
        with col2:
            hc_query = st.text_input("Keywords", value="human capital employees workforce diversity retention")
        with col3:
            st.write("")
            hc_fetch = st.button("Search", type="primary", key="hc_fetch", use_container_width=True)

        if hc_fetch:
            with st.spinner("Searching EDGAR…"):
                try:
                    df = fetch_sec_filings(hc_query, "10-K", str(hc_start), 50)
                    if df.empty:
                        st.info("No results. Try adjusting keywords or date range.")
                    else:
                        st.success(f"{len(df)} filings found")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))

    with tab2:
        st.subheader("Layoff Announcements (8-K)")
        st.caption("8-K filings disclosing material workforce reductions.")
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            lay_start = st.date_input("Filed after", value=date(2023, 1, 1), key="lay_start")
        with col2:
            lay_end = st.date_input("Filed before", value=date.today(), key="lay_end")
        with col3:
            st.write("")
            lay_fetch = st.button("Search 8-Ks", type="primary", key="lay_fetch", use_container_width=True)

        if lay_fetch:
            with st.spinner("Searching EDGAR for layoff filings…"):
                try:
                    df = fetch_layoff_8k(str(lay_start), str(lay_end))
                    if df.empty:
                        st.info("No results found.")
                    else:
                        st.success(f"{len(df)} layoff filings found")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))

    with tab3:
        st.subheader("Search by Company")
        col1, col2, col3 = st.columns([3, 1.5, 1])
        with col1:
            company_name = st.text_input("Company name", placeholder="Apple, Microsoft, Amazon…")
        with col2:
            form_type = st.selectbox("Form type", ["10-K", "10-Q", "8-K", "DEF 14A"])
        with col3:
            st.write("")
            co_fetch = st.button("Search", type="primary", key="co_fetch", use_container_width=True)

        if co_fetch and company_name:
            with st.spinner(f"Searching for {company_name}…"):
                try:
                    df = fetch_company_filings(company_name, form_type)
                    if df.empty:
                        st.info("No results. Check spelling or try a shorter name.")
                    else:
                        st.success(f"{len(df)} filings found")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Page: About & Settings
# ═══════════════════════════════════════════════════════════════════════════════

def render_settings():
    st.header("About & Settings")

    st.markdown(f"""
    **Workforce Data Explorer** puts {len(catalog.SOURCES)} curated US labor market
    data sources behind one interface — this dashboard, plus an
    [MCP connector]({GITHUB_URL}#-the-ai-connector-mcp) that plugs the same live
    data into Claude or ChatGPT: `{MCP_URL}`

    MIT-licensed and open source: [github.com/thelancehaun/workforce-data-explorer]({GITHUB_URL}).
    Data comes from FRED, BLS, Census, O*NET, DOL, and SEC EDGAR — credit for
    everything here belongs to the statistical agencies that publish it.
    """)

    st.subheader("API keys")
    st.markdown("""
    Running your own copy? Add keys to a `.env` file (copy `.env.example`) —
    all free:

    | Service | Why you need it | Get key |
    |---------|----------------|-------------------|
    | **FRED** | Powers most macro time series | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
    | **BLS** | Higher rate limits for BLS series | [data.bls.gov](https://data.bls.gov/registrationEngine/) |
    | **Census Bureau** | ACS, QWI, CBP queries | [api.census.gov](https://api.census.gov/data/key_signup.html) |
    | **DOL** | OSHA / Wage & Hour enforcement | [dataportal.dol.gov](https://dataportal.dol.gov) |
    | **Groq** | The AI Assistant chat | [console.groq.com](https://console.groq.com) |
    | **O*NET** | Optional — higher rate limits | [services.onetcenter.org](https://services.onetcenter.org/) |
    """)

    st.subheader("Data cache")
    st.caption(
        "Fetched data is cached in memory (1 hour for time series, up to a day "
        "for searches and metadata) so repeat queries don't hit the source APIs."
    )
    if st.button("Clear data cache"):
        st.cache_data.clear()
        st.success("Cache cleared — the next fetch of each series will be fresh.")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: AI Assistant
# ═══════════════════════════════════════════════════════════════════════════════

# Shared-key throttle: visitors on the hosted app share one Groq free-tier
# quota, so cap questions per browser session. A visitor's own key bypasses it.
CHAT_WINDOW_SECONDS = 60
CHAT_MAX_PER_WINDOW = 4


def _chart_y_col(df: pd.DataFrame) -> Optional[str]:
    """Column to plot: the measurement, never bookkeeping columns like 'year'."""
    numeric = [c for c in df.select_dtypes(include="number").columns if c != "year"]
    if "value" in numeric:
        return "value"
    return numeric[0] if numeric else None


def render_chat():
    import time
    import workforce_data.chat as chat_engine

    st.header("AI Assistant")
    st.caption("Ask natural language questions about labor market data. Powered by GPT-OSS 120B via Groq.")

    server_key = os.getenv("GROQ_API_KEY", "")
    with st.expander("Use your own Groq API key — free, removes rate limits", expanded=not server_key):
        st.caption(
            "The shared assistant allows a few questions per minute. For unlimited use, "
            "paste a free key from [console.groq.com](https://console.groq.com/keys). "
            "It stays in your browser session and is never stored."
        )
        user_key = st.text_input("Groq API key", type="password", key="user_groq_key").strip()

    api_key = user_key or server_key
    if not api_key:
        st.info("Add a free Groq API key above to enable the AI Assistant.")
        return

    # Initialize session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []  # display messages: {"role", "content"}

    # Display conversation
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("charts"):
                for chart_info in msg["charts"]:
                    df = chart_info["df"]
                    label = chart_info["label"]
                    chart_type = chart_info["chart_type"]
                    st.caption(label)
                    if chart_type == "line" and "date" in df.columns:
                        y_col = _chart_y_col(df)
                        if y_col:
                            fig = ui_theme.line(df, x="date", y=y_col, title=label)
                            st.plotly_chart(fig, use_container_width=True)
                    elif chart_type == "bar":
                        y_col = _chart_y_col(df)
                        cat_cols = df.select_dtypes(exclude="number").columns.tolist()
                        if y_col and cat_cols:
                            fig = ui_theme.bar(df.head(20), x=cat_cols[0], y=y_col, title=label)
                            st.plotly_chart(fig, use_container_width=True)
                    st.download_button(
                        f"Download {label[:30]}… CSV" if len(label) > 30 else f"Download {label} CSV",
                        df.to_csv(index=False),
                        file_name=f"{label[:40].replace(' ', '_')}.csv",
                        mime="text/csv",
                        key=f"dl_{label[:40]}_{id(df)}",
                    )

    # Chat input — a sample-question button on the Overview page may have
    # queued a prompt before switching to this page
    user_input = st.chat_input("Ask anything: 'What's the current unemployment rate?' or 'Show me JOLTS job openings since 2020'")
    pending = st.session_state.pop("pending_chat_prompt", None)
    if not user_input and pending:
        user_input = pending

    if user_input:
        # Throttle only applies to the shared server key
        if not user_key:
            now = time.time()
            recent = [t for t in st.session_state.get("chat_times", []) if now - t < CHAT_WINDOW_SECONDS]
            if len(recent) >= CHAT_MAX_PER_WINDOW:
                wait = int(CHAT_WINDOW_SECONDS - (now - recent[0])) + 1
                st.warning(
                    f"The shared assistant is limited to {CHAT_MAX_PER_WINDOW} questions per minute. "
                    f"Try again in ~{wait}s — or add your own free Groq key above for unlimited use."
                )
                return
            st.session_state.chat_times = recent + [now]

        # Show user message immediately
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Call the chat engine
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply, updated_history, stored_dfs = chat_engine.chat(
                        st.session_state.chat_history,
                        user_input,
                        api_key=api_key,
                    )
                except Exception as e:
                    reply = f"Error: {e}"
                    updated_history = st.session_state.chat_history
                    stored_dfs = {}

            st.markdown(reply)

            # Render any charts the LLM fetched
            charts_for_msg = []
            for key, info in stored_dfs.items():
                df = info["df"]
                label = info["label"]
                chart_type = info["chart_type"]
                if df is None or df.empty:
                    continue

                st.caption(label)
                if chart_type == "line" and "date" in df.columns:
                    y_col = _chart_y_col(df)
                    if y_col:
                        fig = ui_theme.line(df, x="date", y=y_col, title=label)
                        st.plotly_chart(fig, use_container_width=True)
                elif chart_type == "bar":
                    y_col = _chart_y_col(df)
                    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
                    if y_col and cat_cols:
                        fig = ui_theme.bar(df.head(20), x=cat_cols[0], y=y_col, title=label)
                        st.plotly_chart(fig, use_container_width=True)
                elif chart_type is None:
                    st.dataframe(df.head(30), use_container_width=True, hide_index=True)

                st.download_button(
                    f"Download {label[:30]}… CSV" if len(label) > 30 else f"Download {label} CSV",
                    df.to_csv(index=False),
                    file_name=f"{label[:40].replace(' ', '_')}.csv",
                    mime="text/csv",
                    key=f"dl_{key}_{id(df)}",
                )
                charts_for_msg.append({"df": df, "label": label, "chart_type": chart_type})

        # Store for history replay
        st.session_state.chat_history = updated_history
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": reply,
            "charts": charts_for_msg,
        })

    # Clear conversation button
    if st.session_state.chat_messages:
        st.divider()
        if st.button("Clear conversation", type="secondary"):
            st.session_state.chat_history = []
            st.session_state.chat_messages = []
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Router — must be after all function definitions
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_OVERVIEW = st.Page(render_overview, title="Overview", icon="🏠", default=True, url_path="overview")
PAGE_ASSISTANT = st.Page(render_chat, title="AI Assistant", icon="💬", url_path="assistant")

pg = st.navigation({
    "": [PAGE_OVERVIEW, PAGE_ASSISTANT],
    "Explore data": [
        st.Page(render_catalog, title="Catalog", icon="🗂️", url_path="catalog"),
        st.Page(render_postings, title="Job Postings", icon="🔥", url_path="postings"),
        st.Page(render_fred, title="FRED Time Series", icon="📈", url_path="fred"),
        st.Page(render_bls, title="BLS Series", icon="🏭", url_path="bls"),
        st.Page(render_census, title="Census", icon="🗺️", url_path="census"),
        st.Page(render_onet, title="O*NET Occupations", icon="🧰", url_path="occupations"),
        st.Page(render_dol, title="DOL Enforcement", icon="⚖️", url_path="dol"),
        st.Page(render_sec, title="SEC Filings", icon="🏛️", url_path="sec"),
    ],
    "Reference": [
        st.Page(render_settings, title="About & Settings", icon="⚙️", url_path="settings"),
    ],
})
pg.run()
