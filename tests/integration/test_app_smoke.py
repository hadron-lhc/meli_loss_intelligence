import base64
import json
import sys
from array import array as typed_array
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import streamlit as st
from sqlalchemy import text
from streamlit.testing.v1 import AppTest

from loss_intelligence.app import repository
from loss_intelligence.app.formatting import (
    format_int,
    format_pct,
    inspection_label,
    reason_label,
)
from tests.integration.helpers import (
    BASE_TIME,
    create_alert,
    create_detection_run,
    create_event,
    create_incident,
    create_investigation,
    create_scenario,
    create_shipment,
    seed_reference_data,
)

pytestmark = pytest.mark.integration

APP_PATH = str(Path(__file__).resolve().parents[2] / "src/loss_intelligence/app/streamlit_app.py")
VIEW_MODULES = (
    "overview",
    "hotspots",
    "alerts",
    "shipments",
    "investigations",
    "returns",
    "evaluation",
)


def _clear_streamlit_caches() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def _page_runner(view_name: str) -> AppTest:
    script = f"""
import streamlit as st
from loss_intelligence.app.components import render_disclaimer, render_sidebar
from loss_intelligence.app.views import {view_name}

render_disclaimer()
render_sidebar()
{view_name}.render()
"""
    return AppTest.from_string(script, default_timeout=15)


def _metrics_by_label(at: AppTest) -> dict[str, object]:
    return {metric.label: metric for metric in at.metric}


_PLOTLY_TYPECODES = {
    "i1": "b",
    "u1": "B",
    "i2": "h",
    "u2": "H",
    "i4": "i",
    "u4": "I",
    "i8": "q",
    "u8": "Q",
    "f4": "f",
    "f8": "d",
}


def _decode_plotly_arrays(value):
    if isinstance(value, list):
        return [_decode_plotly_arrays(item) for item in value]
    if not isinstance(value, dict):
        return value
    type_code = _PLOTLY_TYPECODES.get(value.get("dtype"))
    if isinstance(value.get("bdata"), str) and type_code is not None:
        decoded = typed_array(type_code)
        decoded.frombytes(base64.b64decode(value["bdata"]))
        if sys.byteorder != "little":
            decoded.byteswap()
        return decoded.tolist()
    return {key: _decode_plotly_arrays(item) for key, item in value.items()}


def _plotly_figures(at: AppTest) -> list[dict]:
    return [_decode_plotly_arrays(json.loads(chart.proto.spec)) for chart in at.get("plotly_chart")]


def _trace_by_name(figures: list[dict], name: str) -> dict:
    for figure in figures:
        for trace in figure.get("data", []):
            if trace.get("name") == name:
                return trace
    raise AssertionError(f"plotly trace {name!r} was not rendered")


def _bar_trace(figures: list[dict], *, orientation: str) -> dict:
    for figure in figures:
        for trace in figure.get("data", []):
            if trace.get("type") == "bar" and trace.get("orientation", "v") == orientation:
                return trace
    raise AssertionError(f"{orientation!r} bar chart was not rendered")


