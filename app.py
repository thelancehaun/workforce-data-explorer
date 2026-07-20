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

from workforce_data import catalog, cache
from workforce_data.sources import fred as fred_connector

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Workforce Data Explorer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: 600; margin-right: 4px;
}
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Workforce Data Explorer")
    st.caption("Access 200+ workforce datasets from one interface")
    st.divider()

    page = st.radio(
        "Navigate",
        [
            "AI Assistant",
            "Catalog",
            "FRED Time Series",
            "BLS Series",
            "O*NET Occupations",
            "DOL Enforcement",
            "SEC Filings",
            "Cache & Settings",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**API Key Status**")
    for name, env_var in [("FRED", "FRED_API_KEY"), ("BLS", "BLS_API_KEY"), ("Census", "CENSUS_API_KEY"), ("O*NET", "ONET_API_KEY")]:
        if os.getenv(env_var, ""):
            st.success(f"{name} ✓", icon="🔑")
        else:
            st.warning(f"{name} — not set", icon="⚠️")
    st.caption("Add keys to `.env` to raise rate limits.")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Catalog
# ═══════════════════════════════════════════════════════════════════════════════

def render_catalog():
    st.header("Data Catalog")
    st.markdown(f"**{len(catalog.SOURCES)} sources** — US federal statistics, academic datasets, private-sector releases, and international databases.")

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
    c2.metric("API-connected", sum(1 for r in results if r.get("connector") in ("fred", "bls", "census", "onet", "dol", "sec")))
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
        with st.expander(f"**{section_name}** — {len(sources)} sources", expanded=len(by_section) == 1):
            for src in sources:
                _source_card(src)


def _source_card(src: dict):
    has_api = src.get("connector") in ("fred", "bls", "census", "onet", "dol", "sec")
    geo = ", ".join(src.get("geography", []))
    topics = " · ".join(src.get("topics", [])[:8])

    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(f"**{src['name']}** `{src['id']}`")
        st.caption(f"*{src.get('provider', '')}* — {src.get('description', '')}")
        st.caption(f"Topics: {topics} | Geography: {geo} | Frequency: {src.get('frequency', '')} | Connector: `{src.get('connector', '')}`")
        if src.get("notes"):
            st.caption(f"Note: {src['notes']}")
    with col2:
        if has_api:
            st.success("API Ready", icon="🔗")
        else:
            st.info("External", icon="🌐")
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
                    df, series_id = fred_connector.get_by_topic(
                        selected_topic,
                        start_date=str(start_date),
                        end_date=str(end_date),
                    )
                    info = fred_connector.get_series_info(series_id)
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
                    results = fred_connector.search_series(search_q, limit=25)
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
                    df = fred_connector.get_series(sid, start_date=str(manual_start))
                    info = fred_connector.get_series_info(sid)
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
        fig = px.line(df, x="date", y="value", labels={"value": units, "date": ""}, title=title)
        fig.update_traces(line_color="#1f77b4", line_width=2)
        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified", margin=dict(t=40, b=10))
        fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
        fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
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

    from workforce_data.sources import bls as bls_connector

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
                    df = bls_connector.get_popular(selected, start_year=int(sy), end_year=int(ey))
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
                    df = bls_connector.get_series(ids, start_year=int(sy2), end_year=int(ey2))
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
                    df = bls_connector.get_oews_occupation(soc.strip(), data_type=metric_code, start_year=int(oews_sy))
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
            fig = px.line(df, x="date", y="value", color="series_id", title=label)
        else:
            fig = px.line(df, x="date", y="value", title=label)
        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified")
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

    from workforce_data.sources import onet as onet_connector

    col1, col2 = st.columns([4, 1])
    with col1:
        search_term = st.text_input("Search occupations", placeholder='e.g. "software developer", "registered nurse", "data scientist"')
    with col2:
        st.write("")
        search_btn = st.button("Search O*NET", type="primary", use_container_width=True)

    if search_btn and search_term:
        with st.spinner("Searching O*NET…"):
            try:
                results = onet_connector.search_occupations(search_term, end=30)
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
                    ["skills", "tasks", "abilities", "knowledge", "work_activities", "technology"],
                    horizontal=True,
                )
            with col2:
                st.write("")
                load_btn = st.button("Load Data", type="primary", use_container_width=True)

            if load_btn:
                with st.spinner(f"Loading {data_type} for {occ_code}…"):
                    try:
                        fn_map = {
                            "skills": onet_connector.get_skills,
                            "tasks": onet_connector.get_tasks,
                            "abilities": onet_connector.get_abilities,
                            "knowledge": onet_connector.get_knowledge,
                            "work_activities": onet_connector.get_work_activities,
                            "technology": onet_connector.get_technology,
                        }
                        df = fn_map[data_type](occ_code)

                        if df.empty:
                            st.info("No data returned for this occupation/data type.")
                        else:
                            if "importance_value" in df.columns and "name" in df.columns:
                                top = df.nlargest(15, "importance_value")
                                fig = px.bar(
                                    top, x="importance_value", y="name", orientation="h",
                                    title=f"Top {data_type.replace('_', ' ').title()} by Importance — {occ_code}",
                                    labels={"importance_value": "Importance Score", "name": ""},
                                    color="importance_value", color_continuous_scale="Blues",
                                )
                                fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", showlegend=False)
                                fig.update_yaxes(autorange="reversed")
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
        if st.button("Load Bright Outlook Occupations", use_container_width=True):
            with st.spinner("Loading…"):
                try:
                    df = onet_connector.get_bright_outlook_occupations()
                    st.success(f"{len(df)} Bright Outlook occupations")
                    st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))
    with col2:
        if st.button("Load Green Economy Occupations", use_container_width=True):
            with st.spinner("Loading…"):
                try:
                    df = onet_connector.get_green_occupations()
                    st.success(f"{len(df)} Green Economy occupations")
                    st.dataframe(df, use_container_width=True, hide_index=True)
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
            from workforce_data.sources import dol as dol_connector
            with st.spinner("Fetching from FRED…"):
                try:
                    df = dol_connector.get_bls_ui_claims(weeks=weeks)
                    if df.empty:
                        st.warning("No data returned. Check that FRED_API_KEY is set in .env")
                    else:
                        st.success(f"{len(df):,} weekly observations")
                        fig = px.line(
                            df, x="date", y="initial_claims_thousands",
                            title="Weekly Initial Unemployment Insurance Claims (Seasonally Adjusted, Thousands)",
                            labels={"initial_claims_thousands": "Claims (thousands)", "date": ""},
                        )
                        fig.update_traces(line_color="#e45756")
                        fig.update_layout(plot_bgcolor="white", paper_bgcolor="white", hovermode="x unified")
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
            from workforce_data.sources import dol as dol_connector
            with st.spinner("Fetching OSHA inspections…"):
                try:
                    df = dol_connector.get_osha_inspections(
                        state=state.upper() if state else None,
                        start_date=str(osha_start),
                        end_date=str(osha_end),
                    )
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
            from workforce_data.sources import dol as dol_connector
            with st.spinner("Fetching WHD enforcement data…"):
                try:
                    df = dol_connector.get_whd_enforcement(state=whd_state.upper() if whd_state else None)
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
            from workforce_data.sources import dol as dol_connector
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

    from workforce_data.sources import sec as sec_connector

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
                    df = sec_connector.search_filings(hc_query, form_type="10-K", date_range_start=str(hc_start), limit=50)
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
                    df = sec_connector.search_layoff_8k(date_range_start=str(lay_start), date_range_end=str(lay_end))
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
                    df = sec_connector.search_company_filings(company_name, form_type=form_type)
                    if df.empty:
                        st.info("No results. Check spelling or try a shorter name.")
                    else:
                        st.success(f"{len(df)} filings found")
                        st.dataframe(df, use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Page: Cache & Settings
# ═══════════════════════════════════════════════════════════════════════════════

def render_cache():
    st.header("Cache & Settings")

    tab1, tab2 = st.tabs(["Cache Status", "API Keys"])

    with tab1:
        st.subheader("Local Cache")
        st.markdown("Fetched data is cached in `~/.workforce_data_cache/` to avoid redundant API calls.")

        stats = cache.stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Active entries", stats["active_entries"])
        c2.metric("Expired entries", stats["expired_entries"])
        c3.metric("Cache size", f"{stats['db_size_mb']} MB")
        c4.metric("Total entries", stats["total_entries"])

        if not stats["by_source"].empty:
            st.markdown("**Cached data by source:**")
            st.dataframe(stats["by_source"], use_container_width=True, hide_index=True)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Clear Entire Cache", type="secondary", use_container_width=True):
                n = cache.clear()
                st.success(f"Cleared {n} cache entries.")
        with col2:
            src_clear = st.text_input("Clear specific source ID", placeholder="e.g. bls_jolts")
            if st.button("Clear Source", use_container_width=True) and src_clear:
                n = cache.clear(src_clear)
                st.success(f"Cleared {n} entries for '{src_clear}'.")

    with tab2:
        st.subheader("API Key Setup")
        st.markdown("""
        Add keys to a `.env` file in the project root (copy from `.env.example`).

        | Service | Why you need it | Get key (all free) |
        |---------|----------------|-------------------|
        | **FRED** | Powers most macro time series | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
        | **BLS** | Higher rate limits for BLS series | [data.bls.gov](https://data.bls.gov/registrationEngine/) |
        | **Census Bureau** | ACS, QWI, CBP queries | [api.census.gov](https://api.census.gov/data/key_signup.html) |
        | **O*NET** | Higher rate limits | [services.onetcenter.org](https://services.onetcenter.org/) |

        All four can be obtained in under 5 minutes total.
        """)

        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            st.markdown("**Current `.env` (values masked):**")
            with open(env_path) as f:
                env_content = f.read()
            masked = re.sub(r"(=[^#\n]{4,})", lambda m: "=****" if m.group(1).strip("= ") not in ("", "your_fred_api_key_here", "your_bls_api_key_here", "your_census_api_key_here") else m.group(1), env_content)
            st.code(masked, language="bash")
        else:
            st.info(f"No `.env` file found. Copy `.env.example` to `.env` and fill in your keys.")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: AI Assistant
# ═══════════════════════════════════════════════════════════════════════════════

# Shared-key throttle: visitors on the hosted app share one Groq free-tier
# quota, so cap questions per browser session. A visitor's own key bypasses it.
CHAT_WINDOW_SECONDS = 60
CHAT_MAX_PER_WINDOW = 4


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
                        numeric_cols = df.select_dtypes(include="number").columns.tolist()
                        if numeric_cols:
                            fig = px.line(df, x="date", y=numeric_cols[0], title=label)
                            st.plotly_chart(fig, use_container_width=True)
                    elif chart_type == "bar":
                        numeric_cols = df.select_dtypes(include="number").columns.tolist()
                        cat_cols = df.select_dtypes(exclude="number").columns.tolist()
                        if numeric_cols and cat_cols:
                            fig = px.bar(df.head(20), x=cat_cols[0], y=numeric_cols[0], title=label)
                            st.plotly_chart(fig, use_container_width=True)
                    st.download_button(
                        f"Download {label[:30]}… CSV" if len(label) > 30 else f"Download {label} CSV",
                        df.to_csv(index=False),
                        file_name=f"{label[:40].replace(' ', '_')}.csv",
                        mime="text/csv",
                        key=f"dl_{label[:40]}_{id(df)}",
                    )

    # Chat input
    user_input = st.chat_input("Ask anything: 'What's the current unemployment rate?' or 'Show me JOLTS job openings since 2020'")

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
                    reply, updated_history = chat_engine.chat(
                        st.session_state.chat_history,
                        user_input,
                        api_key=api_key,
                    )
                    stored_dfs = chat_engine.get_stored_dfs()
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
                    numeric_cols = df.select_dtypes(include="number").columns.tolist()
                    if numeric_cols:
                        fig = px.line(df, x="date", y=numeric_cols[0], title=label)
                        st.plotly_chart(fig, use_container_width=True)
                elif chart_type == "bar":
                    numeric_cols = df.select_dtypes(include="number").columns.tolist()
                    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
                    if numeric_cols and cat_cols:
                        fig = px.bar(df.head(20), x=cat_cols[0], y=numeric_cols[0], title=label)
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

PAGE_MAP = {
    "AI Assistant": render_chat,
    "Catalog": render_catalog,
    "FRED Time Series": render_fred,
    "BLS Series": render_bls,
    "O*NET Occupations": render_onet,
    "DOL Enforcement": render_dol,
    "SEC Filings": render_sec,
    "Cache & Settings": render_cache,
}

PAGE_MAP[page]()
