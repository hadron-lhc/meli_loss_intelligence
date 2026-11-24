import hashlib
import json
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SyntheticDataConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = Field(default=20261119, ge=0)
    shipment_count: int = Field(default=30_000, ge=100, le=100_000)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 6, 30)

    baseline_damage_rate: float = Field(default=0.01, gt=0, lt=0.25)
    return_rate: float = Field(default=0.06, ge=0, le=0.5)
    scenarios_per_split: int = Field(default=3, ge=0, le=5)
    negative_scenarios_per_split: int = Field(default=1, ge=0, le=3)
    control_sample_size: int = Field(default=20, ge=0, le=200)
    clean_baseline_days: int = Field(default=30, ge=0, le=90)

    zone_count: int = Field(default=8, ge=5, le=10)
    facility_count: int = Field(default=8, ge=5, le=10)
    carrier_count: int = Field(default=6, ge=4, le=8)
    product_category_count: int = Field(default=10, ge=8, le=12)
    packaging_type_count: int = Field(default=5, ge=4, le=6)

    event_missing_rate: float = Field(default=0.02, ge=0, le=0.2)
    event_late_rate: float = Field(default=0.02, ge=0, le=0.2)
    unknown_attribution_rate: float = Field(default=0.005, ge=0, le=0.1)
    incomplete_dimensions_rate: float = Field(default=0.02, ge=0, le=0.2)

    damage_scenario_multiplier: float = Field(default=6.0, ge=1.0, le=20.0)
    return_scenario_multiplier: float = Field(default=3.0, ge=1.0, le=10.0)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "SyntheticDataConfig":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.facility_count < self.zone_count:
            raise ValueError("facility_count must be at least zone_count")
        return self

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def fixture(cls) -> "SyntheticDataConfig":
        return cls(
            seed=7,
            shipment_count=1_500,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            baseline_damage_rate=0.012,
            zone_count=5,
            facility_count=5,
            carrier_count=4,
            product_category_count=8,
            packaging_type_count=4,
            scenarios_per_split=3,
        )

    @classmethod
    def fixture_without_scenarios(cls) -> "SyntheticDataConfig":
        return cls.fixture().model_copy(update={"scenarios_per_split": 0})
