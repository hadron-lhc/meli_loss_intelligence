"""Alerts & Anomalies page."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from loss_intelligence.app import cache, repository
from loss_intelligence.app.components import (
    current_database,
    empty_state,
    page_header,
    set_flash,
    show_flash,
)
from loss_intelligence.app.formatting import (
    ALERT_TYPE_LABELS,
    alert_type_label,
    format_date,
    format_datetime,
    format_pct,
    priority_label,
    scope_label,
    status_label,
)
from loss_intelligence.app.views.shipments import render_shipment_block


def _normalize_range(value: Any) -> tuple[date | None, date | None]:
    if value is None:
        return None, None
    if isinstance(value, date):
        return value, value
    if isinstance(value, (tuple, list)):
        if len(value) == 1:
            return value[0], value[0]
        if len(value) >= 2:
            return value[0], value[1]
    return None, None


def _alert_frame(alerts: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(alerts)
    if frame.empty:
        return frame
    frame["alert_short"] = frame["alert_id"].astype(str).str.slice(0, 8)
    frame["generated_text"] = frame["generated_at"].apply(format_datetime)
    frame["scope_text"] = frame["scope_type"].apply(scope_label)
    frame["type_text"] = frame["alert_type"].apply(alert_type_label)
    frame["priority_text"] = frame["priority"].apply(priority_label)
    frame["status_text"] = frame["status"].apply(status_label)
    frame["observed_rate_text"] = frame["observed_rate"].apply(
        lambda value: format_pct(float(value)) if value is not None else "—"
    )
    frame["baseline_rate_text"] = frame["baseline_rate"].apply(
        lambda value: format_pct(float(value)) if value is not None else "—"
    )
    frame["investigation_text"] = frame["investigation_status"].apply(
        lambda value: status_label(value) if value else "None"
    )
    return frame


def _render_alert_detail(database: str, alert_id) -> None:
    alert = cache.get_alert(database, alert_id)
    if alert is None:
        empty_state("Alert not found.")
        return

    st.subheader(
        f"{alert_type_label(alert['alert_type'])} · "
        f"{scope_label(alert['scope_type'])} {alert['scope_name'] or alert['scope_id']}"
    )
    st.caption(
        f"Alert `{alert['alert_id']}` · generated {format_datetime(alert['generated_at'])} · "
        f"priority {priority_label(alert['priority'])} · status {status_label(alert['status'])}"
    )
    st.info(alert["explanation"])

    observed_rate = float(alert["observed_rate"]) if alert["observed_rate"] is not None else None
    baseline_rate = float(alert["baseline_rate"]) if alert["baseline_rate"] is not None else None
    lift = (
        observed_rate / baseline_rate
        if observed_rate is not None and baseline_rate not in (None, 0)
        else None
    )

    first, second, third, fourth = st.columns(4)
    first.metric("Observed rate", format_pct(observed_rate))
    second.metric("Baseline rate", format_pct(baseline_rate))
    third.metric("Relative lift", f"{lift:.2f}x" if lift is not None else "Baseline zero")
    fourth.metric(
        "Anomaly score",
        f"{float(alert['anomaly_score']):.2f}" if alert["anomaly_score"] is not None else "—",
        help="Stored statistical score (two-proportion z-score for this baseline).",
    )

    counts = pd.DataFrame(
        [
            {
                "Window": "Observed",
                "Start": format_datetime(alert["observed_start"]),
                "End": format_datetime(alert["observed_end"]),
                "Numerator": alert["observed_numerator"],
                "Denominator": alert["observed_denominator"],
                "Rate": format_pct(observed_rate),
            },
            {
                "Window": "Baseline",
                "Start": format_datetime(alert["baseline_start"]),
                "End": format_datetime(alert["baseline_end"]),
                "Numerator": None,
                "Denominator": None,
                "Rate": format_pct(baseline_rate),
            },
        ]
    )
    st.dataframe(counts, hide_index=True, width="stretch")
    st.caption(
        "Observed and baseline windows are shown together. The explanation includes the "
        "underlying numerator, denominator and q-value; this UI never implies causation."
    )

    st.markdown("**Contributing evidence**")
    evidence = cache.alert_evidence(database, alert_id)
    if not evidence:
        st.caption("No evidence records are linked to this alert.")
    else:
        evidence_frame = pd.DataFrame(evidence)
        evidence_frame["entity_text"] = evidence_frame["entity_type"].apply(
            lambda value: str(value).capitalize()
        )
        evidence_frame["role_text"] = evidence_frame["evidence_role"].apply(
            lambda value: str(value).capitalize()
        )
        evidence_frame["details"] = evidence_frame.apply(
            lambda row: (
                f"{row['shipment_code']} · {row['incident_type'] or ''} "
                f"{row['severity'] or ''}".strip()
                if row["entity_type"] == "incident"
                else row["shipment_code"] or ""
            ),
            axis=1,
        )
        st.dataframe(
            evidence_frame[["entity_text", "role_text", "details"]].rename(
                columns={"entity_text": "Entity", "role_text": "Role", "details": "Details"}
            ),
            hide_index=True,
            width="stretch",
        )

        shipment_ids = []
        labels = {}
        for row in evidence:
            shipment_id = row.get("shipment_id")
            if shipment_id is not None and shipment_id not in shipment_ids:
                shipment_ids.append(shipment_id)
                labels[shipment_id] = row.get("shipment_code") or str(shipment_id)
        if shipment_ids:
            selected_shipment = st.selectbox(
                "Inspect a contributing shipment",
                options=shipment_ids,
                format_func=lambda value: labels[value],
            )
            with st.expander("Shipment timeline and incidents", expanded=False):
                render_shipment_block(database, selected_shipment)

    st.divider()
    if alert["investigation_id"]:
        st.info(
            f"Investigation `{alert['investigation_id']}` is "
            f"{status_label(alert['investigation_status'])}."
        )
    elif alert["status"] in {"new", "acknowledged", "investigating"}:
        if st.button("Create investigation from this alert", type="primary"):
            try:
                investigation_id = repository.create_investigation(
                    cache.engine(database),
                    alert_id,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                cache.clear_data_cache()
                set_flash(f"Investigation {investigation_id} created from alert {alert_id}.")
                st.rerun()
    else:
        st.caption(
            "This alert is resolved or dismissed. Reopen it through an investigation if "
            "further review is required."
        )


def render() -> None:
    page_header(
        "Alerts & Anomalies",
        "Filter review signals, inspect observed versus baseline rates and drill into "
        "contributing shipments.",
    )
    show_flash()
    database = current_database()

    try:
        options = cache.alert_filter_options(database)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load alert filters: {exc}")
        return

    first_generated = options.get("first_generated")
    last_generated = options.get("last_generated")
    alert_types = options.get("alert_types") or sorted(ALERT_TYPE_LABELS)

    filter_left, filter_right = st.columns([2, 2])
    with filter_left:
        statuses = st.multiselect(
            "Status",
            options=repository.ALERT_STATUSES,
            format_func=status_label,
            key="alert_status_filter",
        )
        priorities = st.multiselect(
            "Priority",
            options=repository.ALERT_PRIORITIES,
            format_func=priority_label,
            key="alert_priority_filter",
        )
    with filter_right:
        selected_types = st.multiselect(
            "Alert type",
            options=alert_types,
            format_func=alert_type_label,
            key="alert_type_filter",
        )
        search = st.text_input("Search alert, entity or explanation", key="alert_search")

    generated_start, generated_end = None, None
    if first_generated is not None and last_generated is not None:
        key = "alert_generated_range"
        if key not in st.session_state:
            st.session_state[key] = (first_generated, last_generated)
        selected_range = st.date_input(
            "Generated date range",
            min_value=first_generated,
            max_value=last_generated,
            key=key,
        )
        generated_start, generated_end = _normalize_range(selected_range)

    try:
        alerts = cache.list_alerts(
            database,
            tuple(statuses) or None,
            tuple(priorities) or None,
            tuple(selected_types) or None,
            generated_start,
            generated_end,
            search or None,
            250,
        )
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load alerts: {exc}")
        return

    st.caption(
        f"{len(alerts)} alerts match the filters. Generated date range "
        f"{format_date(generated_start)} → {format_date(generated_end)}."
    )
    if not alerts:
        empty_state("No alerts match the current filters.")
        return

    frame = _alert_frame(alerts)
    st.dataframe(
        frame[
            [
                "alert_short",
                "generated_text",
                "scope_text",
                "scope_name",
                "type_text",
                "priority_text",
                "status_text",
                "anomaly_score",
                "observed_rate_text",
                "baseline_rate_text",
                "investigation_text",
            ]
        ].rename(
            columns={
                "alert_short": "Alert",
                "generated_text": "Generated",
                "scope_text": "Scope",
                "scope_name": "Entity",
                "type_text": "Type",
                "priority_text": "Priority",
                "status_text": "Status",
                "anomaly_score": "Score",
                "observed_rate_text": "Observed rate",
                "baseline_rate_text": "Baseline rate",
                "investigation_text": "Investigation",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    selected_alert = st.selectbox(
        "Open alert detail",
        options=[row["alert_id"] for row in alerts],
        format_func=lambda value: next(
            f"{row['alert_short']} · {row['type_text']} · {row['scope_name'] or ''}"
            for row in frame.to_dict("records")
            if row["alert_id"] == value
        ),
    )
    st.divider()
    _render_alert_detail(database, selected_alert)
