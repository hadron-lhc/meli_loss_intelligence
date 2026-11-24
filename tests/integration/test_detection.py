from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from loss_intelligence.detection.config import DetectionConfig
from loss_intelligence.detection.detector import detect
from loss_intelligence.detection.evaluation import (
    clean_baseline_span,
    detect_and_evaluate_validation,
    evaluate_validation,
    validation_span,
)
from tests.integration.helpers import (
    BASE_TIME,
    create_alert,
    create_detection_run,
    create_event,
    create_incident,
    create_scenario,
    create_shipment,
    seed_reference_data,
)

pytestmark = pytest.mark.integration

OBSERVED_START = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
OBSERVED_END = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
BASELINE_TIME = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
OBSERVED_TIME = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)


def _detection_config(**overrides) -> DetectionConfig:
    values = {
        "min_observed_denominator": 10,
        "min_baseline_denominator": 10,
        "min_observed_numerator": 2,
        "min_relative_lift": 1.5,
        "min_zero_baseline_rate": 0.25,
        "max_evidence": 3,
    }
    values.update(overrides)
    return DetectionConfig(**values)


def _seed_damage_cohort(engine, reference) -> None:
    for index in range(20):
        shipment_id = create_shipment(
            engine,
            reference,
            created_at=BASELINE_TIME + timedelta(hours=index),
            delivered_at=BASELINE_TIME + timedelta(hours=index, days=1),
            shipment_status="delivered",
            is_test_record=False,
        )
        event_id = create_event(
            engine,
            reference,
            shipment_id,
            occurred_at=BASELINE_TIME + timedelta(hours=index),
        )
        if index == 0:
            create_incident(
                engine,
                shipment_id,
                related_event_id=event_id,
                reported_at=BASELINE_TIME + timedelta(hours=index, days=1),
                confirmed_at=BASELINE_TIME + timedelta(days=1, hours=index + 2),
            )

    for index in range(20):
        shipment_id = create_shipment(
            engine,
            reference,
            created_at=OBSERVED_TIME + timedelta(hours=index),
            delivered_at=OBSERVED_TIME + timedelta(hours=index, days=1),
            shipment_status="delivered",
            is_test_record=False,
        )
        event_id = create_event(
            engine,
            reference,
            shipment_id,
            occurred_at=OBSERVED_TIME + timedelta(hours=index),
        )
        if index < 8:
            create_incident(
                engine,
                shipment_id,
                related_event_id=event_id,
                reported_at=OBSERVED_TIME + timedelta(hours=index, days=1),
                confirmed_at=OBSERVED_TIME + timedelta(days=1, hours=index + 2),
            )


def test_detection_persists_alert_rates_and_evidence(db) -> None:
    reference = seed_reference_data(db)
    _seed_damage_cohort(db, reference)

    result = detect(
        db,
        _detection_config(),
        observed_start=OBSERVED_START,
        observed_end=OBSERVED_END,
    )

    facility_hits = [
        hit
        for hit in result.hits
        if hit.scope_type == "facility" and hit.scope_id == str(reference.facility_id)
    ]
    assert len(facility_hits) == 1
    hit = facility_hits[0]
    assert hit.observed_numerator == 8
    assert hit.observed_denominator == 20
    assert hit.baseline_numerator == 1
    assert hit.baseline_denominator == 20
    assert hit.observed_rate == pytest.approx(0.4)
    assert hit.baseline_rate == pytest.approx(0.05)
    assert hit.relative_lift == pytest.approx(8.0)
    assert hit.q_value <= 0.05
    assert result.tested_hypotheses >= 1
    assert result.significant_hypotheses >= 1
    assert result.suppressed_hypotheses == result.significant_hypotheses - len(result.hits)
    assert len(hit.evidence) == 3
    assert len({item.entity_id for item in hit.evidence}) == 3

    with db.connect() as connection:
        run = connection.execute(
            text(
                "SELECT status, config_hash FROM meta.detection_runs "
                "WHERE detection_run_id = :run_id"
            ),
            {"run_id": result.detection_run_id},
        ).one()
        alert = connection.execute(
            text(
                """
                SELECT observed_numerator, observed_denominator, baseline_rate,
                       detection_run_id
                FROM anomaly_alerts
                WHERE detection_run_id = :run_id
                  AND scope_type = 'facility'
                  AND scope_id = :scope_id
                  AND alert_type = 'damage_rate_spike'
                """
            ),
            {"run_id": result.detection_run_id, "scope_id": str(reference.facility_id)},
        ).one()
        evidence_count = connection.execute(
            text(
                """
                SELECT count(*) FROM anomaly_alert_evidence e
                JOIN anomaly_alerts a ON a.alert_id = e.alert_id
                WHERE a.detection_run_id = :run_id
                  AND a.scope_type = 'facility'
                  AND a.scope_id = :scope_id
                """
            ),
            {"run_id": result.detection_run_id, "scope_id": str(reference.facility_id)},
        ).scalar_one()

    assert run.status == "completed"
    assert run.config_hash == result.config_hash
    assert alert.observed_numerator == 8
    assert alert.observed_denominator == 20
    assert float(alert.baseline_rate) == pytest.approx(0.05)
    assert alert.detection_run_id == result.detection_run_id
    assert evidence_count == 3


