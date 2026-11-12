from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    get_connection, load_tickets, save_worklog, get_worklog,
    get_ticket_counts_by_category, get_ticket_counts_by_borough,
)
from pipeline import ingest_recent_tickets, get_source_metadata
from analytics import prepare_ticket_frame, calculate_kpis
from config import APP_TITLE, DEFAULT_FETCH_LIMIT, SOURCE_URL

st.set_page_config(page_title=APP_TITLE, page_icon="🛠️", layout="wide")
st.title("ServiceOps")
st.caption("Service request operations dashboard · Real public NYC 311 data")

with st.sidebar:
    st.header("Data controls")
    fetch_limit = st.number_input(
        "Maximum recent records to fetch",
        min_value=100, max_value=10000, value=DEFAULT_FETCH_LIMIT, step=100
    )
    if st.button("↻ Refresh from source", use_container_width=True):
        with st.spinner("Fetching and validating records from NYC Open Data..."):
            try:
                result = ingest_recent_tickets(limit=int(fetch_limit))
                st.success(
                    f"Fetched {result['fetched']:,} records; "
                    f"{result['inserted_or_updated']:,} inserted/updated."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")

    st.divider()
    st.caption("Source")
    st.markdown(f"[NYC Open Data 311 dataset]({SOURCE_URL})")
    st.caption("Source records are read-only. Local notes/assignments are stored separately.")

conn = get_connection()
ticket_count = conn.execute("SELECT COUNT(*) FROM service_tickets").fetchone()[0]
conn.close()

if ticket_count == 0:
    st.info("No local records yet. Fetch a real dataset sample to initialise the dashboard.")
    if st.button("Fetch first dataset sample", type="primary"):
        with st.spinner("Fetching recent public service requests..."):
            try:
                result = ingest_recent_tickets(limit=int(fetch_limit))
                st.success(f"Loaded {result['inserted_or_updated']:,} records.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not load data: {exc}")
    st.stop()

raw = load_tickets()
if raw.empty:
    st.warning("The local database contains no ticket records.")
    st.stop()

df = prepare_ticket_frame(raw)
kpis = calculate_kpis(df)

st.caption(
    f"Showing {len(df):,} locally stored source records · "
    f"Latest source refresh: {raw['ingested_at'].max() if 'ingested_at' in raw else 'unknown'}"
)

# Filters use values actually present in the retrieved source data.
with st.sidebar:
    st.header("Filters")
    borough_values = sorted(v for v in df["borough"].dropna().unique().tolist() if str(v).strip())
    category_values = sorted(v for v in df["problem"].dropna().unique().tolist() if str(v).strip())
    agency_values = sorted(v for v in df["agency_name"].dropna().unique().tolist() if str(v).strip())

    borough_filter = st.multiselect("Borough", borough_values)
    category_filter = st.multiselect("Problem category", category_values)
    agency_filter = st.multiselect("Responding agency", agency_values)
    status_filter = st.selectbox("Request state", ["All", "Open (no closed date)", "Closed (has closed date)"])

filtered = df.copy()
if borough_filter:
    filtered = filtered[filtered["borough"].isin(borough_filter)]
if category_filter:
    filtered = filtered[filtered["problem"].isin(category_filter)]
if agency_filter:
    filtered = filtered[filtered["agency_name"].isin(agency_filter)]
if status_filter == "Open (no closed date)":
    filtered = filtered[filtered["closed_date"].isna()]
elif status_filter == "Closed (has closed date)":
    filtered = filtered[filtered["closed_date"].notna()]

kpis = calculate_kpis(filtered)

metric_cols = st.columns(4)
metric_cols[0].metric("Requests in view", f"{kpis['total']:,}")
metric_cols[1].metric("Open requests", f"{kpis['open']:,}")
metric_cols[2].metric("Closed requests", f"{kpis['closed']:,}")
metric_cols[3].metric(
    "Avg. resolution time",
    f"{kpis['avg_resolution_hours']:.1f} hrs" if pd.notna(kpis["avg_resolution_hours"]) else "N/A"
)

if "due_date" in filtered.columns:
    past_due = filtered[
        filtered["closed_date"].isna()
        & filtered["due_date"].notna()
        & (filtered["due_date"] < pd.Timestamp.now(tz="UTC").tz_localize(None))
    ]
    st.metric("Open requests past source due date", f"{len(past_due):,}")
    st.caption("This uses the due date supplied by the source; no invented SLA threshold is applied.")

st.divider()
left, right = st.columns(2)

with left:
    st.subheader("Requests by problem category")
    cat = filtered["problem"].fillna("Not specified").value_counts().head(12).rename_axis("Problem").reset_index(name="Requests")
    if not cat.empty:
        fig = px.bar(cat, x="Requests", y="Problem", orientation="h", title="Top 12 categories")
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=420)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No category data for the selected filters.")

