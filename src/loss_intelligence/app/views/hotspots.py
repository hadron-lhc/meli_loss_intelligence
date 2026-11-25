"""Damage Hotspots page."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from loss_intelligence.app import cache, repository
from loss_intelligence.app.components import (
    chart_layout,
    current_confidence,
    current_database,
    current_minimum_volume,
    current_window,
    empty_state,
    loading,
    navigate_to,
    page_header,
    render_scope_definition,
)
from loss_intelligence.app.formatting import (
    alert_type_label,
    format_ci,
    format_currency,
    format_date,
    format_datetime,
    format_int,
    format_pct,
    priority_label,
    scope_label,
    status_label,
)


def _hotspot_frame(rows: list[dict]) -> pd.DataFrame:
    records = []
    for row in rows:
        damage = row["damage"]
        records.append(
            {
                "scope_id": row["scope_id"],
                "entity": row["scope_name"] or row["scope_id"],
                "eligible_shipments": row["eligible_shipments"],
                "damaged_shipments": row["confirmed_damage_shipments"],
                "incidents": row["confirmed_damage_incidents"],
                "damage_rate": damage["rate"],
                "damage_rate_pct": (damage["rate"] * 100) if damage["rate"] is not None else None,
                "per_1000": damage["per_1000"],
                "ci_low": damage["ci_low"],
                "ci_high": damage["ci_high"],
                "incident_share": row["incident_share"],
                "incident_share_pct": (
                    row["incident_share"] * 100 if row["incident_share"] is not None else None
                ),
                "low_volume": damage["low_volume"],
            }
        )
    return pd.DataFrame(records)


def _previous_period(start_date, end_date):
    if start_date is None or end_date is None:
        return None, None
    length = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return previous_start, previous_end


def _display_frame(frame: pd.DataFrame, compare: bool) -> tuple[pd.DataFrame, dict]:
    display = frame.copy()
    display["ci_text"] = display.apply(lambda row: format_ci(row["ci_low"], row["ci_high"]), axis=1)
    display["volume_flag"] = display["low_volume"].map({True: "Low volume", False: "Comparable"})
    columns = [
        "entity",
        "eligible_shipments",
        "damaged_shipments",
        "incidents",
        "damage_rate_pct",
        "per_1000",
        "ci_text",
        "incident_share_pct",
        "volume_flag",
    ]
    column_config: dict = {
        "Eligible shipments": st.column_config.NumberColumn(format="%d"),
        "Damaged shipments": st.column_config.NumberColumn(format="%d"),
        "Incidents": st.column_config.NumberColumn(format="%d"),
        "Damage rate": st.column_config.NumberColumn(format="%.2f%%"),
        "Per 1,000": st.column_config.NumberColumn(format="%.2f"),
        "Incident share": st.column_config.NumberColumn(format="%.2f%%"),
    }
    if compare:
        display["previous_rate_pct"] = display["previous_rate"].apply(
            lambda value: value * 100 if pd.notna(value) else None
        )
        columns.extend(["previous_rate_pct", "change_pp"])
        column_config["Previous rate"] = st.column_config.NumberColumn(format="%.2f%%")
        column_config["Change (pp)"] = st.column_config.NumberColumn(format="%+.2f pp")

    renamed = display[columns].rename(
        columns={
            "entity": "Entity",
            "eligible_shipments": "Eligible shipments",
            "damaged_shipments": "Damaged shipments",
            "incidents": "Incidents",
            "damage_rate_pct": "Damage rate",
            "per_1000": "Per 1,000",
            "ci_text": "95% CI",
            "incident_share_pct": "Incident share",
            "volume_flag": "Volume",
            "previous_rate_pct": "Previous rate",
            "change_pp": "Change (pp)",
        }
    )
    return renamed, column_config


def _render_chart(frame: pd.DataFrame) -> None:
    comparable = frame[~frame["low_volume"]].dropna(subset=["damage_rate"])
    if comparable.empty:
        empty_state(
            "No group meets the minimum-volume threshold. Lower the threshold or widen the "
            "window before ranking groups."
        )
        return
    top = comparable.sort_values("per_1000", ascending=True).tail(15)
    error_plus = (top["ci_high"] - top["damage_rate"]) * 1000
    error_minus = (top["damage_rate"] - top["ci_low"]) * 1000
    figure = go.Figure(
        go.Bar(
            x=top["per_1000"],
            y=top["entity"],
            orientation="h",
            marker_color="#1f77b4",
            error_x=dict(
                type="data",
                symmetric=False,
                array=error_plus,
                arrayminus=error_minus,
                color="#555555",
            ),
        )
    )
    figure.update_layout(
        xaxis=dict(title="Damages per 1,000 shipments"),
        yaxis=dict(title=""),
    )
    chart_layout(figure, height=max(320, 28 * len(top)))
    st.plotly_chart(figure, width="stretch")
    st.caption(
        "Comparable groups only. Bars show damages per 1,000 eligible shipments; whiskers "
        "are the Wilson confidence interval. Groups below the minimum volume are excluded "
        "from this ranking."
    )


def _format_loss_by_currency(losses: list[dict] | None) -> str:
    if not losses:
        return "—"
    return " · ".join(
        format_currency(item.get("estimated_loss_amount"), item.get("currency_code"))
        for item in losses
    )


def _render_drilldown(
    database: str,
    scope_type: str,
    frame: pd.DataFrame,
    start_date,
    end_date,
) -> None:
    st.subheader("Hotspot drill-down")
    options = frame["scope_id"].tolist()
    labels = dict(zip(frame["scope_id"], frame["entity"], strict=False))
    selected_scope_id = st.selectbox(
        "Inspect group records and alerts",
        options=options,
        format_func=lambda value: labels.get(value, str(value)),
        key=f"hotspot_drilldown_{scope_type}",
    )
    try:
        with loading("Loading group drill-down..."):
            drill = cache.hotspot_drilldown(
                database,
                scope_type,
                selected_scope_id,
                start_date,
                end_date,
            )
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load hotspot drill-down: {exc}")
        return

    left, right = st.columns(2)
    with left:
        st.markdown("**Recent confirmed-damage shipments**")
        shipments = drill["shipments"]
        if not shipments:
            st.caption("No confirmed-damage shipments attributed to this group in the window.")
        else:
            sframe = pd.DataFrame(shipments)
            sframe["loss_text"] = sframe["loss_by_currency"].apply(_format_loss_by_currency)
            st.dataframe(
                sframe[
                    [
                        "shipment_code",
                        "carrier_name",
                        "destination_zone",
                        "product_category",
                        "incident_count",
                        "loss_text",
                    ]
                ].rename(
                    columns={
                        "shipment_code": "Shipment",
                        "carrier_name": "Carrier",
                        "destination_zone": "Zone",
                        "product_category": "Category",
                        "incident_count": "Incidents",
                        "loss_text": "Est. loss by currency",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            selected_shipment = st.selectbox(
                "Open shipment",
                options=[row["shipment_id"] for row in shipments],
                format_func=lambda value: next(
                    (row["shipment_code"] for row in shipments if row["shipment_id"] == value),
                    str(value),
                ),
                key=f"hotspot_shipment_{scope_type}",
            )
            if st.button("Open in Shipment Explorer", key=f"hotspot_open_shipment_{scope_type}"):
                navigate_to("shipments", nav_shipment_id=selected_shipment)

    with right:
        st.markdown("**Alerts for this group**")
        alerts = drill["alerts"]
        if not alerts:
            st.caption("No alerts are stored for this group.")
        else:
            aframe = pd.DataFrame(alerts)
            aframe["alert_short"] = aframe["alert_id"].astype(str).str.slice(0, 8)
            aframe["type_text"] = aframe["alert_type"].apply(alert_type_label)
            aframe["priority_text"] = aframe["priority"].apply(priority_label)
            aframe["status_text"] = aframe["status"].apply(status_label)
            aframe["observed_text"] = aframe["observed_rate"].apply(
                lambda value: format_pct(float(value)) if value is not None else "—"
            )
            aframe["generated_text"] = aframe["generated_at"].apply(format_datetime)
            st.dataframe(
                aframe[
                    [
                        "alert_short",
                        "type_text",
                        "priority_text",
                        "status_text",
                        "observed_text",
                        "generated_text",
                    ]
                ].rename(
                    columns={
                        "alert_short": "Alert",
                        "type_text": "Type",
                        "priority_text": "Priority",
                        "status_text": "Status",
                        "observed_text": "Observed rate",
                        "generated_text": "Generated",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            selected_alert = st.selectbox(
                "Open alert",
                options=[row["alert_id"] for row in alerts],
                format_func=lambda value: next(
                    (
                        f"{str(row['alert_id'])[:8]} · {alert_type_label(row['alert_type'])}"
                        for row in alerts
                        if row["alert_id"] == value
                    ),
                    str(value),
                ),
                key=f"hotspot_alert_{scope_type}",
            )
            if st.button("Open in Alerts & Anomalies", key=f"hotspot_open_alert_{scope_type}"):
                navigate_to("alerts", nav_alert_id=selected_alert)


def render() -> None:
    page_header(
        "Damage Hotspots",
        "Compare damage rates with the exposure denominator, incident concentration and "
        "uncertainty cues.",
    )
    database = current_database()
    start_date, end_date = current_window()
    minimum_volume = current_minimum_volume()
    confidence = current_confidence()

    scope_type = st.selectbox(
        "Group by",
        repository.HOTSPOT_SCOPE_TYPES,
        format_func=scope_label,
        key="hotspot_scope_type",
    )
    render_scope_definition(scope_type)
    compare = st.toggle(
        "Compare with the previous period of equal length",
        key="hotspot_compare",
    )

    previous_empty = False
    try:
        with loading("Loading damage hotspots..."):
            rows = cache.hotspots(
                database,
                scope_type,
                start_date,
                end_date,
                minimum_volume,
                confidence,
            )
            frame = _hotspot_frame(rows)
            if compare:
                previous_start, previous_end = _previous_period(start_date, end_date)
                previous_rows = (
                    cache.hotspots(
                        database,
                        scope_type,
                        previous_start,
                        previous_end,
                        minimum_volume,
                        confidence,
                    )
                    if previous_start is not None
                    else []
                )
                previous_empty = not previous_rows
                previous_frame = _hotspot_frame(previous_rows)
                previous_rates = (
                    previous_frame.set_index("scope_id")["damage_rate"].to_dict()
                    if not previous_frame.empty
                    else {}
                )
                frame["previous_rate"] = frame["scope_id"].map(previous_rates)
                frame["change_pp"] = (frame["damage_rate"] - frame["previous_rate"]) * 100
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load hotspots: {exc}")
        return

    st.caption(
        f"Window {format_date(start_date)} → {format_date(end_date)} · minimum volume "
        f"{format_int(minimum_volume)} · {int(confidence * 100)}% confidence intervals."
    )
    if frame.empty:
        empty_state("No hotspot groups match the current window.")
        return

    _render_chart(frame)

    if compare:
        previous_start, previous_end = _previous_period(start_date, end_date)
        st.caption(
            f"Comparison window {format_date(previous_start)} → {format_date(previous_end)}. "
            "Change is the percentage-point difference in shipment-level damage rate."
        )
        if previous_empty:
            st.info(
                "No eligible shipments exist in the prior comparison window "
                f"({format_date(previous_start)} → {format_date(previous_end)}). "
                "Narrow the sidebar analysis window to a later sub-range to compare periods."
            )

    display, column_config = _display_frame(frame, compare)
    st.subheader("All groups")
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config=column_config,
    )
    st.caption(
        "Damage rate uses distinct affected shipments. Incident share is the share of "
        "confirmed incidents attributed to the group and is not a rate. Low-volume groups "
        "remain visible but are not ranked as comparable."
    )

    low_volume = frame[frame["low_volume"]]
    if not low_volume.empty:
        low_display, low_config = _display_frame(low_volume, compare)
        with st.expander(f"Low-volume groups ({len(low_volume)})"):
            st.dataframe(
                low_display,
                hide_index=True,
                width="stretch",
                column_config=low_config,
            )
            st.caption(
                "These groups have fewer eligible shipments than the minimum-volume "
                "threshold. Their rates are shown for completeness only."
            )

    st.divider()
    _render_drilldown(database, scope_type, frame, start_date, end_date)
