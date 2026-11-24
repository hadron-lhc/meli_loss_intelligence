"""Shipment Explorer page and reusable shipment drill-down."""

from __future__ import annotations

from uuid import UUID

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from loss_intelligence.app import cache
from loss_intelligence.app.components import (
    chart_layout,
    current_database,
    empty_state,
    page_header,
)
from loss_intelligence.app.formatting import (
    alert_type_label,
    format_currency,
    format_datetime,
    format_int,
    humanize,
    priority_label,
    scope_label,
    status_label,
)


def _characteristics(detail: dict) -> None:
    st.markdown(f"**Shipment code:** `{detail['shipment_code']}`")
    st.markdown(f"**Status:** {humanize(detail['shipment_status'])}")
    left, right = st.columns(2)
    with left:
        st.write(f"Created: {format_datetime(detail['created_at'])}")
        st.write(f"Dispatched: {format_datetime(detail['dispatched_at'])}")
        st.write(f"Delivered: {format_datetime(detail['delivered_at'])}")
        st.write(f"Origin facility: {detail.get('origin_facility') or '—'}")
        st.write(f"Destination zone: {detail.get('destination_zone') or '—'}")
        st.write(f"Carrier: {detail.get('carrier_name') or '—'}")
    with right:
        st.write(f"Product category: {detail.get('product_category') or '—'}")
        st.write(f"Fragility class: {humanize(detail.get('fragility_class'))}")
        st.write(f"Packaging: {detail.get('packaging_name') or '—'}")
        st.write(f"Protection level: {humanize(detail.get('protection_level'))}")
        st.write(
            "Weight: " + (f"{format_int(detail['weight_g'])} g" if detail.get("weight_g") else "—")
        )
        dimensions = [
            detail.get("length_mm"),
            detail.get("width_mm"),
            detail.get("height_mm"),
        ]
        st.write(
            "Dimensions: "
            + (
                " × ".join(f"{format_int(value)}" for value in dimensions) + " mm"
                if all(value is not None for value in dimensions)
                else "—"
            )
        )
        st.write(
            "Declared value: "
            + format_currency(detail.get("declared_value"), detail.get("currency_code"))
        )