with right:
    st.subheader("Requests by borough")
    borough = filtered["borough"].fillna("Not specified").value_counts().rename_axis("Borough").reset_index(name="Requests")
    if not borough.empty:
        fig = px.pie(borough, names="Borough", values="Requests", hole=0.45)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No borough data for the selected filters.")

st.subheader("Service request register")
display_cols = [
    "ticket_id", "created_date", "problem", "problem_detail", "agency_name",
    "borough", "status", "closed_date", "age_days", "resolution_hours"
]
display_cols = [c for c in display_cols if c in filtered.columns]
table = filtered[display_cols].copy()
st.dataframe(table, use_container_width=True, hide_index=True, height=380)

csv_bytes = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇ Download filtered records (CSV)",
    data=csv_bytes,
    file_name="serviceops_filtered_tickets.csv",
    mime="text/csv",
)

st.divider()
st.subheader("Internal follow-up notes")
st.caption(
    "These are local workflow annotations created by the demo user. "
    "They do not alter or claim to be part of the NYC Open Data source."
)

ticket_options = filtered["ticket_id"].dropna().astype(str).tolist()
if ticket_options:
    selected_ticket = st.selectbox("Select a service request", ticket_options)
    existing = get_worklog(selected_ticket)
    if existing:
        st.write("**Existing local follow-up**")
        st.write(f"Assigned to: {existing['assigned_to'] or 'Not assigned'}")
        st.write(f"Priority: {existing['priority'] or 'Not set'}")
        st.write(f"Notes: {existing['notes'] or 'No notes'}")
        st.caption(f"Last updated: {existing['updated_at']}")
    with st.form("worklog_form"):
        assigned_to = st.text_input("Assigned to (optional)", value=(existing or {}).get("assigned_to") or "")
        priority = st.selectbox(
            "Internal priority",
            ["Not set", "Low", "Normal", "High", "Urgent"],
            index=["Not set", "Low", "Normal", "High", "Urgent"].index((existing or {}).get("priority") or "Not set")
        )
        notes = st.text_area("Follow-up notes (optional)", value=(existing or {}).get("notes") or "")
        submitted = st.form_submit_button("Save local follow-up")
        if submitted:
            save_worklog(selected_ticket, assigned_to.strip(), priority, notes.strip())
            st.success("Local follow-up saved.")
            st.rerun()
else:
    st.info("No tickets available under the current filters.")

with st.expander("Data provenance and methodology"):
    try:
        metadata = get_source_metadata()
        st.write(f"**Source page title:** {metadata.get('title', 'Unavailable')}")
        st.write(f"**Description:** {metadata.get('description', 'Unavailable')}")
    except Exception as exc:
        st.warning(f"Could not retrieve source-page metadata: {exc}")
    st.markdown(
        "- Source records are fetched from the official NYC Open Data Socrata JSON endpoint.\n"
        "- Source fields are retained; records are keyed by the source unique request ID.\n"
        "- Resolution hours are calculated only for records with both creation and closure timestamps.\n"
        "- Open age is calculated from creation timestamp to the current time.\n"
        "- Internal assignments and notes are stored in a separate local table.\n"
        "- No service-level target is invented; past-due analysis uses the source due-date field where present."
    )
