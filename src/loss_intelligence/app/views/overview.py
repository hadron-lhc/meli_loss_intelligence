"""Operations Overview page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from loss_intelligence.app import cache
from loss_intelligence.app.components import (
    chart_layout,
    current_confidence,
    current_database,
    current_maturity_days,
    current_minimum_volume,
    current_window,
    empty_state,
    freshness_line,
    loading,
    navigate_to,
    page_header,
)
from loss_intelligence.app.formatting import (
    format_ci,
    format_currency,
    format_date,
    format_datetime,
    format_int,
    format_pct,
    format_per_1000,
)


def _daily_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["cohort_date"] = pd.to_datetime(frame["cohort_date"])
    frame["damage_rate"] = frame["damage"].apply(lambda value: value["rate"])
    frame["ci_low"] = frame["damage"].apply(lambda value: value["ci_low"])
    frame["ci_high"] = frame["damage"].apply(lambda value: value["ci_high"])
    frame["low_volume"] = frame["damage"].apply(lambda value: value["low_volume"])
    return frame


def _render_kpis(overview: dict, counts: dict) -> None:
    damage = overview["damage"]
    first, second, third = st.columns(3)
    first.metric(
        "Processed shipments",
        format_int(overview["eligible_shipments"]),
        help="Distinct delivered or returned non-test shipments created in the analysis window.",
    )
    second.metric(
        "Confirmed damage incidents",
        format_int(overview["confirmed_damage_incidents"]),
        help="Confirmed package-damage incidents linked to eligible shipments in the window.",
    )
    third.metric(
        "Damage rate",
        format_pct(damage["rate"]),
        help=(
            f"{format_int(damage['numerator'])} damaged shipments / "
            f"{format_int(damage['denominator'])} eligible shipments. "
            f"{format_ci(damage['ci_low'], damage['ci_high'])} Wilson interval."
        ),
    )

    fourth, fifth, sixth = st.columns(3)
    fourth.metric(
        "Damages per 1,000 shipments",
        format_per_1000(damage["per_1000"]),
        help="Damage rate multiplied by 1,000.",
    )
    fifth.metric(
        "Open alerts (current)",
        format_int(counts.get("open_alerts", 0)),
        help=(
            "Current global alerts in new, acknowledged or investigating status across all "
            "detection runs (not filtered by the sidebar cohort window)."
        ),
    )
    sixth.metric(
        "Investigation backlog (current)",
        format_int(counts.get("investigation_backlog", 0)),
        help=(
            "Current global investigations in open or in-review status (not filtered by the "
            "sidebar cohort window)."
        ),
    )

    if counts.get("open_alerts", 0) > 0:
        if st.button("Review open alerts →", key="overview_open_alerts_nav"):
            navigate_to("alerts")

    if damage["low_volume"]:
        st.caption(
            f"Overall volume is below the minimum-volume threshold of "
            f"{format_int(damage['minimum_volume'])}; interpret this rate cautiously."
        )


def _render_loss(losses: list[dict]) -> None:
    st.subheader("Estimated synthetic loss")
    if not losses:
        st.caption("No confirmed loss amounts are available in this window.")
        return
    columns = st.columns(min(len(losses), 3))
    for column, item in zip(columns, losses[:3], strict=False):
        column.metric(
            f"Estimated loss ({item['currency_code']})",
            format_currency(item["estimated_loss_amount"], item["currency_code"]),
            help=(
                f"{format_int(item['confirmed_damage_incidents'])} confirmed incidents "
                "with an estimated amount. Currencies are never summed together."
            ),
        )
    st.caption(
        "Synthetic estimated amounts only. Loss is grouped by currency and is not a "
        "financial liability calculation."
    )


def _add_maturity_marker(figure: go.Figure, frame: pd.DataFrame, maturity: dict) -> None:
    mature_end = maturity.get("mature_end_date")
    maturity_days = maturity.get("maturity_days", 0)
    if mature_end is None or maturity_days <= 0 or frame.empty:
        return
    min_date = frame["cohort_date"].min().date()
    max_date = frame["cohort_date"].max().date()
    if mature_end >= max_date or mature_end < min_date:
        return

    boundary = mature_end.isoformat()
    figure.add_vrect(
        x0=boundary,
        x1=max_date.isoformat(),
        fillcolor="rgba(217, 119, 6, 0.10)",
        line_width=0,
    )
    figure.add_shape(
        type="line",
        x0=boundary,
        x1=boundary,
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color="#d97706", width=1.5, dash="dash"),
    )
    figure.add_annotation(
        x=boundary,
        y=1,
        yref="paper",
        text=f"Immature tail ({maturity_days}d)",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font=dict(size=11, color="#b45309"),
    )


def _render_trend(daily: list[dict], maturity: dict) -> None:
    st.subheader("Damage-rate trend")
    frame = _daily_frame(daily)
    if frame.empty:
        empty_state("No daily metrics are available in this window.")
        return

    rate_figure = go.Figure()
    rate_figure.add_trace(
        go.Scatter(
            x=frame["cohort_date"],
            y=frame["ci_high"],
            line=dict(width=0),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    rate_figure.add_trace(
        go.Scatter(
            x=frame["cohort_date"],
            y=frame["ci_low"],
            fill="tonexty",
            line=dict(width=0),
            fillcolor="rgba(31, 119, 180, 0.16)",
            name="Wilson interval",
            hoverinfo="skip",
        )
    )
    rate_figure.add_trace(
        go.Scatter(
            x=frame["cohort_date"],
            y=frame["damage_rate"],
            mode="lines+markers",
            name="Damage rate",
            line=dict(color="#1f77b4", width=2),
        )
    )
    rate_figure.update_layout(
        yaxis=dict(title="Damage rate", tickformat=".2%"),
        xaxis=dict(title="Shipment cohort date"),
    )
    _add_maturity_marker(rate_figure, frame, maturity)
    chart_layout(rate_figure)

    volume_figure = go.Figure(
        go.Bar(
            x=frame["cohort_date"],
            y=frame["eligible_shipments"],
            name="Eligible shipments",
            marker_color="#9ecae1",
        )
    )
    volume_figure.update_layout(
        yaxis=dict(title="Eligible shipments"),
        xaxis=dict(title="Shipment cohort date"),
    )
    _add_maturity_marker(volume_figure, frame, maturity)
    chart_layout(volume_figure)

    left, right = st.columns(2)
    with left:
        st.plotly_chart(rate_figure, width="stretch")
        st.caption(
            "Damage rate = distinct confirmed package-damage shipments / eligible "
            "shipments. The band is the selected Wilson confidence interval."
        )
    with right:
        st.plotly_chart(volume_figure, width="stretch")
        st.caption(
            "Denominator by cohort date. Recent dates are immature and may still receive "
            "damage reports."
        )


def _render_maturity(overview: dict) -> None:
    maturity = overview["maturity"]
    with st.expander("Maturity adjustment and metric definitions"):
        left, right = st.columns(2)
        left.metric(
            "Mature cohort rate",
            format_pct(maturity["mature"]["rate"]),
            help=(
                f"{format_int(maturity['mature']['numerator'])} / "
                f"{format_int(maturity['mature']['denominator'])} shipments through "
                f"{format_date(maturity['mature_end_date'])}."
            ),
        )
        right.metric(
            "Immature cohort rate",
            format_pct(maturity["immature"]["rate"]),
            help=(
                f"{format_int(maturity['immature']['numerator'])} / "
                f"{format_int(maturity['immature']['denominator'])} shipments in the last "
                f"{maturity['maturity_days']} days."
            ),
        )
        st.markdown(
            "- **Cohort date** is the UTC date when the shipment was created.\n"
            "- **Eligible shipment** is delivered or returned, non-test, with a delivery "
            "timestamp.\n"
            "- **Damage rate** uses distinct affected shipments, not incident rows.\n"
            f"- The last **{maturity['maturity_days']} days** are immature so still-arriving "
            "damage reports are not mistaken for a decline."
        )


def _render_data_quality(quality: dict) -> None:
    totals = quality["totals"]
    labels = {
        "late_recorded_events": "Late-recorded events",
        "timestamp_conflicts": "Timestamp conflicts",
        "duplicate_event_records": "Duplicate event records",
        "shipments_with_duplicate_event_codes": "Shipments with duplicate event codes",
        "events_missing_facility": "Events missing facility",
        "events_missing_carrier": "Events missing carrier",
        "shipments_missing_dimensions": "Shipments missing dimensions",
        "data_gap_events": "Data-gap events",
    }
    with st.expander("Data-quality observability"):
        frame = pd.DataFrame([{"Signal": labels[key], "Count": totals[key]} for key in labels])
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Count": st.column_config.NumberColumn(format="%d"),
            },
        )
        st.caption(
            "These signals describe synthetic data quality. They are not counted as damage "
            "and do not block operational metrics."
        )


def render() -> None:
    page_header(
        "Operations Overview",
        "Current synthetic operating picture with transparent denominators, uncertainty "
        "and alert backlog.",
    )
    database = current_database()
    start_date, end_date = current_window()
    minimum_volume = current_minimum_volume()
    confidence = current_confidence()
    maturity_days = current_maturity_days()

    try:
        with loading("Loading operations overview..."):
            overview = cache.overview(
                database,
                start_date,
                end_date,
                minimum_volume,
                confidence,
                maturity_days,
            )
            daily = cache.daily_metrics(database, start_date, end_date, minimum_volume, confidence)
            losses = cache.loss_by_currency(database, start_date, end_date)
            quality = cache.data_quality(database, start_date, end_date)
            counts = cache.operational_counts(database)
            freshness = cache.data_freshness(database)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load the operations overview: {exc}")
        return

    st.caption(
        f"Window {format_date(overview['start_date'])} → {format_date(overview['end_date'])} · "
        f"{freshness_line(freshness)}"
    )
    if overview["eligible_shipments"] == 0:
        empty_state(
            "No eligible shipments match the current window. Adjust the analysis window or "
            "load a generated dataset."
        )
        return

    _render_kpis(overview, counts)
    st.divider()
    _render_loss(losses)
    st.divider()
    _render_trend(daily, overview["maturity"])
    st.divider()
    _render_maturity(overview)
    _render_data_quality(quality)
    st.caption(f"Data loaded at {format_datetime(freshness.get('latest_generation_at'))}.")
