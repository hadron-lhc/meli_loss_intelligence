from collections import Counter

from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.generator import generate_dataset
from loss_intelligence.synthetic.scenarios import split_ranges


def test_generator_is_deterministic(fixture_dataset) -> None:
    regenerated = generate_dataset(SyntheticDataConfig.fixture())
    assert fixture_dataset.rows == regenerated.rows


def test_manifest_counts_match_rows(fixture_dataset) -> None:
    for name, count in fixture_dataset.manifest["row_counts"].items():
        assert len(fixture_dataset.rows[name]) == count


def test_manifest_duplicate_count_uses_code_and_timestamp(fixture_dataset) -> None:
    groups = Counter(
        (row["shipment_id"], row["event_code"], row["occurred_at"])
        for row in fixture_dataset.rows["shipment_events"]
    )
    duplicate_shipments = {key[0] for key, count in groups.items() if count > 1}

    assert fixture_dataset.manifest["data_quality_findings"][
        "shipments_with_duplicate_event_codes"
    ] == len(duplicate_shipments)


def test_generator_includes_the_configured_end_date(fixture_dataset) -> None:
    created_dates = {
        row["created_at"].date().isoformat() for row in fixture_dataset.rows["shipments"]
    }
    scenario_end_dates = {
        row["end_at"].date().isoformat() for row in fixture_dataset.rows["synthetic_scenarios"]
    }

    assert min(created_dates) == "2026-01-01"
    assert max(created_dates) == "2026-03-31"
    assert max(scenario_end_dates) <= "2026-04-01"


def test_scenarios_are_split_and_have_truth_links(fixture_dataset) -> None:
    scenarios = fixture_dataset.rows["synthetic_scenarios"]
    links = fixture_dataset.rows["synthetic_truth_links"]

    assert len(scenarios) == 12
    assert Counter(row["split"] for row in scenarios) == {
        "train": 4,
        "validation": 4,
        "test": 4,
    }
    assert Counter(row["expected_detection"] for row in scenarios) == {
        True: 9,
        False: 3,
    }
    assert len({row["scenario_code"] for row in scenarios}) == len(scenarios)
    assert {row["difficulty"] for row in scenarios} == {"easy", "medium"}

    by_scenario = Counter(link["scenario_id"] for link in links)
    affected = Counter(link["scenario_id"] for link in links if link["truth_role"] == "affected")
    controls = Counter(link["scenario_id"] for link in links if link["truth_role"] == "control")
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        assert by_scenario[scenario_id] > 0
        assert controls[scenario_id] == 20
        if scenario["expected_detection"]:
            assert affected[scenario_id] > 0
        else:
            assert affected[scenario_id] == 0


def test_scenarios_do_not_share_facilities() -> None:
    config = SyntheticDataConfig.fixture().model_copy(update={"facility_count": 8})
    dataset = generate_dataset(config)
    facilities = [
        row["affected_entity_id"]
        for row in dataset.rows["synthetic_scenarios"]
        if row["affected_entity_type"] == "facility"
    ]
    assert len(facilities) == len(set(facilities))


def test_scenario_windows_stay_inside_their_split(fixture_dataset) -> None:
    bounds = split_ranges(SyntheticDataConfig.fixture())
    for scenario in fixture_dataset.rows["synthetic_scenarios"]:
        start, end = bounds[scenario["split"]]
        assert start <= scenario["start_at"] < scenario["end_at"] <= end


def test_incidents_reference_events_on_the_same_shipment(fixture_dataset) -> None:
    event_shipments = {
        row["event_id"]: row["shipment_id"] for row in fixture_dataset.rows["shipment_events"]
    }
    shipments = {row["shipment_id"]: row for row in fixture_dataset.rows["shipments"]}
    for incident in fixture_dataset.rows["incidents"]:
        assert incident["incident_type"] == "package_damage"
        assert incident["related_event_id"] in event_shipments
        assert event_shipments[incident["related_event_id"]] == incident["shipment_id"]
        assert shipments[incident["shipment_id"]]["shipment_status"] in {
            "delivered",
            "returned",
        }


def test_returns_only_apply_to_delivered_shipments(fixture_dataset) -> None:
    shipments = {row["shipment_id"]: row for row in fixture_dataset.rows["shipments"]}
    returned_shipment_ids = set()
    for return_row in fixture_dataset.rows["returns"]:
        shipment = shipments[return_row["shipment_id"]]
        assert shipment["shipment_status"] == "returned"
        assert shipment["delivered_at"] is not None
        returned_shipment_ids.add(return_row["shipment_id"])
    for shipment in shipments.values():
        if shipment["shipment_status"] == "returned":
            assert shipment["shipment_id"] in returned_shipment_ids


def test_truth_links_reference_real_entities(fixture_dataset) -> None:
    indexes = {
        "shipment": {row["shipment_id"] for row in fixture_dataset.rows["shipments"]},
        "event": {row["event_id"] for row in fixture_dataset.rows["shipment_events"]},
        "incident": {row["incident_id"] for row in fixture_dataset.rows["incidents"]},
        "return": {row["return_id"] for row in fixture_dataset.rows["returns"]},
    }
    for link in fixture_dataset.rows["synthetic_truth_links"]:
        assert link["entity_id"] in indexes[link["entity_type"]]


def test_operational_rows_do_not_leak_scenario_truth(fixture_dataset) -> None:
    forbidden = {
        "scenario_id",
        "truth_link_id",
        "truth_role",
        "expected_signals",
        "expected_detection",
        "difficulty",
        "split",
        "affected_entity_id",
        "affected_entity_type",
    }
    for name in (
        "shipments",
        "shipment_events",
        "incidents",
        "returns",
    ):
        for row in fixture_dataset.rows[name]:
            assert not forbidden.intersection(row)


def test_no_scenario_profile_has_no_truth() -> None:
    dataset = generate_dataset(SyntheticDataConfig.fixture_without_scenarios())
    assert dataset.rows["synthetic_scenarios"] == []
    assert dataset.rows["synthetic_truth_links"] == []
    assert dataset.manifest["scenario_counts"] == {
        "train": 0,
        "validation": 0,
        "test": 0,
    }
