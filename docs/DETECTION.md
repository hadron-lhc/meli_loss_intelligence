# Detection Layer

> Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.

Phase 4 adds a transparent statistical baseline detector. It scans operational data,
persists reproducible detection runs and alerts, links supporting evidence, and evaluates
alerts against held-out synthetic scenarios. Alerts are review signals only. They do not
confirm damage, assign carrier culpability or make a fraud determination.

Detection feature queries never read `evaluation.*`. Scenario truth is used only after
alerts exist, inside the evaluation module.

## Commands

```bash
make migrate
make detect
make detect-validation
make evaluate-validation
```

- `make detect` scores the latest 30-day window in the main database.
- `make detect-validation` detects over the full validation-scenario span and immediately
  evaluates the resulting run.
- `make evaluate-validation` evaluates the latest completed run, or `DETECTION_RUN_ID=...`
  if supplied.

Useful overrides:

```bash
make detect DETECTION_DB=test
make detect DETECTION_START=2026-04-01T00:00:00+00:00 \
  DETECTION_END=2026-05-16T00:00:00+00:00
make detect DETECTION_ALPHA=0.01 DETECTION_MIN_LIFT=2 DETECTION_MAX_EVIDENCE=10
make detect-validation DETECTION_K=5
make evaluate-validation DETECTION_RUN_ID=<uuid> DETECTION_K=10
```

The equivalent Python entry point is:

```bash
uv run python -m loss_intelligence.detection.cli detect \
  --database main --start 2026-04-01T00:00:00+00:00 \
  --end 2026-05-16T00:00:00+00:00 --max-evidence 5
```

Commands are `detect`, `run-validation` and `evaluate-validation`. Every command prints JSON.

## Time windows

- With no explicit dates, the observed window ends at the UTC midnight after the latest
  non-test shipment `created_at` and starts `lookback_days` earlier.
- An explicit `--start` is inclusive; `--end` is exclusive.
- For ad hoc detection, the baseline window is the same length immediately before the
  observed window.
- `run-validation` uses a clean historical baseline ending at the earliest scenario
  start across all splits, with the configured `lookback_days`. This avoids scenarios
  contaminating the baseline; the baseline must not overlap the observed window.
- Windows with a non-positive length are rejected.
- `run-validation` uses the minimum scenario start and maximum scenario end from
  `evaluation.synthetic_scenarios` where `split = 'validation'` and
  `expected_detection = TRUE`.

## Signals

| Metric | Scope | Numerator | Denominator |
|---|---|---|---|
| Confirmed damage rate | facility, carrier, carrier-zone, zone, product category, packaging type, stage | Distinct eligible shipments with a confirmed package-damage incident attributed to the scope | Eligible shipments exposed to the scope |
| Sequence anomaly rate | facility | Distinct shipments with repeated `LINEHAUL_IN_TRANSIT` or repeated `DELIVERY_ATTEMPTED` events that visited the facility | Distinct eligible shipments with an event at the facility |
| Return rate | product category | Distinct eligible shipments with a return | Eligible shipments in the category |
| Data-quality issue rate | facility | Distinct shipments with missing dimensions, a late event, a timestamp conflict, `DATA_GAP_DETECTED`, or a duplicate event code/timestamp | Distinct shipments with an event at the facility |

Eligibility, confirmed-damage and attribution semantics follow the analytics layer.
`SHP_CREATED` missing a facility is expected and is not treated as a data-quality failure.

## Statistical test

For each scope, the observed and baseline rates are compared with a one-sided
two-proportion z-test for an increase:

```text
z = (p_observed - p_baseline) / sqrt(p_pooled * (1 - p_pooled) *
    (1 / n_observed + 1 / n_baseline))
p = P(Z >= z)
```

- The pooled proportion is `(x_observed + x_baseline) / (n_observed + n_baseline)`.
- Zero variance returns `z = 0`, `p = 1`.
- Candidate tests require minimum observed and baseline denominators plus a minimum
  observed numerator.
