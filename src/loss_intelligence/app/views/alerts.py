"""Alerts & Anomalies page."""

from __future__ import annotations

from uuid import UUID

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from loss_intelligence.app import cache, repository
from loss_intelligence.app.components import (
    current_database,
    empty_state,
    loading,
    navigate_to,
    normalize_date_range,
    page_header,
    set_flash,
    show_flash,
)
from loss_intelligence.app.formatting import (
    ALERT_TYPE_LABELS,
    alert_type_label,
    condition_label,
    format_date,
    format_datetime,
    format_pct,
    inspection_label,
    priority_label,
    reason_label,
    scope_label,
    status_label,
)
from loss_intelligence.app.views.shipments import render_shipment_block


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
    frame["observed_rate_pct"] = frame["observed_rate"].apply(
        lambda value: float(value) * 100 if value is not None else None
    )
    frame["baseline_rate_pct"] = frame["baseline_rate"].apply(
        lambda value: float(value) * 100 if value is not None else None
    )
    frame["score_num"] = frame["anomaly_score"].apply(
        lambda value: float(value) if value is not None else None
    )
    frame["investigation_text"] = frame["investigation_status"].apply(
        lambda value: status_label(value) if value else "None"
    )
    return frame


def _evidence_details(row: pd.Series) -> str:
    entity_type = row.get("entity_type")
    code = row.get("shipment_code") or ""
    if entity_type == "incident":
        parts = [code, str(row.get("incident_type") or ""), str(row.get("severity") or "")]
        return " · ".join(part for part in parts if part)
    if entity_type == "return":
        reason = reason_label(row.get("return_declared_reason"))
        outcome = inspection_label(row.get("return_inspection_outcome"))
        cond = row.get("return_condition")
        suffix = f" ({condition_label(cond)})" if cond else ""
        return " · ".join(part for part in [code, reason, outcome + suffix] if part)
    if entity_type == "event":
        event_code = str(row.get("event_code") or "")
        stage = str(row.get("event_stage") or "")
        return " · ".join(part for part in [code, event_code, stage] if part)
    return code


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
                "Numerator": (
                    f"{int(alert['observed_numerator']):,}"
                    if alert["observed_numerator"] is not None
                    else "—"
                ),
                "Denominator": (
                    f"{int(alert['observed_denominator']):,}"
                    if alert["observed_denominator"] is not None
                    else "—"
                ),
                "Rate": format_pct(observed_rate),
            },
            {
                "Window": "Baseline",
                "Start": format_datetime(alert["baseline_start"]),
                "End": format_datetime(alert["baseline_end"]),
                "Numerator": "—",
                "Denominator": "—",
                "Rate": format_pct(baseline_rate),
            },
        ]
    )
    st.dataframe(counts, hide_index=True, width="stretch")
    st.caption(
        "Observed and baseline windows are shown together. The explanation includes the "
        "underlying baseline numerator and denominator; this UI never implies causation."
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
        evidence_frame["details"] = evidence_frame.apply(_evidence_details, axis=1)
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
                key=f"alert_evidence_shipment_{alert_id}",
            )
            if st.button(
                "Open in Shipment Explorer →",
                key=f"alert_open_shipment_{alert_id}",
            ):
                navigate_to("shipments", nav_shipment_id=selected_shipment)
            with st.expander("Shipment timeline and incidents", expanded=False):
                render_shipment_block(database, selected_shipment)

    st.divider()
    if alert["investigation_id"]:
        st.info(
            f"Investigation `{alert['investigation_id']}` is "
            f"{status_label(alert['investigation_status'])}."
        )
        if st.button(
            "Open investigation in Workspace →",
            type="primary",
            key=f"alert_open_investigation_{alert_id}",
        ):
            navigate_to("investigations", nav_investigation_id=alert["investigation_id"])
    elif alert["status"] in {"new", "acknowledged", "investigating"}:
        action_cols = st.columns(3)
        with action_cols[0]:
            if st.button(
                "Create investigation",
                type="primary",
                key=f"alert_create_inv_{alert_id}",
            ):
                try:
                    with loading("Creating investigation..."):
                        investigation_id = repository.create_investigation(
                            cache.engine(database),
                            alert_id,
                        )
                except (ValueError, SQLAlchemyError) as exc:
                    st.error(f"Could not create investigation: {exc}")
                else:
                    cache.clear_data_cache()
                    set_flash(f"Investigation {investigation_id} created from alert {alert_id}.")
                    navigate_to("investigations", nav_investigation_id=investigation_id)
        with action_cols[1]:
            if alert["status"] == "new" and st.button(
                "Acknowledge alert",
                key=f"alert_ack_{alert_id}",
            ):
                try:
                    with loading("Updating alert status..."):
                        repository.update_alert_status(
                            cache.engine(database),
                            alert_id,
                            status="acknowledged",
                        )
                except (ValueError, SQLAlchemyError) as exc:
                    st.error(f"Could not acknowledge alert: {exc}")
                else:
                    cache.clear_data_cache()
                    set_flash(f"Alert {str(alert_id)[:8]} acknowledged.")
                    st.rerun()
        with action_cols[2]:
            if st.button("Dismiss alert", key=f"alert_dismiss_{alert_id}"):
                try:
                    with loading("Dismissing alert..."):
                        repository.update_alert_status(
                            cache.engine(database),
                            alert_id,
                            status="dismissed",
                        )
                except (ValueError, SQLAlchemyError) as exc:
                    st.error(f"Could not dismiss alert: {exc}")
                else:
                    cache.clear_data_cache()
                    set_flash(f"Alert {str(alert_id)[:8]} dismissed.")
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
    range_key = f"alert_generated_range_{database}"
    select_key = f"alert_selected_{database}"

    nav_alert_id = st.session_state.pop("nav_alert_id", None)
    nav_alert = None
    if nav_alert_id is not None:
        try:
            nav_alert_uuid = UUID(str(nav_alert_id))
        except (TypeError, ValueError):
            st.error(f"Alert `{nav_alert_id}` is not a valid alert identifier.")
            return
        try:
            with loading("Loading requested alert..."):
                nav_alert = cache.get_alert(database, nav_alert_uuid)
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            st.error(f"Could not load alert {nav_alert_uuid}: {exc}")
            return
        if nav_alert is None:
            st.error(f"Alert `{nav_alert_uuid}` was not found in the selected database.")
            return
        st.session_state[select_key] = nav_alert_uuid
        for filter_key in (
            "alert_status_filter",
            "alert_priority_filter",
            "alert_type_filter",
            "alert_search",
            range_key,
        ):
            st.session_state.pop(filter_key, None)

    try:
        with loading("Loading alert filters..."):
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
        search = st.text_input("Search alert ID, scope or explanation", key="alert_search")

    generated_start, generated_end = None, None
    if first_generated is not None and last_generated is not None:
        if range_key not in st.session_state:
            st.session_state[range_key] = (first_generated, last_generated)
        selected_range = st.date_input(
            "Generated date range",
            min_value=first_generated,
            max_value=last_generated,
            key=range_key,
        )
        generated_start, generated_end = normalize_date_range(selected_range)

    try:
        with loading("Loading alerts..."):
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

    if nav_alert is not None and not any(
        row["alert_id"] == nav_alert["alert_id"] for row in alerts
    ):
        alerts.insert(0, nav_alert)

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
                "score_num",
                "observed_rate_pct",
                "baseline_rate_pct",
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
                "score_num": "Score",
                "observed_rate_pct": "Observed rate",
                "baseline_rate_pct": "Baseline rate",
                "investigation_text": "Investigation",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Score": st.column_config.NumberColumn(format="%.2f"),
            "Observed rate": st.column_config.NumberColumn(format="%.2f%%"),
            "Baseline rate": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

    alert_options = [row["alert_id"] for row in alerts]
    if select_key in st.session_state and st.session_state[select_key] not in alert_options:
        if nav_alert is not None:
            st.error(f"Alert `{nav_alert['alert_id']}` could not be loaded into the alert list.")
            return
        st.session_state[select_key] = alert_options[0]

    selected_alert = st.selectbox(
        "Open alert detail",
        options=alert_options,
        format_func=lambda value: next(
            (
                f"{row['alert_short']} · {row['type_text']} · {row['scope_name'] or ''}"
                for row in frame.to_dict("records")
                if row["alert_id"] == value
            ),
            str(value),
        ),
        key=select_key,
    )
    st.divider()
    _render_alert_detail(database, selected_alert)
