"""Reusable Streamlit UI pieces and sidebar controls."""

from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from loss_intelligence.app import cache
from loss_intelligence.app.formatting import format_datetime, format_int

DISCLAIMER = (
    "**Synthetic data — independent proof of concept.** This dashboard uses generated "
    "shipment records only. It is not affiliated with or endorsed by Mercado Libre. "
    "Alerts are review signals, not incident confirmations, fraud findings or carrier "
    "culpability conclusions."
)


def render_disclaimer() -> None:
    st.warning(DISCLAIMER, icon="⚠️")


def page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


def empty_state(message: str) -> None:
    st.info(message)


def set_flash(message: str) -> None:
    st.session_state["flash_message"] = message


def show_flash() -> None:
    message = st.session_state.pop("flash_message", None)
    if message:
        st.success(message)


def chart_layout(fig: Any, *, height: int = 340) -> Any:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=12),
    )
    return fig


def current_database() -> str:
    return str(st.session_state.get("db_target", "main"))


def _normalize_window(value: Any) -> tuple[date | None, date | None]:
    if value is None:
        return None, None
    if isinstance(value, date):
        return value, value
    if isinstance(value, (tuple, list)):
        if len(value) == 0:
            return None, None
        if len(value) == 1:
            return value[0], value[0]
        return value[0], value[1]
    return None, None


def current_window() -> tuple[date | None, date | None]:
    database = current_database()
    return _normalize_window(st.session_state.get(f"date_range_{database}"))


def current_minimum_volume() -> int:
    return int(st.session_state.get("minimum_volume", 30))


def current_maturity_days() -> int:
    return int(st.session_state.get("maturity_days", 14))


def current_confidence() -> float:
    return float(st.session_state.get("confidence", 0.95))


def render_sidebar() -> None:
    st.sidebar.title("Loss Intelligence")
    st.sidebar.caption("Synthetic-data PoC · Phase 5 dashboard")

    database = st.sidebar.selectbox(
        "Database",
        ("main", "test"),
        key="db_target",
        help=(
            "The main database is the demo dataset. The test database is used by integration tests."
        ),
    )

    try:
        bounds = cache.cohort_bounds(database)
        freshness = cache.data_freshness(database)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.sidebar.error(f"Database is not available: {exc}")
        return

    if bounds[0] is not None and bounds[1] is not None:
        key = f"date_range_{database}"
        if key not in st.session_state:
            st.session_state[key] = bounds
        st.sidebar.date_input(
            "Analysis window (shipment cohort date)",
            min_value=bounds[0],
            max_value=bounds[1],
            key=key,
            help=(
                "Cohort date is the UTC date when a shipment was created. Every KPI uses "
                "distinct eligible shipments created in this window."
            ),
        )
    else:
        st.sidebar.info("No eligible shipments found in this database.")

    st.sidebar.number_input(
        "Minimum volume",
        min_value=1,
        max_value=100000,
        value=30,
        step=10,
        key="minimum_volume",
        help=(
            "Groups below this many eligible shipments are flagged as low volume and are "
            "not ranked as if they were comparable."
        ),
    )
    st.sidebar.number_input(
        "Maturity horizon (days)",
        min_value=0,
        max_value=180,
        value=14,
        step=1,
        key="maturity_days",
        help=(
            "Recent cohorts are split into mature and immature windows so still-arriving "
            "damage reports do not look like a real decline."
        ),
    )
    st.sidebar.slider(
        "Confidence level",
        min_value=0.80,
        max_value=0.99,
        value=0.95,
        step=0.01,
        key="confidence",
        help="Confidence level for the Wilson interval on every rate.",
    )

    st.sidebar.divider()
    st.sidebar.markdown("**Data freshness**")
    st.sidebar.caption(
        f"Latest shipment: {format_datetime(freshness.get('latest_shipment_at'))}\n\n"
        f"Latest alert: {format_datetime(freshness.get('latest_alert_at'))}\n\n"
        f"Latest generation run: {format_datetime(freshness.get('latest_generation_at'))}"
    )
    if freshness.get("generator_version"):
        st.sidebar.caption(f"Generator version: `{freshness['generator_version']}`")

    st.sidebar.divider()
    st.sidebar.caption(
        "Persistent notice: all operational records are synthetic. This PoC does not use "
        "real Mercado Libre data or real loss claims."
    )


def render_scope_definition(scope_type: str) -> None:
    definitions = {
        "facility": "Exposure is distinct eligible shipments with an event at the facility.",
        "carrier": "Exposure is distinct eligible shipments handled by the carrier.",
        "carrier_zone": (
            "Exposure is distinct eligible shipments for the carrier and destination zone."
        ),
        "zone": "Exposure is distinct eligible shipments delivered to the destination zone.",
        "product_category": "Exposure is distinct eligible shipments in the product category.",
        "packaging_type": "Exposure is distinct eligible shipments using the packaging type.",
        "stage": "Exposure is distinct eligible shipments with an event in the stage.",
    }
    st.caption(definitions.get(scope_type, ""))


def render_dataframe_note(text: str) -> None:
    st.caption(text)


def freshness_line(freshness: dict[str, Any]) -> str:
    return (
        f"Latest shipment {format_datetime(freshness.get('latest_shipment_at'))} · "
        f"latest alert {format_datetime(freshness.get('latest_alert_at'))}"
    )


def alert_counts_line(counts: dict[str, int]) -> str:
    return (
        f"{format_int(counts.get('open_alerts', 0))} open alerts · "
        f"{format_int(counts.get('investigation_backlog', 0))} investigations in backlog"
    )