def _create_return(
    engine,
    shipment_id,
    *,
    declared_reason: str,
    inspection_outcome: str,
    initiated_at=None,
):
    initiated = initiated_at or (BASE_TIME + timedelta(days=1))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO returns (
                    return_id, shipment_id, initiated_at, received_at,
                    declared_reason, inspection_outcome, return_status, condition_on_return
                ) VALUES (
                    :return_id, :shipment_id, :initiated_at, :received_at,
                    :declared_reason, :inspection_outcome, 'inspected', 'damaged'
                )
                """
            ),
            {
                "return_id": uuid4(),
                "shipment_id": shipment_id,
                "initiated_at": initiated,
                "received_at": initiated + timedelta(days=1),
                "declared_reason": declared_reason,
                "inspection_outcome": inspection_outcome,
            },
        )


def test_entrypoint_and_all_pages_render_empty_database(db) -> None:
    _clear_streamlit_caches()
    entry = AppTest.from_file(APP_PATH, default_timeout=15)
    entry.session_state["db_target"] = "test"
    entry.run()
    assert not entry.exception
    assert any("Synthetic data" in warning.value for warning in entry.warning)

    for view_name in VIEW_MODULES:
        at = _page_runner(view_name)
        at.session_state["db_target"] = "test"
        at.run()
        assert not at.exception, f"unexpected exception on empty view {view_name}: {at.exception}"
        assert any("Synthetic data" in warning.value for warning in at.warning)


def test_zero_denominator_rates_render_empty_states(db) -> None:
    start_date, end_date = date(2026, 1, 1), date(2026, 1, 2)
    overview = repository.overview(db, start_date, end_date, minimum_volume=30)
    assert overview["eligible_shipments"] == 0
    assert overview["damage"]["denominator"] == 0
    assert overview["damage"]["rate"] is None

    summary = repository.returns_summary(db, start_date, end_date)
    assert summary["totals"]["eligible_shipments"] == 0
    assert summary["totals"]["inspected_returns"] == 0

    _clear_streamlit_caches()
    for view_name, metric_labels in (
        ("overview", ("Damage rate",)),
        ("returns", ("Return rate", "Inspection discrepancy rate")),
    ):
        at = _page_runner(view_name)
        at.session_state["db_target"] = "test"
        at.session_state["date_range_test"] = (start_date, end_date)
        at.run()
        assert not at.exception, f"unexpected exception on empty {view_name}: {at.exception}"
        assert set(_metrics_by_label(at)).isdisjoint(metric_labels)
        assert any("No eligible shipments" in info.value for info in at.info)


def test_all_pages_and_drilldowns_render_seeded_data(db) -> None:
    reference = seed_reference_data(db)
    shipment_id = create_shipment(
        db,
        reference,
        delivered_at=BASE_TIME + timedelta(hours=4),
        shipment_status="delivered",
        is_test_record=False,
    )
    later_time = BASE_TIME + timedelta(days=20)
    returned_id = create_shipment(
        db,
        reference,
        created_at=later_time,
        delivered_at=later_time + timedelta(hours=5),
        shipment_status="returned",
        is_test_record=False,
    )
    event_id = create_event(db, reference, shipment_id)
    create_incident(db, shipment_id, related_event_id=event_id)
    with db.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO returns (
                    return_id, shipment_id, initiated_at, received_at,
                    declared_reason, inspection_outcome, return_status, condition_on_return
                ) VALUES (
                    :return_id, :shipment_id, :initiated_at, :received_at,
                    'damaged', 'does_not_match_declaration', 'inspected', 'used'
                )
                """
            ),
            {
                "return_id": uuid4(),
                "shipment_id": returned_id,
                "initiated_at": later_time + timedelta(days=1),
                "received_at": later_time + timedelta(days=2),
            },
        )
    run_id = create_detection_run(db)
    alert_id = create_alert(
        db,
        scope_type="facility",
        scope_id=str(reference.facility_id),
        detection_run_id=run_id,
    )
    inv_id = create_investigation(db, alert_id=alert_id)
    create_scenario(
        db,
        split="validation",
        start_at=BASE_TIME,
        end_at=BASE_TIME + timedelta(days=2),
        affected_entity_id=str(reference.facility_id),
    )

    _clear_streamlit_caches()
    for view_name in VIEW_MODULES:
        at = _page_runner(view_name)
        at.session_state["db_target"] = "test"
        if view_name == "hotspots":
            at.session_state["hotspot_scope_type"] = "carrier_zone"
            at.session_state["hotspot_compare"] = True
        elif view_name == "alerts":
            at.session_state["nav_alert_id"] = alert_id
        elif view_name == "shipments":
            at.session_state["nav_shipment_id"] = returned_id
        elif view_name == "investigations":
            at.session_state["nav_investigation_id"] = inv_id
        at.run()
        assert not at.exception, f"unexpected exception on seeded view {view_name}: {at.exception}"


