"""Streamlit UI for inspecting uploaded Catalyst Center badge client JSON."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from wireless_rf.client_parser import parse_badge_client_raw
from wireless_rf.client_prometheus import render_badge_prometheus

st.set_page_config(page_title="Badge Client 802.11r Impact", layout="wide")
st.title("Vocera badge 802.11r impact")
st.caption("Upload badge client raw JSON collected from Catalyst Center client detail.")

uploaded = st.file_uploader("Badge client raw JSON", type=["json"])
if uploaded is None:
    st.info("Upload badge client raw JSON to inspect client latency, retries, roaming, and FT state.")
    st.stop()

payload = json.loads(uploaded.read().decode("utf-8", errors="replace"))
# The app accepts either raw collector output or a flat client-detail list; the
# parser handles both shapes so the UI can stay table-focused.
snapshots = parse_badge_client_raw(payload)
rows = [snapshot.to_row() for snapshot in snapshots]
df = pd.DataFrame(rows)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Badge clients", len(df))
c2.metric("FT clients", int((df.get("ft_state") == "ft").sum()) if "ft_state" in df else 0)
c3.metric("Mean retry %", "n/a" if "rx_retry_pct" not in df or df["rx_retry_pct"].dropna().empty else f"{df['rx_retry_pct'].mean():.2f}")
c4.metric("Mean voice latency us", "n/a" if "latency_voice_us" not in df or df["latency_voice_us"].dropna().empty else f"{df['latency_voice_us'].mean():.0f}")

tab_clients, tab_latency, tab_export = st.tabs(["Clients", "Latency and Retries", "Exports"])
with tab_clients:
    st.dataframe(df, use_container_width=True)

with tab_latency:
    cols = [
        "client_mac",
        "badge_model",
        "ssid",
        "ap_name",
        "band",
        "rssi_dbm",
        "snr_db",
        "rx_retry_pct",
        "latency_voice_us",
        "latency_be_us",
        "max_roaming_duration_ms",
        "average_auth_duration_ms",
        "akm",
        "ft_state",
    ]
    st.dataframe(df[[col for col in cols if col in df.columns]], use_container_width=True)

with tab_export:
    st.download_button("Download CSV", df.to_csv(index=False), file_name="badge_client_snapshot.csv", mime="text/csv")
    st.download_button(
        "Download Prometheus exposition",
        render_badge_prometheus(snapshots),
        file_name="badge_client.prom",
        mime="text/plain",
    )
