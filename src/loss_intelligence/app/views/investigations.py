"""Investigation Workspace page."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from loss_intelligence.app import cache, repository
from loss_intelligence.app.components import (
    current_database,
    empty_state,
    loading,
    navigate_to,
    page_header,
    set_flash,
    show_flash,
)
from loss_intelligence.app.formatting import (
    alert_type_label,
    format_datetime,
    format_pct,
    outcome_label,
    priority_label,
    scope_label,
    status_label,
)


def _render_create_section(database: str) -> None:
    st.subheader("Create an investigation from an alert")
    try:
        candidates = cache.alerts_without_active_investigation(database)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load candidate alerts: {exc}")
        return
    if not candidates:
        st.caption("Every open alert already has an active investigation.")
        return

    selected = st.selectbox(
        "Alert",
        options=[row["alert_id"] for row in candidates],
        format_func=lambda value: next(
            (
                f"{row['alert_type']} · {scope_label(row['scope_type'])} "
                f"{row['scope_name'] or ''} · {priority_label(row['priority'])}"
                for row in candidates
                if row["alert_id"] == value
            ),
            str(value),
        ),
    )
    if st.button("Create investigation", type="primary"):
        try:
            with loading("Creating investigation..."):
                investigation_id = repository.create_investigation(
                    cache.engine(database),
                    selected,
                )
        except (ValueError, SQLAlchemyError) as exc:
            st.error(f"Could not create investigation: {exc}")
        else:
            cache.clear_data_cache()
            st.session_state[f"investigation_selected_{database}"] = investigation_id
            set_flash(f"Investigation {investigation_id} created.")
            st.rerun()


def _render_detail(database: str, investigation_id) -> None:
    detail = cache.investigation_detail(database, investigation_id)
    if detail is None:
        empty_state("Investigation not found.")
        return

    st.subheader(f"Investigation {str(investigation_id)[:8]}")
    if detail.get("alert_id"):
        st.caption(
            f"Alert `{detail['alert_id']}` · {alert_type_label(detail['alert_type'])} · "
            f"{scope_label(detail['scope_type'])} {detail['scope_name'] or ''} · "
            f"priority {priority_label(detail['alert_priority'])}"
        )
        if detail.get("explanation"):
            st.info(detail["explanation"])
        first, second, third = st.columns(3)
        first.metric(
            "Observed rate",
            format_pct(
                float(detail["observed_rate"]) if detail.get("observed_rate") is not None else None
            ),
        )
        second.metric(
            "Baseline rate",
            format_pct(
                float(detail["baseline_rate"]) if detail.get("baseline_rate") is not None else None
            ),
        )
        third.metric(
            "Observed count",
            f"{detail.get('observed_numerator') or 0:,} / "
            f"{detail.get('observed_denominator') or 0:,}",
        )
        if st.button(
            "Open source alert in Alerts & Anomalies →",
            key=f"inv_open_alert_{investigation_id}",
        ):
            navigate_to("alerts", nav_alert_id=detail["alert_id"])
    else:
        st.caption(f"Incident-linked investigation `{detail.get('incident_id')}`.")

    st.markdown(
        "**Reviewer identity:** `demo_reviewer (synthetic)` — this is a demonstration "
        "identity, not a real employee."
    )

    status_options = list(repository.INVESTIGATION_STATUSES)
    outcome_options = [None, *repository.INVESTIGATION_OUTCOMES]
    status_index = (
        status_options.index(detail["status"]) if detail["status"] in status_options else 0
    )
    outcome_index = (
        outcome_options.index(detail["outcome"]) if detail.get("outcome") in outcome_options else 0
    )

    with st.form(f"investigation_form_{investigation_id}"):
        status = st.selectbox(
            "Status",
            options=status_options,
            index=status_index,
            format_func=status_label,
        )
        outcome = st.selectbox(
            "Outcome",
            options=outcome_options,
            index=outcome_index,
            format_func=lambda value: "—" if value is None else outcome_label(value),
            help="Closed and dismissed investigations require an outcome.",
        )
        notes = st.text_area(
            "Notes",
            value=detail.get("notes") or "",
            placeholder="What did the reviewer observe?",
        )
        recommended_action = st.text_area(
            "Recommended action",
            value=detail.get("recommended_action") or "",
            placeholder="Follow-up action for the operations team.",
        )
        st.text_input("Reviewer", value=repository.DEMO_REVIEWER, disabled=True)
        submitted = st.form_submit_button("Save investigation", type="primary")

    if submitted:
        try:
            with loading("Saving investigation..."):
                repository.update_investigation(
                    cache.engine(database),
                    investigation_id,
                    status=status,
                    outcome=outcome,
                    notes=notes or None,
                    recommended_action=recommended_action or None,
                    reviewer_label=repository.DEMO_REVIEWER,
                )
        except (ValueError, SQLAlchemyError) as exc:
            st.error(f"Could not save investigation: {exc}")
        else:
            cache.clear_data_cache()
            set_flash("Investigation updated and audit trail recorded.")
            st.rerun()

    st.markdown("**Audit trail**")
    audit = cache.investigation_audit(database, investigation_id)
    if not audit:
        st.caption("No audit entries yet.")
    else:
        audit_frame = pd.DataFrame(audit)
        audit_frame["changed_at_text"] = audit_frame["changed_at"].apply(format_datetime)
        audit_frame["from_status_text"] = audit_frame["from_status"].apply(
            lambda value: status_label(value) if value else "—"
        )
        audit_frame["to_status_text"] = audit_frame["to_status"].apply(status_label)
        audit_frame["outcome_text"] = audit_frame["outcome"].apply(
            lambda value: outcome_label(value) if value else "—"
        )
        st.dataframe(
            audit_frame[
                [
                    "changed_at_text",
                    "changed_by",
                    "from_status_text",
                    "to_status_text",
                    "outcome_text",
                    "note",
                ]
            ].rename(
                columns={
                    "changed_at_text": "Changed at",
                    "changed_by": "Changed by",
                    "from_status_text": "From",
                    "to_status_text": "To",
                    "outcome_text": "Outcome",
                    "note": "Note",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "The audit trail is append-only and is written by database triggers whenever "
            "status or outcome changes."
        )


def render() -> None:
    page_header(
        "Investigation Workspace",
        "Create investigations from alerts, record decisions and follow-up actions, and "
        "review the audit trail.",
    )
    show_flash()
    database = current_database()
    select_key = f"investigation_selected_{database}"

    nav_investigation_id = st.session_state.pop("nav_investigation_id", None)
    if nav_investigation_id is not None:
        st.session_state[select_key] = nav_investigation_id
        st.session_state.pop("investigation_status_filter", None)
        st.session_state.pop("investigation_outcome_filter", None)

    _render_create_section(database)
    st.divider()

    status_filter, outcome_filter = st.columns(2)
    with status_filter:
        statuses = st.multiselect(
            "Filter by status",
            options=repository.INVESTIGATION_STATUSES,
            format_func=status_label,
            key="investigation_status_filter",
        )
    with outcome_filter:
        outcomes = st.multiselect(
            "Filter by outcome",
            options=list(repository.INVESTIGATION_OUTCOMES),
            format_func=outcome_label,
            key="investigation_outcome_filter",
        )

    try:
        with loading("Loading investigations..."):
            investigations = cache.list_investigations(
                database,
                tuple(statuses) or None,
                tuple(outcomes) or None,
            )
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load investigations: {exc}")
        return

    if not investigations:
        empty_state("No investigations match the current filters.")
        return

    frame = pd.DataFrame(investigations)
    frame["investigation_short"] = frame["investigation_id"].astype(str).str.slice(0, 8)
    frame["status_text"] = frame["status"].apply(status_label)
    frame["outcome_text"] = frame["outcome"].apply(
        lambda value: outcome_label(value) if value else "—"
    )
    frame["opened_text"] = frame["opened_at"].apply(format_datetime)
    frame["updated_text"] = frame["updated_at"].apply(format_datetime)
    frame["alert_type_text"] = frame["alert_type"].apply(
        lambda value: alert_type_label(value) if value else "—"
    )
    frame["scope_text"] = frame["scope_type"].apply(
        lambda value: scope_label(value) if value else "—"
    )
    st.dataframe(
        frame[
            [
                "investigation_short",
                "status_text",
                "outcome_text",
                "alert_type_text",
                "scope_text",
                "scope_name",
                "alert_priority",
                "reviewer_label",
                "opened_text",
                "updated_text",
            ]
        ].rename(
            columns={
                "investigation_short": "Investigation",
                "status_text": "Status",
                "outcome_text": "Outcome",
                "alert_type_text": "Alert type",
                "scope_text": "Scope",
                "scope_name": "Entity",
                "alert_priority": "Alert priority",
                "reviewer_label": "Reviewer",
                "opened_text": "Opened",
                "updated_text": "Updated",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    inv_options = [row["investigation_id"] for row in investigations]
    if select_key in st.session_state and st.session_state[select_key] not in inv_options:
        st.session_state[select_key] = inv_options[0]

    selected = st.selectbox(
        "Open investigation",
        options=inv_options,
        format_func=lambda value: next(
            (
                f"{row['investigation_short']} · {row['status_text']} · "
                f"{row['scope_name'] or row['alert_type_text']}"
                for row in frame.to_dict("records")
                if row["investigation_id"] == value
            ),
            str(value),
        ),
        key=select_key,
    )
    st.divider()
    _render_detail(database, selected)
