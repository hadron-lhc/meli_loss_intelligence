import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class DetectionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = "statistical_rules"
    model_version: str = "0.1.0"
    min_observed_denominator: int = Field(default=50, ge=1)
    min_baseline_denominator: int = Field(default=50, ge=1)
    min_observed_numerator: int = Field(default=3, ge=1)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_relative_lift: float = Field(default=1.5, ge=1)
    min_zero_baseline_rate: float = Field(default=0.25, ge=0, le=1)
    max_evidence: int = Field(default=5, ge=0, le=50)
    lookback_days: int = Field(default=30, ge=7, le=180)

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
