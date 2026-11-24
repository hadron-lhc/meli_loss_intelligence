# 07 — KPI Definitions, Statistical Detection & Model Evaluation

## 1. Metric definitions

### Confirmed damage shipments
Count distinct shipments with at least one incident where:
- `incident_type = 'package_damage'`
- `incident_status = 'confirmed'`

For shipment-level damage rate, count each shipment once even if multiple damage incident records exist. For incident workload, count incidents separately.

### Damage rate
`distinct confirmed-damage shipments / eligible processed shipments`

The eligible denominator must be defined consistently for the selected cohort and period. For the MVP, use shipments that entered the measured operational scope during the selected period and have a valid cohort assignment. Document exclusions.

### Damages per 1,000 shipments
`damage_rate * 1000`

### Estimated synthetic loss
Sum `estimated_loss_amount` for confirmed incidents with a known amount, grouped by currency. Do not sum across currencies without a conversion source/rate.

### Incident concentration
`incidents in group / all confirmed incidents in comparison population`

This is a share, not a rate. Display it separately from damage rate.

### Detection delay
For an injected scenario, time between scenario start / first detectable signal and first alert. State exact convention used.

### Alert precision@K
Among the top K alerts ranked by priority/score in a test window, proportion that overlap an injected scenario under a documented matching rule. This is synthetic scenario detection precision, not real-world operational precision.

### Recall
Proportion of expected-to-detect held-out scenarios detected under the documented matching rule.

### False discovery proportion (FDP)
False alerts divided by all alerts, using held-out synthetic truth. This is the complement of alert precision and is not a false-positive rate. Do not call an alert false merely because no confirmed damage exists; the label is based on scenario ground truth for evaluation only.

### False positive rate (FPR)
Among negative-control scenarios with no injected effect, the proportion that received at least one matching alert. FPR is reported as null when the evaluation set has no negative controls. FDP and FPR answer different questions and must not be substituted for each other.

## 2. Statistical baseline first

Recommended first detector:
- Aggregate confirmed damage rate by entity and time window.
- Compare an observed window with a baseline window.
- Enforce a minimum denominator.
- Use confidence intervals or a suitable count/rate test.
- Apply multiple-comparison caution when scanning many entities.
- Prefer shrinkage / empirical-Bayes or hierarchical approaches only if justified and implemented transparently.
- Show numerator, denominator, observed rate, baseline rate and uncertainty.

A simple rate threshold is not sufficient if group volumes vary substantially.

## 3. Candidate statistical methods

Start simple and document assumptions:
- Wilson interval for binomial proportions.
- Two-proportion comparison or exact test for small counts.
- Poisson rate comparison when exposure/time assumptions are appropriate.
- Control chart / EWMA for temporal monitoring, if enough time points exist.

Avoid claiming statistical significance without stating the test, assumptions, and multiple-testing handling.

## 4. Isolation Forest

Use only after baseline:
- Input features should be derived from operational data, not synthetic truth tables.
- Candidate features: event counts by stage, elapsed time between stages, event-gap counts, shipment weight/dimensions, package category, packaging type, number of delivery attempts, reporting delay.
- Avoid direct identifiers and target leakage.
- Encode categorical features appropriately.
- Fit scaler/encoder in a pipeline where required.
- Use contamination as a modelling assumption, not an estimate of real anomaly prevalence.
- Score is an anomaly ranking/score, not damage probability.
- Compare incremental value against statistical baseline.

## 5. Evaluation design

- Use scenario-level train/validation/test splits by time and/or entity.
- Hold out entire scenarios/entities where feasible.
- Do not randomly split near-duplicate rows across train and test if that leaks patterns.
- Keep `synthetic_scenarios` and `synthetic_truth_links` inaccessible to feature generation and dashboard production code.
- Evaluate statistical detector and Isolation Forest on identical held-out scenarios.
- Report precision@K, recall, false-discovery proportion, false-positive rate on negative controls, detection delay and alert volume. Do not label FDP as FPR.
- Include a no-signal baseline and a simple rules baseline.
- Report confidence intervals or variability across repeated seeds where feasible.

## 6. Decision policy

The system recommends investigation; it does not:
- declare a shipment damaged without a confirmed incident,
- declare a carrier responsible,
- estimate actual Mercado Libre loss,
- identify a customer or seller as fraudulent,
- automatically block, penalize or reimburse anyone.