def _render_events(events: list[dict]) -> None:
    st.subheader("Chronological event timeline")
    if not events:
        empty_state("No events are recorded for this shipment.")
        return
    frame = pd.DataFrame(events)
    frame["occurred_at_text"] = frame["occurred_at"].apply(format_datetime)
    frame["recorded_at_text"] = frame["recorded_at"].apply(format_datetime)
    st.dataframe(
        frame[
            [
                "sequence_number",
                "occurred_at_text",
                "recorded_at_text",
                "event_code",
                "event_name",
                "stage",
                "event_status",
                "facility_name",
                "carrier_name",
                "zone_name",
                "source_system",
            ]
        ].rename(
            columns={
                "sequence_number": "Seq",
                "occurred_at_text": "Occurred",
                "recorded_at_text": "Recorded",
                "event_code": "Code",
                "event_name": "Event",
                "stage": "Stage",
                "event_status": "Status",
                "facility_name": "Facility",
                "carrier_name": "Carrier",
                "zone_name": "Zone",
                "source_system": "Source",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    figure = go.Figure(
        go.Scatter(
            x=frame["occurred_at"],
            y=frame["sequence_number"],
            mode="lines+markers",
            text=frame["event_code"],
            hovertemplate="%{text}<br>%{x|%Y-%m-%d %H:%M}<extra></extra>",
            line=dict(color="#1f77b4"),
            marker=dict(size=8),
        )
    )
    figure.update_layout(
        xaxis=dict(title="Occurred at"),
        yaxis=dict(title="Sequence", autorange="reversed"),
    )
    chart_layout(figure, height=300)
    st.plotly_chart(figure, width="stretch")
    st.caption(
        "Events are ordered by occurrence time and sequence number. Recorded-at values can "
        "differ because the synthetic data includes late recordings and timestamp conflicts."
    )


def _render_incidents(incidents: list[dict]) -> None:
    st.subheader("Confirmed and reported incidents")
    if not incidents:
        st.caption("No incidents are recorded for this shipment.")
        return
    frame = pd.DataFrame(incidents)
    frame["reported_at_text"] = frame["reported_at"].apply(format_datetime)
    frame["confirmed_at_text"] = frame["confirmed_at"].apply(format_datetime)
    frame["loss_text"] = frame.apply(
        lambda row: format_currency(row["estimated_loss_amount"], row["currency_code"]),
        axis=1,
    )
    st.dataframe(
        frame[
            [
                "incident_type",
                "damage_type",
                "severity",
                "incident_status",
                "reported_at_text",
                "confirmed_at_text",
                "loss_text",
                "evidence_type",
                "notes",
            ]
        ].rename(
            columns={
                "incident_type": "Type",
                "damage_type": "Damage",
                "severity": "Severity",
                "incident_status": "Status",
                "reported_at_text": "Reported",
                "confirmed_at_text": "Confirmed",
                "loss_text": "Estimated loss",
                "evidence_type": "Evidence",
                "notes": "Notes",
            }
        ),
        hide_index=True,
        width="stretch",
    )


def _render_alerts(alerts: list[dict]) -> None:
    st.subheader("Associated alerts")
    if not alerts:
        st.caption("No alert evidence links this shipment to an alert.")
        return
    frame = pd.DataFrame(alerts)
    frame["generated_at_text"] = frame["generated_at"].apply(format_datetime)
    frame["alert_short"] = frame["alert_id"].astype(str).str.slice(0, 8)
    frame["alert_type_text"] = frame["alert_type"].apply(alert_type_label)
    frame["scope_text"] = frame["scope_type"].apply(scope_label)
    frame["priority_text"] = frame["priority"].apply(priority_label)
    frame["status_text"] = frame["status"].apply(status_label)
    st.dataframe(
        frame[
            [
                "alert_short",
                "alert_type_text",
                "scope_text",
                "scope_name",
                "priority_text",
                "status_text",
                "generated_at_text",
                "evidence_role",
            ]
        ].rename(
            columns={
                "alert_short": "Alert",
                "alert_type_text": "Type",
                "scope_text": "Scope",
                "scope_name": "Entity",
                "priority_text": "Priority",
                "status_text": "Status",
                "generated_at_text": "Generated",
                "evidence_role": "Evidence role",
            }
        ),
        hide_index=True,
        width="stretch",
    )


def render_shipment_block(database: str, shipment_id: UUID) -> None:
    detail = cache.shipment_detail(database, shipment_id)
    if detail is None:
        empty_state("Shipment not found.")
        return
    st.subheader(f"Shipment {detail['shipment_code']}")
    _characteristics(detail)
    st.divider()
    _render_events(cache.shipment_events(database, shipment_id))
    st.divider()
    _render_incidents(cache.shipment_incidents(database, shipment_id))
    st.divider()
    _render_alerts(cache.shipment_alerts(database, shipment_id))
    st.caption(
        "This operational view does not expose hidden synthetic ground-truth labels or "
        "scenario membership."
    )


def render() -> None:
    page_header(
        "Shipment Explorer",
        "Search a shipment, inspect its event timeline and see associated incidents and alerts.",
    )
    database = current_database()
    query = st.text_input(
        "Shipment code or ID",
        placeholder="e.g. SHP-000000000000 or a shipment UUID",
        key="shipment_search_query",
    )

    try:
        results = cache.shipment_search(database, query or None, limit=50)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not search shipments: {exc}")
        return

    if not results:
        empty_state("No shipments match this search.")
        return

    frame = pd.DataFrame(results)
    frame["created_at_text"] = frame["created_at"].apply(format_datetime)
    st.dataframe(
        frame[
            [
                "shipment_code",
                "shipment_status",
                "created_at_text",
                "origin_facility",
                "destination_zone",
                "carrier_name",
                "product_category",
                "packaging_name",
            ]
        ].rename(
            columns={
                "shipment_code": "Shipment",
                "shipment_status": "Status",
                "created_at_text": "Created",
                "origin_facility": "Origin facility",
                "destination_zone": "Destination zone",
                "carrier_name": "Carrier",
                "product_category": "Category",
                "packaging_name": "Packaging",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    selected_id = st.selectbox(
        "Select a shipment",
        options=[row["shipment_id"] for row in results],
        format_func=lambda value: next(
            row["shipment_code"] for row in results if row["shipment_id"] == value
        ),
    )
    st.divider()
    render_shipment_block(database, selected_id)