def test_detection_minimum_volume_suppresses_alerts(db) -> None:
    reference = seed_reference_data(db)
    _seed_damage_cohort(db, reference)

    result = detect(
        db,
        _detection_config(min_observed_denominator=21),
        observed_start=OBSERVED_START,
        observed_end=OBSERVED_END,
    )

    assert result.hits == ()
    with db.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM meta.detection_runs WHERE detection_run_id = :run_id"),
            {"run_id": result.detection_run_id},
        ).scalar_one()
        alert_count = connection.execute(
            text("SELECT count(*) FROM anomaly_alerts WHERE detection_run_id = :run_id"),
            {"run_id": result.detection_run_id},
        ).scalar_one()

    assert status == "completed"
    assert alert_count == 0


def test_validation_evaluation_matches_scenario_scope_and_window(db) -> None:
    reference = seed_reference_data(db)
    detection_run_id = create_detection_run(db)
    create_alert(
        db,
        alert_type="damage_rate_spike",
        scope_type="facility",
        scope_id=str(reference.facility_id),
        observed_start=BASE_TIME,
        observed_end=BASE_TIME + timedelta(days=7),
        detection_run_id=detection_run_id,
    )
    create_alert(
        db,
        alert_type="damage_rate_spike",
        scope_type="zone",
        scope_id=str(reference.zone_id),
        observed_start=BASE_TIME,
        observed_end=BASE_TIME + timedelta(days=7),
        detection_run_id=detection_run_id,
    )
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="validation",
        start_at=BASE_TIME,
        end_at=BASE_TIME + timedelta(days=7),
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
    )

    summary = evaluate_validation(db, detection_run_id=detection_run_id, k=2)

    assert summary.expected_scenarios == 1
    assert summary.detected_scenarios == 1
    assert summary.recall == 1.0
    assert summary.total_alerts == 2
    assert summary.false_alerts == 1
    assert summary.false_discovery_proportion == pytest.approx(0.5)
    assert summary.negative_scenarios == 0
    assert summary.false_positive_scenarios == 0
    assert summary.false_positive_rate is None
    assert summary.precision_at_k is not None
    assert 0.5 <= summary.precision_at_k <= 1.0
    assert summary.k == 2
    assert summary.k_effective == 2
    assert summary.scenarios[0].detected is True
    assert summary.scenarios[0].matching_alert_count == 1
    assert validation_span(db) == (BASE_TIME, BASE_TIME + timedelta(days=7))


def test_validation_detection_uses_a_clean_historical_baseline(db) -> None:
    reference = seed_reference_data(db)
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="train",
        start_at=BASE_TIME,
        end_at=BASE_TIME + timedelta(days=7),
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
    )
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="validation",
        start_at=BASE_TIME + timedelta(days=30),
        end_at=BASE_TIME + timedelta(days=37),
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
    )

    assert clean_baseline_span(db, 30) == (
        BASE_TIME - timedelta(days=30),
        BASE_TIME,
    )

    detection, _ = detect_and_evaluate_validation(
        db,
        _detection_config(),
        k=10,
    )

    assert detection.baseline_start == BASE_TIME - timedelta(days=30)
    assert detection.baseline_end == BASE_TIME
    assert detection.observed_start == BASE_TIME + timedelta(days=30)


def test_validation_evaluation_reports_fpr_from_negative_controls(db) -> None:
    reference = seed_reference_data(db)
    detection_run_id = create_detection_run(db)
    positive_start = BASE_TIME
    positive_end = BASE_TIME + timedelta(days=7)
    negative_start = BASE_TIME + timedelta(days=10)
    negative_end = BASE_TIME + timedelta(days=17)
    create_alert(
        db,
        alert_type="damage_rate_spike",
        scope_type="facility",
        scope_id=str(reference.facility_id),
        observed_start=positive_start,
        observed_end=positive_end,
        detection_run_id=detection_run_id,
    )
    create_alert(
        db,
        alert_type="damage_rate_spike",
        scope_type="facility",
        scope_id=str(reference.facility_id),
        observed_start=negative_start,
        observed_end=negative_end,
        detection_run_id=detection_run_id,
    )
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="validation",
        start_at=positive_start,
        end_at=positive_end,
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
        expected_detection=True,
    )
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="validation",
        start_at=negative_start,
        end_at=negative_end,
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
        expected_detection=False,
    )
    create_scenario(
        db,
        scenario_type="facility_rate_shift",
        split="validation",
        start_at=BASE_TIME + timedelta(days=20),
        end_at=BASE_TIME + timedelta(days=27),
        affected_entity_type="facility",
        affected_entity_id=str(reference.facility_id),
        expected_detection=False,
    )

    summary = evaluate_validation(db, detection_run_id=detection_run_id, k=10)

    assert summary.expected_scenarios == 1
    assert summary.detected_scenarios == 1
    assert summary.negative_scenarios == 2
    assert summary.false_positive_scenarios == 1
    assert summary.false_positive_rate == pytest.approx(0.5)
    assert summary.total_alerts == 2
    assert summary.false_alerts == 1
    assert summary.false_discovery_proportion == pytest.approx(0.5)
    assert summary.precision_at_k == pytest.approx(0.5)
    assert summary.k == 10
    assert summary.k_effective == 2
