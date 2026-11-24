from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loss_intelligence.domain.events import EVENT_TAXONOMY
from loss_intelligence.synthetic.common import DATASET_FILES, deterministic_uuid
from loss_intelligence.synthetic.config import SyntheticDataConfig
from loss_intelligence.synthetic.writer import resolve_dataset_dir

SHIPMENT_STATUSES = {
    "created",
    "in_transit",
    "delivered",
    "returned",
    "cancelled",
    "lost",
    "unknown",
}
INCIDENT_TYPES = {"package_damage", "package_loss", "tampering", "other"}
DAMAGE_TYPES = {
    "crushed",
    "torn",
    "punctured",
    "wet",
    "broken_contents",
    "deformed",
    "other",
    "unknown",
}
SEVERITIES = {"low", "medium", "high", "critical", "unknown"}
INCIDENT_STATUSES = {"reported", "under_review", "confirmed", "rejected", "closed"}
EVIDENCE_TYPES = {
    "photo",
    "inspection",
    "customer_report",
    "carrier_report",
    "multiple",
    "unknown",
}
RETURN_REASONS = {
    "damaged",
    "wrong_item",
    "not_as_described",
    "changed_mind",
    "size_fit",
    "missing_parts",
    "other",
    "unknown",
}
INSPECTION_OUTCOMES = {
    "not_inspected",
    "matches_declaration",
    "does_not_match_declaration",
    "inconclusive",
    "unknown",
}
RETURN_STATUSES = {"initiated", "in_transit", "received", "inspected", "closed", "cancelled"}
CONDITIONS_ON_RETURN = {"new", "used", "damaged", "incomplete", "unknown"}
TRUTH_ENTITY_TYPES = {"shipment", "event", "incident", "return"}
TRUTH_ROLES = {"affected", "control", "background"}
SPLITS = {"train", "validation", "test"}
DIFFICULTIES = {"easy", "medium", "hard"}


@dataclass(frozen=True)
class ValidationResult:
    dataset_dir: Path
    manifest: dict[str, Any]
    row_counts: dict[str, int]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_quality_findings: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"valid={self.ok} errors={len(self.errors)} warnings={len(self.warnings)} "
            f"rows={sum(self.row_counts.values())}"
        )


