"""Returns Intelligence page (secondary)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from loss_intelligence.app import cache
from loss_intelligence.app.components import (
    chart_layout,
    current_database,
    current_window,
    empty_state,
    page_header,
)
from loss_intelligence.app.formatting import (
    condition_label,
    format_date,
    format_days,
    format_int,
    format_pct,
    inspection_label,
    reason_label,
)


def _reason_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["reason_text"] = frame["declared_reason"].apply(reason_label)
    return frame


def _render_reason_chart(rows: list[dict]) -> None:
    frame = _reason_frame(rows)
    if frame.empty:
        empty_state("No return reasons are available in this window.")
        return
    frame = frame.sort_values("return_count")
    figure = go.Figure(
        go.Bar(
            x=frame["return_count"],
            y=frame["reason_text"],
            orientation="h",
            marker_color="#6baed6",
        )
    )
    figure.update_layout(
        xaxis=dict(title="Returns"),
        yaxis=dict(title=""),
    )
    chart_layout(figure, height=max(300, 26 * len(frame)))
    st.plotly_chart(figure, width="stretch")


def _render_inspection_chart(rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    if frame.empty:
        empty_state("No inspection outcomes are available in this window.")
        return
    frame["inspection_text"] = frame["inspection_outcome"].apply(inspection_label)
    figure = go.Figure(
        go.Bar(
            x=frame["inspection_text"],
            y=frame["return_count"],
            marker_color="#fdae6b",
        )
    )
    figure.update_layout(
        xaxis=dict(title=""),
        yaxis=dict(title="Returns"),
    )
    chart_layout(figure, height=320)
    st.plotly_chart(figure, width="stretch")


def render() -> None:
    page_header(
        "Returns Intelligence",
        "Return volume, declared reasons and inspection discrepancies. This page is a "
        "secondary review aid.",
    )
    st.warning(
        "**Review signal, not a fraud determination.** This page does not accuse customers "
        "and does not support automatic blocking, enforcement or account action.",
        icon="⚠️",
    )
    database = current_database()
    start_date, end_date = current_window()

    try:
        summary = cache.returns_summary(database, start_date, end_date)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load returns intelligence: {exc}")
        return

    totals = summary["totals"]
    if totals["eligible_shipments"] == 0:
        empty_state(
            "No eligible shipments match the current window. Adjust the analysis window "
            "or load a generated dataset."
        )
        return

    st.caption(
        f"Window {format_date(start_date)} → {format_date(end_date)}. Return counts are "
        "joined to eligible shipments by shipment ID; the denominator is distinct eligible "
        "shipments in the shipment cohort."
    )

    return_rate = (
        totals["shipments_with_return"] / totals["eligible_shipments"]
        if totals["eligible_shipments"]
        else None
    )
    discrepancy_rate = (
        totals["discrepancy_returns"] / totals["inspected_returns"]
        if totals["inspected_returns"]
        else None
    )

    first, second, third, fourth = st.columns(4)
    first.metric(
        "Shipments with a return",
        format_int(totals["shipments_with_return"]),
        help=f"{format_int(totals['return_count'])} return records in the window.",
    )
    second.metric(
        "Return rate",
        format_pct(return_rate),
        help=(
            f"{format_int(totals['shipments_with_return'])} shipments with a return / "
            f"{format_int(totals['eligible_shipments'])} eligible shipments."
        ),
    )
    third.metric(
        "Repeat-return shipments",
        format_int(totals["repeat_shipments"]),
        help="Shipments with more than one return record in the window.",
    )
    fourth.metric(
        "Inspection discrepancy rate",
        format_pct(discrepancy_rate),
        help=(
            f"{format_int(totals['discrepancy_returns'])} returns whose inspection did not "
            f"match the declaration / {format_int(totals['inspected_returns'])} inspected."
        ),
    )

    fifth, sixth = st.columns(2)
    fifth.metric(
        "Average days to return",
        format_days(totals["average_days_to_return"]),
        help="Average elapsed days from shipment creation to return initiation.",
    )
    sixth.metric(
        "Returns with inspection",
        format_int(totals["inspected_returns"]),
        help="Returns whose inspection outcome is not 'not_inspected'.",
    )

    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Return volume by declared reason")
        _render_reason_chart(summary["by_reason"])
        st.caption(
            "Declared reasons describe the customer's stated reason. They are not an "
            "inspection finding."
        )
    with right:
        st.subheader("Inspection outcomes")
        _render_inspection_chart(summary["by_inspection"])
        st.caption(
            "Discrepancy signals use inspection outcomes. They require human review and do "
            "not establish intent."
        )

    st.divider()
    st.subheader("Return trend")
    daily = pd.DataFrame(summary["daily"])
    if daily.empty:
        empty_state("No daily return records are available in this window.")
    else:
        daily["return_date"] = pd.to_datetime(daily["return_date"])
        figure = go.Figure(
            go.Scatter(
                x=daily["return_date"],
                y=daily["return_count"],
                mode="lines+markers",
                line=dict(color="#e6550d"),
                name="Returns",
            )
        )
        figure.update_layout(
            xaxis=dict(title="Return initiation date"),
            yaxis=dict(title="Returns"),
        )
        chart_layout(figure, height=300)
        st.plotly_chart(figure, width="stretch")
        st.caption("Return initiation date can differ from the shipment cohort date.")

    st.divider()
    st.subheader("Discrepancy signals by reason")
    discrepancies = _reason_frame(summary["discrepancy_by_reason"])
    if discrepancies.empty:
        st.caption("No inspection discrepancies are recorded in this window.")
    else:
        st.dataframe(
            discrepancies[["reason_text", "return_count"]].rename(
                columns={"reason_text": "Declared reason", "return_count": "Returns"}
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "These are review signals only. No customer is accused and no automatic action "
            "is taken."
        )

    conditions = pd.DataFrame(summary["by_condition"])
    if not conditions.empty:
        with st.expander("Condition on return"):
            conditions["condition_text"] = conditions["condition_on_return"].apply(condition_label)
            st.dataframe(
                conditions[["condition_text", "return_count"]].rename(
                    columns={"condition_text": "Condition", "return_count": "Returns"}
                ),
                hide_index=True,
                width="stretch",
            )
