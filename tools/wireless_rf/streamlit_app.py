"""Streamlit UI for inspecting uploaded WLC RF evidence files."""

from __future__ import annotations

import json
from io import StringIO

import pandas as pd
import streamlit as st

from wireless_rf.parser import apply_filters, parse_wlc_rf_dump
from wireless_rf.prometheus import render_prometheus
from wireless_rf.stats_engine import describe, summarize_snapshots_by_site

st.set_page_config(page_title="Wireless RF Report", layout="wide")
st.title("Wireless RF neighbor and DFS report")
st.caption("Upload a raw Cisco WLC evidence file collected through an approved manual or offline process.")

uploaded = st.file_uploader("Raw WLC RF evidence file", type=["txt", "log"])
wlc = st.text_input("WLC label", value="SRHC-WLC-40G-SEC")
band = st.selectbox("Band", ["5ghz", "24ghz"], index=0)
site_tag = st.text_input("Exact Site Tag filter", value="")
site_regex = st.text_input("Site Tag regex", value="")
ap_regex = st.text_input("AP name regex", value="")
min_neighbors = st.number_input("Minimum neighbor count", min_value=0, value=0, step=1)

if uploaded is None:
    st.info("Upload a WLC raw output file to generate the report.")
    st.stop()

text = uploaded.read().decode("utf-8", errors="replace")
# Keep parsing/filtering local to the uploaded file so operators can inspect
# raw evidence without writing to the repo's scheduled export paths.
snapshots = parse_wlc_rf_dump(text, wlc=wlc, default_band=band)
filtered = apply_filters(
    snapshots,
    site_tag=site_tag or None,
    site_tag_regex=site_regex or None,
    ap_name_regex=ap_regex or None,
    band=band,
    min_neighbors=min_neighbors or None,
)
rows = [snapshot.to_row() for snapshot in filtered]
df = pd.DataFrame(rows)
summary = describe([snapshot.neighbor_count for snapshot in filtered])

c1, c2, c3, c4 = st.columns(4)
c1.metric("APs parsed", len(filtered))
c2.metric("Mean neighbors", "n/a" if summary["mean"] is None else f"{summary['mean']:.1f}")
c3.metric("APs on DFS", sum(1 for s in filtered if s.is_dfs_channel))
c4.metric("APs with radar count > 0", sum(1 for s in filtered if s.radar_changes_total and s.radar_changes_total > 0))

tab_neighbors, tab_dfs, tab_stats, tab_export = st.tabs(["Neighbor Counts", "DFS Events", "Stats", "Exports"])
with tab_neighbors:
    st.dataframe(df, use_container_width=True)

with tab_dfs:
    dfs_cols = [
        "wlc", "ap_name", "site_tag", "current_channel", "is_dfs_channel",
        "cac_running", "radar_changes_total", "zero_wait_dfs_enabled",
    ]
    st.dataframe(df[[c for c in dfs_cols if c in df.columns]], use_container_width=True)

with tab_stats:
    st.subheader("Neighbor count summary")
    st.json(summary)
    st.subheader("By Site Tag")
    st.json(summarize_snapshots_by_site(filtered))

with tab_export:
    csv_text = df.to_csv(index=False)
    st.download_button("Download CSV", csv_text, file_name="wlc_rf_snapshot.csv", mime="text/csv")
    st.download_button("Download JSON", json.dumps({"summary": summary, "rows": rows}, indent=2), file_name="wlc_rf_summary.json", mime="application/json")
    st.download_button("Download Prometheus exposition", render_prometheus(filtered), file_name="wlc_rf.prom", mime="text/plain")
