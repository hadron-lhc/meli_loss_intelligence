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
    loading,
    navigate_to,
    page_header,
)
from loss_intelligence.app.formatting import (
    alert_type_label,
    condition_label,
    format_currency,
    format_datetime,
    format_int,
    humanize,
    inspection_label,
    priority_label,
    reason_label,
    scope_label,
    status_label,
)

SHIPMENT_STATUS_OPTIONS = (
    None,
    "created",
    "in_transit",
    "delivered",
    "returned",
    "cancelled",
    "lost",
    "unknown",
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
    frame["related_event_text"] = frame.apply(
        lambda row: (
            f"#{int(row['related_event_sequence'])} {row['related_event_code']}"
            if pd.notna(row.get("related_event_sequence")) and row.get("related_event_code")
            else ("Linked" if row.get("related_event_id") else "—")
        ),
        axis=1,
    )
    st.dataframe(
        frame[
            [
                "incident_type",
                "damage_type",
                "severity",
                "incident_status",
                "related_event_text",
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
                "related_event_text": "Related event",
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


def _render_returns(returns: list[dict]) -> None:
    st.subheader("Returns")
    if not returns:
        st.caption("No return records are associated with this shipment.")
        return
    frame = pd.DataFrame(returns)
    frame["initiated_text"] = frame["initiated_at"].apply(format_datetime)
    frame["received_text"] = frame["received_at"].apply(format_datetime)
    frame["reason_text"] = frame["declared_reason"].apply(reason_label)
    frame["inspection_text"] = frame["inspection_outcome"].apply(inspection_label)
    frame["status_text"] = frame["return_status"].apply(humanize)
    frame["condition_text"] = frame["condition_on_return"].apply(condition_label)
    st.dataframe(
        frame[
            [
                "initiated_text",
                "received_text",
                "status_text",
                "reason_text",
                "inspection_text",
                "condition_text",
            ]
        ].rename(
            columns={
                "initiated_text": "Initiated",
                "received_text": "Received",
                "status_text": "Status",
                "reason_text": "Declared reason",
                "inspection_text": "Inspection",
                "condition_text": "Condition",
            }
        ),
        hide_index=True,
        width="stretch",
    )


def _render_alerts(alerts: list[dict], *, key_prefix: str) -> None:
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
    selected_alert = st.selectbox(
        "Open associated alert",
        options=[row["alert_id"] for row in alerts],
        format_func=lambda value: next(
            (
                f"{str(row['alert_id'])[:8]} · {alert_type_label(row['alert_type'])} · "
                f"{row['scope_name'] or ''}"
                for row in alerts
                if row["alert_id"] == value
            ),
            str(value),
        ),
        key=f"{key_prefix}_alert_select",
    )
    if st.button("Open in Alerts & Anomalies →", key=f"{key_prefix}_open_alert"):
        navigate_to("alerts", nav_alert_id=selected_alert)


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
    _render_returns(cache.shipment_returns(database, shipment_id))
    st.divider()
    _render_alerts(cache.shipment_alerts(database, shipment_id), key_prefix=f"ship_{shipment_id}")
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
    select_key = f"shipment_selected_{database}"

    nav_shipment_id = st.session_state.pop("nav_shipment_id", None)
    if nav_shipment_id is not None:
        st.session_state[select_key] = nav_shipment_id
        st.session_state.pop("shipment_search_query", None)
        st.session_state.pop("shipment_status_filter", None)
        st.session_state.pop("shipment_damaged_only", None)

    search_col, status_col, damage_col = st.columns([3, 1, 1])
    with search_col:
        query = st.text_input(
            "Shipment code or ID",
            placeholder="e.g. SHP-000000000000 or a shipment UUID",
            key="shipment_search_query",
        )
    with status_col:
        status_filter = st.selectbox(
            "Status",
            options=SHIPMENT_STATUS_OPTIONS,
            format_func=lambda value: "All statuses" if value is None else humanize(value),
            key="shipment_status_filter",
        )
    with damage_col:
        damaged_only = st.checkbox(
            "Confirmed damage only",
            key="shipment_damaged_only",
        )

    try:
        with loading("Searching shipments..."):
            results = cache.shipment_search(
                database,
                query or None,
                status=status_filter,
                damaged_only=damaged_only,
                limit=50,
            )
            pinned_id = st.session_state.get(select_key)
            if (
                pinned_id is not None
                and not query
                and status_filter is None
                and not damaged_only
                and all(row["shipment_id"] != pinned_id for row in results)
            ):
                pinned = cache.shipment_detail(database, pinned_id)
                if pinned is not None:
                    results = [pinned, *results]
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

    shipment_options = [row["shipment_id"] for row in results]
    if select_key in st.session_state and st.session_state[select_key] not in shipment_options:
        st.session_state[select_key] = shipment_options[0]

    selected_id = st.selectbox(
        "Select a shipment",
        options=shipment_options,
        format_func=lambda value: next(
            (row["shipment_code"] for row in results if row["shipment_id"] == value),
            str(value),
        ),
        key=select_key,
    )
    st.divider()
    render_shipment_block(database, selected_id)