class _Checker:
    def __init__(self, dataset_dir: Path, manifest: dict[str, Any]) -> None:
        self.dataset_dir = dataset_dir
        self.manifest = manifest
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.row_counts: dict[str, int] = {}
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.findings = Counter(
            {
                "late_recorded_events": 0,
                "timestamp_conflicts": 0,
                "shipments_with_duplicate_event_codes": 0,
                "events_missing_facility": 0,
                "events_missing_carrier": 0,
                "shipments_missing_dimensions": 0,
                "data_gap_events": 0,
            }
        )

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def run(self) -> ValidationResult:
        self._read_files()
        self._check_manifest()
        if self.errors:
            return self._result()

        indexes = self._build_indexes()
        if indexes is None:
            return self._result()

        self._check_references(indexes)
        self._check_duplicates(indexes)
        self._check_truth(indexes)
        self._check_leakage()
        self._check_manifest_findings()
        return self._result()

    def _result(self) -> ValidationResult:
        if self.errors:
            self.warnings.append("validation errors prevent a safe load")
        return ValidationResult(
            dataset_dir=self.dataset_dir,
            manifest=self.manifest,
            row_counts=self.row_counts,
            errors=self.errors,
            warnings=self.warnings,
            data_quality_findings=dict(self.findings),
        )

    def _read_files(self) -> None:
        expected = self.manifest.get("files", DATASET_FILES)
        for name, filename in DATASET_FILES.items():
            path = self.dataset_dir / filename
            if not path.is_file():
                self.error(f"missing dataset file: {filename}")
                self.rows[name] = []
                continue
            rows: list[dict[str, Any]] = []
            try:
                with path.open(encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if not line.strip():
                            continue
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            self.error(f"{filename}:{line_number} must be a JSON object")
                            continue
                        rows.append(value)
            except json.JSONDecodeError as exc:
                self.error(f"{filename}: invalid JSON: {exc}")
            self.rows[name] = rows
            self.row_counts[name] = len(rows)

        if isinstance(expected, dict):
            missing = set(DATASET_FILES) - set(expected)
            extra = set(expected) - set(DATASET_FILES)
            for name in sorted(missing):
                self.error(f"manifest does not list dataset file: {DATASET_FILES[name]}")
            for name in sorted(extra):
                self.error(f"manifest lists unknown dataset file: {name}")

    def _check_manifest(self) -> None:
        row_counts = self.manifest.get("row_counts")
        if not isinstance(row_counts, dict):
            self.error("manifest row_counts must be an object")
        else:
            for name, count in self.row_counts.items():
                if row_counts.get(name) != count:
                    self.error(
                        f"manifest row_counts[{name}]={row_counts.get(name)} but file has {count}"
                    )

        config = self.manifest.get("config")
        if not isinstance(config, dict):
            self.error("manifest config must be an object")
            return
        try:
            parsed_config = SyntheticDataConfig.model_validate(config)
        except ValueError as exc:
            self.error(f"manifest config is invalid: {exc}")
            return
        if parsed_config.config_hash != self.manifest.get("config_hash"):
            self.error("manifest config_hash does not match config")
        generator_version = self.manifest.get("generator_version")
        if not isinstance(generator_version, str):
            self.error("manifest generator_version must be a string")
            return
        run_key = (
            parsed_config.config_hash
            if generator_version == "0.1.0"
            else f"{generator_version}:{parsed_config.config_hash}"
        )
        expected_run_id = deterministic_uuid(parsed_config.seed, "generation_run", run_key)
        if str(expected_run_id) != self.manifest.get("run_id"):
            self.error("manifest run_id is not deterministic for the supplied config")

    def _build_indexes(self) -> dict[str, dict[str, dict[str, Any]]] | None:
        indexes: dict[str, dict[str, dict[str, Any]]] = {}
        specs = {
            "zones": "zone_id",
            "facilities": "facility_id",
            "carriers": "carrier_id",
            "product_categories": "product_category_id",
            "packaging_types": "packaging_type_id",
            "shipments": "shipment_id",
            "shipment_events": "event_id",
            "incidents": "incident_id",
            "returns": "return_id",
            "synthetic_scenarios": "scenario_id",
            "synthetic_truth_links": "truth_link_id",
        }
        for name, field_name in specs.items():
            index: dict[str, dict[str, Any]] = {}
            for row_number, row in enumerate(self.rows[name], start=1):
                value = row.get(field_name)
                if not isinstance(value, str) or not value:
                    self.error(f"{name}:{row_number} missing {field_name}")
                    continue
                if value in index:
                    self.error(f"{name}:{row_number} duplicate {field_name}={value}")
                    continue
                index[value] = row
            indexes[name] = index
        return indexes

    def _check_references(self, indexes: dict[str, dict[str, dict[str, Any]]]) -> None:
        zones = indexes["zones"]
        facilities = indexes["facilities"]
        carriers = indexes["carriers"]
        categories = indexes["product_categories"]
        packaging = indexes["packaging_types"]
        shipments = indexes["shipments"]
        events = indexes["shipment_events"]
        returns = indexes["returns"]

        for row_number, facility in enumerate(self.rows["facilities"], start=1):
            self._require_ref(facility.get("zone_id"), zones, "facilities", row_number, "zone_id")

        for row_number, shipment in enumerate(self.rows["shipments"], start=1):
            prefix = f"shipments:{row_number}"
            self._require_ref(
                shipment.get("origin_facility_id"),
                facilities,
                "shipments",
                row_number,
                "origin_facility_id",
                optional=True,
            )
            self._require_ref(
                shipment.get("destination_zone_id"),
                zones,
                "shipments",
                row_number,
                "destination_zone_id",
            )
            self._require_ref(
                shipment.get("carrier_id"),
                carriers,
                "shipments",
                row_number,
                "carrier_id",
                optional=True,
            )
            self._require_ref(
                shipment.get("product_category_id"),
                categories,
                "shipments",
                row_number,
                "product_category_id",
            )
            self._require_ref(
                shipment.get("packaging_type_id"),
                packaging,
                "shipments",
                row_number,
                "packaging_type_id",
            )
            status = shipment.get("shipment_status")
            if status not in SHIPMENT_STATUSES:
                self.error(f"{prefix} invalid shipment_status={status!r}")
            if status in {"delivered", "returned"} and not shipment.get("delivered_at"):
                self.error(f"{prefix} status {status} requires delivered_at")
            if shipment.get("delivered_at") and shipment.get("dispatched_at"):
                if self._dt(shipment["delivered_at"], prefix) < self._dt(
                    shipment["dispatched_at"], prefix
                ):
                    self.error(f"{prefix} delivered_at is before dispatched_at")
            if (shipment.get("declared_value") is None) != (shipment.get("currency_code") is None):
                self.error(f"{prefix} declared_value and currency_code must be paired")
            for field_name in ("weight_g", "length_mm", "width_mm", "height_mm"):
                value = shipment.get(field_name)
                if value is not None and (not isinstance(value, int) or value <= 0):
                    self.error(f"{prefix} invalid {field_name}={value!r}")
            if status == "returned" and not any(
                item.get("shipment_id") == shipment.get("shipment_id") for item in returns.values()
            ):
                self.error(f"{prefix} status returned has no return row")

        event_keys: set[tuple[str, int]] = set()
        for row_number, event in enumerate(self.rows["shipment_events"], start=1):
            prefix = f"shipment_events:{row_number}"
            shipment_id = event.get("shipment_id")
            if shipment_id not in shipments:
                self.error(f"{prefix} unknown shipment_id={shipment_id}")
            taxonomy = EVENT_TAXONOMY.get(event.get("event_code"))
            if taxonomy is None:
                self.error(f"{prefix} unknown event_code={event.get('event_code')!r}")
            else:
                if event.get("event_name") != taxonomy.name:
                    self.error(f"{prefix} event_name does not match taxonomy")
                if event.get("stage") != taxonomy.stage:
                    self.error(f"{prefix} stage does not match taxonomy")
                if event.get("event_status") != taxonomy.status:
                    self.error(f"{prefix} event_status does not match taxonomy")
            sequence = event.get("sequence_number")
            if not isinstance(sequence, int) or sequence <= 0:
                self.error(f"{prefix} invalid sequence_number={sequence!r}")
            else:
                key = (str(shipment_id), sequence)
                if key in event_keys:
                    self.error(f"{prefix} duplicate shipment sequence {key}")
                event_keys.add(key)
            self._require_ref(
                event.get("facility_id"),
                facilities,
                "shipment_events",
                row_number,
                "facility_id",
                optional=True,
            )
            self._require_ref(
                event.get("zone_id"),
                zones,
                "shipment_events",
                row_number,
                "zone_id",
                optional=True,
            )
            self._require_ref(
                event.get("carrier_id"),
                carriers,
                "shipment_events",
                row_number,
                "carrier_id",
                optional=True,
            )
            occurred_at = self._dt(event.get("occurred_at"), prefix)
            recorded_at = self._dt(event.get("recorded_at"), prefix)
            if occurred_at and recorded_at:
                if recorded_at < occurred_at:
                    self.findings["timestamp_conflicts"] += 1
                if recorded_at > occurred_at + timedelta(hours=24):
                    self.findings["late_recorded_events"] += 1
            if event.get("facility_id") is None:
                self.findings["events_missing_facility"] += 1
            if event.get("carrier_id") is None:
                self.findings["events_missing_carrier"] += 1
            if event.get("event_code") == "DATA_GAP_DETECTED":
                self.findings["data_gap_events"] += 1

        event_groups: Counter[tuple[str, str, str]] = Counter()
        for event in self.rows["shipment_events"]:
            code = event.get("event_code")
            shipment_id = event.get("shipment_id")
            occurred_at = event.get("occurred_at")
            if (
                isinstance(code, str)
                and isinstance(shipment_id, str)
                and isinstance(occurred_at, str)
            ):
                event_groups[(shipment_id, code, occurred_at)] += 1
        duplicated_shipments = {
            shipment_id for (shipment_id, _, _), count in event_groups.items() if count > 1
        }
        self.findings["shipments_with_duplicate_event_codes"] = len(duplicated_shipments)

        for shipment in self.rows["shipments"]:
            if any(
                shipment.get(field_name) is None
                for field_name in ("weight_g", "length_mm", "width_mm", "height_mm")
            ):
                self.findings["shipments_missing_dimensions"] += 1

        for row_number, incident in enumerate(self.rows["incidents"], start=1):
            prefix = f"incidents:{row_number}"
            shipment_id = incident.get("shipment_id")
            if shipment_id not in shipments:
                self.error(f"{prefix} unknown shipment_id={shipment_id}")
            related_event_id = incident.get("related_event_id")
            related_event = events.get(related_event_id)
            if related_event is None:
                self.error(f"{prefix} unknown related_event_id={related_event_id}")
            elif related_event.get("shipment_id") != shipment_id:
                self.error(f"{prefix} related_event belongs to another shipment")
            if incident.get("incident_type") not in INCIDENT_TYPES:
                self.error(f"{prefix} invalid incident_type")
            damage_type = incident.get("damage_type")
            if incident.get("incident_type") == "package_damage" and damage_type is None:
                self.error(f"{prefix} package_damage requires damage_type")
            if damage_type is not None and damage_type not in DAMAGE_TYPES:
                self.error(f"{prefix} invalid damage_type={damage_type!r}")
            if incident.get("severity") not in SEVERITIES:
                self.error(f"{prefix} invalid severity")
            if incident.get("incident_status") not in INCIDENT_STATUSES:
                self.error(f"{prefix} invalid incident_status")
            if incident.get("evidence_type") not in EVIDENCE_TYPES:
                self.error(f"{prefix} invalid evidence_type")
            if incident.get("incident_status") == "confirmed" and not incident.get("confirmed_at"):
                self.error(f"{prefix} confirmed incident requires confirmed_at")
            reported_at = self._dt(incident.get("reported_at"), prefix)
            confirmed_at = self._dt(incident.get("confirmed_at"), prefix)
            if reported_at and confirmed_at and confirmed_at < reported_at:
                self.error(f"{prefix} confirmed_at is before reported_at")
            if (incident.get("estimated_loss_amount") is None) != (
                incident.get("currency_code") is None
            ):
                self.error(f"{prefix} estimated_loss_amount and currency_code must be paired")

        for row_number, return_row in enumerate(self.rows["returns"], start=1):
            prefix = f"returns:{row_number}"
            shipment_id = return_row.get("shipment_id")
            if shipment_id not in shipments:
                self.error(f"{prefix} unknown shipment_id={shipment_id}")
            if return_row.get("declared_reason") not in RETURN_REASONS:
                self.error(f"{prefix} invalid declared_reason")
            if return_row.get("inspection_outcome") not in INSPECTION_OUTCOMES:
                self.error(f"{prefix} invalid inspection_outcome")
            if return_row.get("return_status") not in RETURN_STATUSES:
                self.error(f"{prefix} invalid return_status")
            condition = return_row.get("condition_on_return")
            if condition is not None and condition not in CONDITIONS_ON_RETURN:
                self.error(f"{prefix} invalid condition_on_return={condition!r}")
            initiated_at = self._dt(return_row.get("initiated_at"), prefix)
            received_at = self._dt(return_row.get("received_at"), prefix)
            if initiated_at and received_at and received_at < initiated_at:
                self.error(f"{prefix} received_at is before initiated_at")

        scenario_ids = indexes["synthetic_scenarios"]
        for row_number, scenario in enumerate(self.rows["synthetic_scenarios"], start=1):
            prefix = f"synthetic_scenarios:{row_number}"
            if scenario.get("split") not in SPLITS:
                self.error(f"{prefix} invalid split")
            start_at = self._dt(scenario.get("start_at"), prefix)
            end_at = self._dt(scenario.get("end_at"), prefix)
            if start_at and end_at and end_at <= start_at:
                self.error(f"{prefix} end_at must be after start_at")
            if not isinstance(scenario.get("expected_detection"), bool):
                self.error(f"{prefix} expected_detection must be boolean")
            if not isinstance(scenario.get("expected_signals"), dict):
                self.error(f"{prefix} expected_signals must be an object")
            difficulty = scenario.get("difficulty")
            if difficulty is not None and difficulty not in DIFFICULTIES:
                self.error(f"{prefix} invalid difficulty={difficulty!r}")
            if scenario.get("scenario_id") not in scenario_ids:
                self.error(f"{prefix} scenario not indexed")

    def _check_duplicates(self, indexes: dict[str, dict[str, dict[str, Any]]]) -> None:
        for name, field_name in (
            ("zones", "zone_code"),
            ("facilities", "facility_code"),
            ("carriers", "carrier_code"),
            ("product_categories", "category_code"),
            ("packaging_types", "packaging_code"),
            ("shipments", "shipment_code"),
            ("synthetic_scenarios", "scenario_code"),
        ):
            seen: set[str] = set()
            for row_number, row in enumerate(self.rows[name], start=1):
                value = row.get(field_name)
                if not isinstance(value, str) or not value:
                    self.error(f"{name}:{row_number} missing {field_name}")
                    continue
                if value in seen:
                    self.error(f"{name}:{row_number} duplicate {field_name}={value}")
                seen.add(value)

        # Keep this check intentionally separate from the index build to catch
        # duplicate scenario/entity links even when the file itself is otherwise valid.
        seen_links: set[tuple[str, str, str]] = set()
        for row_number, link in enumerate(self.rows["synthetic_truth_links"], start=1):
            key = (
                str(link.get("scenario_id")),
                str(link.get("entity_type")),
                str(link.get("entity_id")),
            )
            if key in seen_links:
                self.error(f"synthetic_truth_links:{row_number} duplicate link {key}")
            seen_links.add(key)

        for row_number, scenario in enumerate(self.rows["synthetic_scenarios"], start=1):
            if scenario.get("scenario_id") not in indexes["synthetic_scenarios"]:
                self.error(f"synthetic_scenarios:{row_number} scenario not indexed")

    def _check_truth(self, indexes: dict[str, dict[str, dict[str, Any]]]) -> None:
        scenarios = indexes["synthetic_scenarios"]
        entity_indexes = {
            "shipment": indexes["shipments"],
            "event": indexes["shipment_events"],
            "incident": indexes["incidents"],
            "return": indexes["returns"],
        }
        affected_history: dict[tuple[str, str], set[str]] = {}
        for row_number, link in enumerate(self.rows["synthetic_truth_links"], start=1):
            prefix = f"synthetic_truth_links:{row_number}"
            scenario_id = link.get("scenario_id")
            if scenario_id not in scenarios:
                self.error(f"{prefix} unknown scenario_id={scenario_id}")
            entity_type = link.get("entity_type")
            if entity_type not in TRUTH_ENTITY_TYPES:
                self.error(f"{prefix} invalid entity_type={entity_type!r}")
                continue
            entity_id = link.get("entity_id")
            if entity_id not in entity_indexes[entity_type]:
                self.error(f"{prefix} unknown {entity_type} entity_id={entity_id}")
            role = link.get("truth_role")
            if role not in TRUTH_ROLES:
                self.error(f"{prefix} invalid truth_role={role!r}")
            if role == "control" and entity_id in affected_history.get(
                (str(scenario_id), entity_type), set()
            ):
                self.error(f"{prefix} entity is both control and affected")
            if role == "affected" and entity_type == "shipment":
                affected_history.setdefault((str(scenario_id), entity_type), set()).add(
                    str(entity_id)
                )

        for (scenario_id, entity_type), affected in affected_history.items():
            for row_number, link in enumerate(self.rows["synthetic_truth_links"], start=1):
                if (
                    str(link.get("scenario_id")) == scenario_id
                    and link.get("entity_type") == entity_type
                    and link.get("truth_role") == "control"
                    and str(link.get("entity_id")) in affected
                ):
                    self.error(f"synthetic_truth_links:{row_number} control overlaps affected")

    def _check_leakage(self) -> None:
        operational = [
            "zones",
            "facilities",
            "carriers",
            "product_categories",
            "packaging_types",
            "shipments",
            "shipment_events",
            "incidents",
            "returns",
        ]
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
        for name in operational:
            for row_number, row in enumerate(self.rows[name], start=1):
                leaked = forbidden.intersection(row)
                if leaked:
                    self.error(f"{name}:{row_number} contains evaluation fields: {sorted(leaked)}")

    def _check_manifest_findings(self) -> None:
        declared = self.manifest.get("data_quality_findings")
        if isinstance(declared, dict):
            for key, value in self.findings.items():
                if declared.get(key) != value:
                    self.warn(
                        f"manifest data_quality_findings[{key}]={declared.get(key)} "
                        f"but observed {value}"
                    )

    def _require_ref(
        self,
        value: Any,
        index: dict[str, Any],
        name: str,
        row_number: int,
        field_name: str,
        optional: bool = False,
    ) -> None:
        if value is None:
            if not optional:
                self.error(f"{name}:{row_number} missing {field_name}")
            return
        if value not in index:
            self.error(f"{name}:{row_number} unknown {field_name}={value}")

    def _dt(self, value: Any, context: str) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            self.error(f"{context} invalid datetime={value!r}")
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            self.error(f"{context} invalid datetime={value!r}")
            return None


def validate_dataset(dataset_dir: Path) -> ValidationResult:
    dataset_dir = dataset_dir.resolve()
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        return ValidationResult(
            dataset_dir=dataset_dir,
            manifest={},
            row_counts={},
            errors=[f"manifest not found: {manifest_path}"],
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ValidationResult(
            dataset_dir=dataset_dir,
            manifest={},
            row_counts={},
            errors=[f"manifest is invalid JSON: {exc}"],
        )
    if not isinstance(manifest, dict):
        return ValidationResult(
            dataset_dir=dataset_dir,
            manifest={},
            row_counts={},
            errors=["manifest must be a JSON object"],
        )
    return _Checker(dataset_dir, manifest).run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated synthetic dataset.")
    parser.add_argument("--data-dir", default="data/generated", help="dataset root")
    parser.add_argument("--run-id", help="specific run id; defaults to latest")
    args = parser.parse_args()

    dataset_dir = resolve_dataset_dir(Path(args.data_dir), args.run_id)
    result = validate_dataset(dataset_dir)
    print(result.summary())
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")
    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
