"""Streamlit entrypoint for the loss-intelligence dashboard."""

from __future__ import annotations

import streamlit as st

from loss_intelligence.app.components import render_disclaimer, render_sidebar
from loss_intelligence.app.views import (
    alerts,
    evaluation,
    hotspots,
    investigations,
    overview,
    returns,
    shipments,
)

st.set_page_config(
    page_title="Loss Intelligence PoC",
    page_icon=":material/local_shipping:",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = {
    "Monitor": [
        st.Page(
            overview.render,
            title="Operations Overview",
            icon=":material/dashboard:",
            url_path="overview",
        ),
        st.Page(
            hotspots.render,
            title="Damage Hotspots",
            icon=":material/location_on:",
            url_path="hotspots",
        ),
        st.Page(
            alerts.render,
            title="Alerts & Anomalies",
            icon=":material/notification_important:",
            url_path="alerts",
        ),
    ],
    "Investigate": [
        st.Page(
            shipments.render,
            title="Shipment Explorer",
            icon=":material/search:",
            url_path="shipments",
        ),
        st.Page(
            investigations.render,
            title="Investigation Workspace",
            icon=":material/fact_check:",
            url_path="investigations",
        ),
        st.Page(
            returns.render,
            title="Returns Intelligence",
            icon=":material/assignment_return:",
            url_path="returns",
        ),
    ],
    "Assess": [
        st.Page(
            evaluation.render,
            title="Model & Evaluation",
            icon=":material/science:",
            url_path="evaluation",
        ),
    ],
}

navigation = st.navigation(pages)
render_disclaimer()
render_sidebar()
navigation.run()