def test_alert_navigation_loads_alert_outside_first_page(db) -> None:
    reference = seed_reference_data(db)
    target_alert_id = create_alert(
        db,
        scope_type="facility",
        scope_id=str(reference.facility_id),
        observed_start=BASE_TIME - timedelta(days=2),
        observed_end=BASE_TIME - timedelta(days=1),
    )
    for offset in range(250):
        create_alert(
            db,
            scope_type="facility",
            scope_id=str(reference.facility_id),
            observed_start=BASE_TIME + timedelta(days=offset),
            observed_end=BASE_TIME + timedelta(days=offset + 1),
        )

    _clear_streamlit_caches()
    at = _page_runner("alerts")
    at.session_state["db_target"] = "test"
    at.session_state["nav_alert_id"] = target_alert_id
    at.run()

    assert not at.exception
    assert any(selectbox.value == target_alert_id for selectbox in at.selectbox)
    assert any(str(target_alert_id) in caption.value for caption in at.caption)


def test_alert_navigation_missing_alert_shows_explicit_error(db) -> None:
    reference = seed_reference_data(db)
    unrelated_alert_id = create_alert(
        db,
        scope_type="facility",
        scope_id=str(reference.facility_id),
    )

    _clear_streamlit_caches()
    missing_alert_id = uuid4()
    at = _page_runner("alerts")
    at.session_state["db_target"] = "test"
    at.session_state["nav_alert_id"] = missing_alert_id
    at.run()

    assert not at.exception
    assert any("not found" in error.value.lower() for error in at.error)
    assert not any(selectbox.value == missing_alert_id for selectbox in at.selectbox)
    assert not any(selectbox.value == unrelated_alert_id for selectbox in at.selectbox)


def test_overview_metrics_and_chart_data_match_analytics(db) -> None:
    reference = seed_reference_data(db)
    start_date, end_date = date(2026, 1, 1), date(2026, 1, 2)
    damaged_ids = []
    for offset, damaged in ((0, True), (0, False), (1, True), (1, False)):
        created_at = BASE_TIME + timedelta(days=offset)
        shipment_id = create_shipment(
            db,
            reference,
            created_at=created_at,
            delivered_at=created_at + timedelta(hours=4),
            shipment_status="delivered",
            is_test_record=False,
        )
        if damaged:
            damaged_ids.append(shipment_id)
            create_incident(db, shipment_id, confirmed_at=created_at + timedelta(hours=2))
    create_incident(db, damaged_ids[0], confirmed_at=BASE_TIME + timedelta(hours=3))

    expected = repository.overview(
        db,
        start_date,
        end_date,
        minimum_volume=30,
        confidence=0.95,
        maturity_days=14,
    )
    expected_daily = repository.daily_metrics(
        db,
        start_date,
        end_date,
        minimum_volume=30,
        confidence=0.95,
    )
    assert expected["eligible_shipments"] == 4
    assert expected["confirmed_damage_incidents"] == 3
    assert expected["damage"]["numerator"] == 2
    assert expected["damage"]["denominator"] == 4

    _clear_streamlit_caches()
    at = _page_runner("overview")
    at.session_state["db_target"] = "test"
    at.session_state["date_range_test"] = (start_date, end_date)
    at.run()

    assert not at.exception
    metrics = _metrics_by_label(at)
    damage_metric = metrics["Damage rate"]
    assert damage_metric.value == format_pct(expected["damage"]["rate"])
    assert format_int(expected["damage"]["numerator"]) in damage_metric.help
    assert format_int(expected["damage"]["denominator"]) in damage_metric.help
    assert metrics["Processed shipments"].value == format_int(expected["eligible_shipments"])
    assert metrics["Confirmed damage incidents"].value == format_int(
        expected["confirmed_damage_incidents"]
    )

    figures = _plotly_figures(at)
    rate_trace = _trace_by_name(figures, "Damage rate")
    volume_trace = _trace_by_name(figures, "Eligible shipments")
    assert rate_trace["y"] == pytest.approx([row["damage"]["rate"] for row in expected_daily])
    assert volume_trace["y"] == [row["eligible_shipments"] for row in expected_daily]


