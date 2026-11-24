"""Damage Hotspots page."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from loss_intelligence.analytics.metrics import SCOPE_TYPES
from loss_intelligence.app import cache
from loss_intelligence.app.components import (
    chart_layout,
    current_confidence,
    current_database,
    current_minimum_volume,
    current_window,
    empty_state,
    page_header,
    render_scope_definition,
)
from loss_intelligence.app.formatting import (
    format_ci,
    format_date,
    format_int,
    format_pct,
    format_per_1000,
    scope_label,
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
                "per_1000": damage["per_1000"],
                "ci_low": damage["ci_low"],
                "ci_high": damage["ci_high"],
                "incident_share": row["incident_share"],
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


def _display_frame(frame: pd.DataFrame, compare: bool) -> pd.DataFrame:
    display = frame.copy()
    display["damage_rate_pct"] = display["damage_rate"].apply(format_pct)
    display["per_1000_text"] = display["per_1000"].apply(format_per_1000)
    display["ci_text"] = display.apply(lambda row: format_ci(row["ci_low"], row["ci_high"]), axis=1)
    display["incident_share_pct"] = display["incident_share"].apply(format_pct)
    display["volume_flag"] = display["low_volume"].map({True: "Low volume", False: "Comparable"})
    columns = [
        "entity",
        "eligible_shipments",
        "damaged_shipments",
        "incidents",
        "damage_rate_pct",
        "per_1000_text",
        "ci_text",
        "incident_share_pct",
        "volume_flag",
    ]
    if compare:
        display["previous_rate_pct"] = display["previous_rate"].apply(format_pct)
        display["change_pp_text"] = display["change_pp"].apply(
            lambda value: "—" if pd.isna(value) else f"{value:+.2f} pp"
        )
        columns.extend(["previous_rate_pct", "change_pp_text"])
    display = display[columns].rename(
        columns={
            "entity": "Entity",
            "eligible_shipments": "Eligible shipments",
            "damaged_shipments": "Damaged shipments",
            "incidents": "Incidents",
            "damage_rate_pct": "Damage rate",
            "per_1000_text": "Per 1,000",
            "ci_text": "95% CI",
            "incident_share_pct": "Incident share",
            "volume_flag": "Volume",
            "previous_rate_pct": "Previous rate",
            "change_pp_text": "Change",
        }
    )
    return display


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
        SCOPE_TYPES,
        format_func=scope_label,
        key="hotspot_scope_type",
    )
    render_scope_definition(scope_type)
    compare = st.toggle(
        "Compare with the previous period of equal length",
        key="hotspot_compare",
    )

    try:
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

    display = _display_frame(frame, compare)
    st.subheader("All groups")
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Eligible shipments": st.column_config.NumberColumn(format="%d"),
            "Damaged shipments": st.column_config.NumberColumn(format="%d"),
            "Incidents": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.caption(
        "Damage rate uses distinct affected shipments. Incident share is the share of "
        "confirmed incidents attributed to the group and is not a rate. Low-volume groups "
        "remain visible but are not ranked as comparable."
    )

    low_volume = frame[frame["low_volume"]]
    if not low_volume.empty:
        with st.expander(f"Low-volume groups ({len(low_volume)})"):
            st.dataframe(
                _display_frame(low_volume, compare),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "These groups have fewer eligible shipments than the minimum-volume "
                "threshold. Their rates are shown for completeness only."
            )
