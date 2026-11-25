"""Streamlit entrypoint for the loss-intelligence dashboard."""

from __future__ import annotations

import os

import streamlit as st

from loss_intelligence.app.components import register_pages, render_disclaimer, render_sidebar
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


def _load_streamlit_secrets() -> None:
    """Expose root-level Streamlit secrets to the project's Pydantic settings."""
    from streamlit.errors import StreamlitSecretNotFoundError

    try:
        secrets = st.secrets.to_dict()
    except StreamlitSecretNotFoundError:
        return

    for name, value in secrets.items():
        if isinstance(value, (str, int, float, bool)):
            os.environ.setdefault(name, str(value))


_load_streamlit_secrets()

overview_page = st.Page(
    overview.render,
    title="Operations Overview",
    icon=":material/dashboard:",
    url_path="overview",
)
hotspots_page = st.Page(
    hotspots.render,
    title="Damage Hotspots",
    icon=":material/location_on:",
    url_path="hotspots",
)
alerts_page = st.Page(
    alerts.render,
    title="Alerts & Anomalies",
    icon=":material/notification_important:",
    url_path="alerts",
)
shipments_page = st.Page(
    shipments.render,
    title="Shipment Explorer",
    icon=":material/search:",
    url_path="shipments",
)
investigations_page = st.Page(
    investigations.render,
    title="Investigation Workspace",
    icon=":material/fact_check:",
    url_path="investigations",
)
returns_page = st.Page(
    returns.render,
    title="Returns Intelligence",
    icon=":material/assignment_return:",
    url_path="returns",
)
evaluation_page = st.Page(
    evaluation.render,
    title="Model & Evaluation",
    icon=":material/science:",
    url_path="evaluation",
)

pages = {
    "Monitor": [overview_page, hotspots_page, alerts_page],
    "Investigate": [shipments_page, investigations_page, returns_page],
    "Assess": [evaluation_page],
}

register_pages(
    {
        "overview": overview_page,
        "hotspots": hotspots_page,
        "alerts": alerts_page,
        "shipments": shipments_page,
        "investigations": investigations_page,
        "returns": returns_page,
        "evaluation": evaluation_page,
    }
)

navigation = st.navigation(pages)
render_disclaimer()
render_sidebar()
navigation.run()