def test_returns_metrics_and_chart_data_match_summary(db) -> None:
    reference = seed_reference_data(db)
    start_date, end_date = date(2026, 1, 1), date(2026, 1, 4)
    shipment_ids = []
    for offset in range(4):
        created_at = BASE_TIME + timedelta(days=offset)
        shipment_ids.append(
            create_shipment(
                db,
                reference,
                created_at=created_at,
                delivered_at=created_at + timedelta(hours=4),
                shipment_status="returned" if offset < 3 else "delivered",
                is_test_record=False,
            )
        )
    _create_return(
        db,
        shipment_ids[0],
        declared_reason="damaged",
        inspection_outcome="does_not_match_declaration",
    )
    _create_return(
        db,
        shipment_ids[1],
        declared_reason="wrong_item",
        inspection_outcome="matches_declaration",
    )
    _create_return(
        db,
        shipment_ids[2],
        declared_reason="other",
        inspection_outcome="not_inspected",
    )

    summary = repository.returns_summary(db, start_date, end_date)
    totals = summary["totals"]
    assert totals["eligible_shipments"] == 4
    assert totals["shipments_with_return"] == 3
    assert totals["inspected_returns"] == 2
    assert totals["discrepancy_returns"] == 1
    expected_return_rate = 3 / 4
    expected_discrepancy_rate = 1 / 2

    _clear_streamlit_caches()
    at = _page_runner("returns")
    at.session_state["db_target"] = "test"
    at.session_state["date_range_test"] = (start_date, end_date)
    at.run()

    assert not at.exception
    metrics = _metrics_by_label(at)
    return_rate_metric = metrics["Return rate"]
    assert return_rate_metric.value == format_pct(expected_return_rate)
    assert format_int(totals["shipments_with_return"]) in return_rate_metric.help
    assert format_int(totals["eligible_shipments"]) in return_rate_metric.help
    discrepancy_metric = metrics["Inspection discrepancy rate"]
    assert discrepancy_metric.value == format_pct(expected_discrepancy_rate)
    assert format_int(totals["discrepancy_returns"]) in discrepancy_metric.help
    assert format_int(totals["inspected_returns"]) in discrepancy_metric.help

    figures = _plotly_figures(at)
    expected_reasons = sorted(summary["by_reason"], key=lambda row: row["return_count"])
    reason_trace = _bar_trace(figures, orientation="h")
    assert reason_trace["x"] == [row["return_count"] for row in expected_reasons]
    assert reason_trace["y"] == [reason_label(row["declared_reason"]) for row in expected_reasons]
    inspection_trace = _bar_trace(figures, orientation="v")
    assert inspection_trace["x"] == [
        inspection_label(row["inspection_outcome"]) for row in summary["by_inspection"]
    ]
    assert inspection_trace["y"] == [row["return_count"] for row in summary["by_inspection"]]
    trend_trace = _trace_by_name(figures, "Returns")
    assert trend_trace["y"] == [row["return_count"] for row in summary["daily"]]


def test_returns_discrepancy_rate_with_zero_inspections(db) -> None:
    reference = seed_reference_data(db)
    start_date, end_date = date(2026, 1, 1), date(2026, 1, 2)
    shipment_ids = []
    for offset in range(2):
        created_at = BASE_TIME + timedelta(days=offset)
        shipment_ids.append(
            create_shipment(
                db,
                reference,
                created_at=created_at,
                delivered_at=created_at + timedelta(hours=4),
                shipment_status="returned" if offset == 0 else "delivered",
                is_test_record=False,
            )
        )
    _create_return(
        db,
        shipment_ids[0],
        declared_reason="changed_mind",
        inspection_outcome="not_inspected",
    )

    summary = repository.returns_summary(db, start_date, end_date)
    totals = summary["totals"]
    assert totals["eligible_shipments"] == 2
    assert totals["shipments_with_return"] == 1
    assert totals["inspected_returns"] == 0
    assert totals["discrepancy_returns"] == 0

    _clear_streamlit_caches()
    at = _page_runner("returns")
    at.session_state["db_target"] = "test"
    at.session_state["date_range_test"] = (start_date, end_date)
    at.run()

    assert not at.exception
    metrics = _metrics_by_label(at)
    assert metrics["Return rate"].value == format_pct(1 / 2)
    discrepancy_metric = metrics["Inspection discrepancy rate"]
    assert discrepancy_metric.value == "—"
    assert format_int(0) in discrepancy_metric.help
    assert "inspected" in discrepancy_metric.help