- Benjamini-Hochberg controls the false-discovery rate across all testable scopes in
  the run. `run-validation` reports `tested_hypotheses`, `significant_hypotheses` and
  `suppressed_hypotheses` so q-significant signals rejected by the lift or zero-baseline
  guard remain visible instead of disappearing behind the final alert count.
- An alert requires `q <= alpha` and a relative lift of at least `min_relative_lift`.
- When the baseline rate is zero, relative lift is undefined; the observed rate must be at
  least `min_zero_baseline_rate` instead. This prevents a system-wide or low-rate peer
  change from flagging every scope when no historical comparison rate exists.
- Baseline/observed numerators, denominators and rates are stored on each alert.

Default configuration:

| Setting | Default |
|---|---:|
| `model_name` | `statistical_rules` |
| `model_version` | `0.1.0` |
| `lookback_days` | `30` |
| `min_observed_denominator` | `50` |
| `min_baseline_denominator` | `50` |
| `min_observed_numerator` | `3` |
| `alpha` | `0.05` |
| `min_relative_lift` | `1.5` |
| `min_zero_baseline_rate` | `0.25` |
| `max_evidence` | `5` |

The SHA-256 config hash is stored with every detection run.

## Persistence

A run is recorded in `meta.detection_runs` with model, version, config, config hash,
status and timestamps. It links the latest completed generation run when available.
Alerts are written to `anomaly_alerts` with:

- alert and scope type, scope name in the explanation, and the observed/baseline windows
- observed and baseline numerators, denominators and rates
- z-score as `anomaly_score`, priority, explanation and model metadata
- `status = 'new'` and the detection run ID

Supporting shipment and incident IDs go to `anomaly_alert_evidence`, capped by
`max_evidence`. Explanations state that the result is a statistical association, not a
causal or culpability conclusion.

A run is marked `completed` only after alerts persist. Any exception marks it `failed`
and re-raises; alert writes occur in a transaction.

## Validation evaluation

`evaluate-validation` uses validation-split scenarios. Scenarios with
`expected_detection = TRUE` are expected positives; scenarios with
`expected_detection = FALSE` are negative controls used only to estimate the false
positive rate. Detection recall is computed over expected positives only.

Matching rule:

1. Alert `alert_type`, `scope_type` and `scope_id` must match the scenario type and
   affected entity.
2. The alert window must overlap the scenario window.
3. Multiple matching alerts count as one detected scenario.

Reported metrics:

- `recall`: detected expected scenarios / expected scenarios
- `false_alerts`: alerts matching no expected scenario
- `false_discovery_proportion`: false alerts / all run alerts (`1 - precision`)
- `negative_scenarios`: validation scenarios with `expected_detection = FALSE`
- `false_positive_scenarios`: negative controls with at least one matching alert
- `false_positive_rate`: false positive scenarios / negative scenarios; null when no
  negative controls exist
- `precision_at_k`: matched alerts among the top K by anomaly score / effective K
- `k_effective`: `min(k, total_alerts)`; null precision is reported when no alerts exist
- per-scenario matching and overlapping alert counts

Detection delay is not reported because the detector evaluates fixed windows rather than
continuous streams; a window-level delay would overstate temporal precision.

## Limits and scope

- The statistical baseline is implemented; Isolation Forest is intentionally deferred.
  It must be compared against this baseline on identical held-out scenarios before any
  incremental-value claim is made.
- Alert priority is a triage heuristic based on q-value and lift, not a calibrated risk score.
- Evaluation uses synthetic scenario labels and does not establish real-world performance.
- Small scopes are suppressed by minimum-volume rules rather than ranked.
- Facility and stage exposures can overlap because one shipment may visit multiple scopes.
- A shipment-level sequence anomaly is attributed to each facility the shipment visited;
  facility and stage exposure are not mutually exclusive.
- No alert confirms an incident or assigns responsibility.
