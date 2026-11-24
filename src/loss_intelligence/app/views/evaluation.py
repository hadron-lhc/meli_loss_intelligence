"""Model & Evaluation page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from loss_intelligence.app import cache
from loss_intelligence.app.components import (
    current_database,
    empty_state,
    page_header,
)
from loss_intelligence.app.formatting import (
    format_datetime,
    format_int,
    format_pct,
    humanize,
)


def _render_metrics(summary: dict) -> None:
    first, second, third, fourth = st.columns(4)
    first.metric(
        "Recall",
        format_pct(summary["recall"]),
        help=(
            f"{summary['detected_scenarios']} of {summary['expected_scenarios']} expected "
            "validation scenarios detected."
        ),
    )
    second.metric(
        "False-positive rate",
        format_pct(summary["false_positive_rate"]),
        help=(
            f"{summary['false_positive_scenarios']} of {summary['negative_scenarios']} "
            "negative-control scenarios produced a matching alert."
        ),
    )
    third.metric(
        "False-discovery proportion",
        format_pct(summary["false_discovery_proportion"]),
        help=(
            f"{summary['false_alerts']} of {summary['total_alerts']} alerts were not "
            "matched to an expected scenario."
        ),
    )
    fourth.metric(
        f"Precision@{summary['k']}",
        format_pct(summary["precision_at_k"]),
        help=(
            f"Top {summary['k']} alerts; {summary['k_effective']} effective when fewer "
            "alerts exist."
        ),
    )


def _render_scenarios(summary: dict) -> None:
    st.subheader("Validation scenarios")
    scenarios = summary["scenarios"]
    if not scenarios:
        empty_state("No validation scenarios are available for this run.")
        return
    frame = pd.DataFrame(scenarios)
    frame["detected_text"] = frame["detected"].map({True: "Detected", False: "Missed"})
    frame["scope_text"] = frame["expected_scope_type"].apply(humanize)
    st.dataframe(
        frame[
            [
                "scenario_code",
                "scenario_type",
                "scope_text",
                "expected_scope_id",
                "expected_alert_type",
                "detected_text",
                "alert_count",
                "matching_alert_count",
            ]
        ].rename(
            columns={
                "scenario_code": "Scenario",
                "scenario_type": "Type",
                "scope_text": "Scope",
                "expected_scope_id": "Expected entity",
                "expected_alert_type": "Expected alert",
                "detected_text": "Outcome",
                "alert_count": "Overlapping alerts",
                "matching_alert_count": "Matching alerts",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Scenario truth describes how the synthetic data was constructed. It is not "
        "evidence of real-world detection performance."
    )


def _render_model_comparison(summary: dict) -> None:
    st.subheader("Model comparison")
    baseline, isolation_forest = st.columns(2)
    with baseline:
        st.markdown("**Statistical baseline / rules**")
        st.metric("Recall", format_pct(summary["recall"]))
        st.metric("Precision@K", format_pct(summary["precision_at_k"]))
        st.metric(
            "False-discovery proportion",
            format_pct(summary["false_discovery_proportion"]),
        )
        st.caption(
            "Transparent two-proportion z-test with Benjamini-Hochberg FDR control, "
            "minimum-volume rules and relative-lift thresholds."
        )
    with isolation_forest:
        st.markdown("**Isolation Forest**")
        st.warning(
            "Not implemented. It is deferred pending a fair, reproducible comparison with "
            "the statistical baseline.",
            icon="⏸️",
        )
        st.caption(
            "No incremental-value claim is made. The dashboard will show Isolation Forest "
            "metrics only after it is trained and evaluated on the same held-out scenarios."
        )

    st.caption(
        "Detection delay is not defined in the current evaluation output. "
        "Synthetic performance does not establish real-world performance."
    )


def render() -> None:
    page_header(
        "Model & Evaluation",
        "Compare the statistical baseline with the deferred Isolation Forest and review "
        "held-out synthetic scenario results.",
    )
    st.warning(
        "Synthetic evaluation metrics do not establish real-world detection performance. "
        "They describe how the detector behaves on constructed scenarios only.",
        icon="⚠️",
    )
    database = current_database()

    try:
        runs = cache.detection_runs(database)
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not load detection runs: {exc}")
        return

    if not runs:
        empty_state(
            "No detection runs are available. Run `make detect-validation` or `make detect` "
            "before opening this page."
        )
        return

    frame = pd.DataFrame(runs)
    frame["started_text"] = frame["started_at"].apply(format_datetime)
    frame["completed_text"] = frame["completed_at"].apply(format_datetime)
    frame["model_text"] = frame["model_name"] + " " + frame["model_version"]
    st.dataframe(
        frame[
            [
                "detection_run_id",
                "model_text",
                "status",
                "alert_count",
                "started_text",
                "completed_text",
                "config_hash",
            ]
        ].rename(
            columns={
                "detection_run_id": "Run",
                "model_text": "Model",
                "status": "Status",
                "alert_count": "Alerts",
                "started_text": "Started",
                "completed_text": "Completed",
                "config_hash": "Config hash",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    selected_run = st.selectbox(
        "Detection run",
        options=[row["detection_run_id"] for row in runs],
        format_func=lambda value: next(
            (
                f"{str(row['detection_run_id'])[:8]} · {row['model_text']} · "
                f"{row['status']} · {format_int(row['alert_count'])} alerts"
                for row in frame.to_dict("records")
                if row["detection_run_id"] == value
            ),
            str(value),
        ),
    )
    k = st.number_input("K for precision@K", min_value=1, max_value=100, value=10, step=1)

    try:
        summary = cache.evaluation_summary(database, selected_run, int(k))
    except ValueError as exc:
        empty_state(f"Evaluation is not available for this run: {exc}")
        return
    except Exception as exc:  # pragma: no cover - surfaced in the UI
        st.error(f"Could not evaluate this run: {exc}")
        return

    st.caption(
        f"Run {selected_run} · split {summary['split']} · "
        f"{summary['expected_scenarios']} expected scenarios · "
        f"{summary['negative_scenarios']} negative controls."
    )
    _render_metrics(summary)
    st.divider()
    _render_scenarios(summary)
    st.divider()
    _render_model_comparison(summary)

    selected = next(row for row in runs if row["detection_run_id"] == selected_run)
    with st.expander("Detection run configuration"):
        st.code(json.dumps(selected["config"], indent=2, default=str), language="json")
        st.caption(f"Config hash: `{selected['config_hash']}`")
