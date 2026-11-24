# 02 — Industry Benchmark & Product Lessons

## Purpose

Use public industry references to identify useful product capabilities and technical patterns. This is a capability benchmark, not a claim that the PoC has tested or replicated these commercial products.

## Reference landscape

### project44
Public positioning: shipment visibility, exception management and logistics orchestration.
Potential lesson:
- Visibility should lead to actionable exceptions.
- An exception needs context, ownership, status and resolution history.
- A dashboard should connect aggregate performance to individual shipment evidence.

### FourKites
Public positioning: supply-chain visibility, shipment tracking and risk/exception alerts.
Potential lesson:
- Event integration and timeline reconstruction are foundational.
- Risk alerts should be tied to operational context, not shown as unexplained scores.

### Descartes
Public positioning: transportation management, logistics connectivity, visibility and analytics.
Potential lesson:
- Carrier connectivity, standardized data and operational workflow matter as much as predictive models.
- Do not add ML before data integration and data quality are credible.

### Andreani (Argentina)
Its 2025 sustainability reporting describes a digital delivery-management system with monitoring across stages, GPS, incident/event capture, alerts, route/zone/driver analysis and operational follow-up.
Potential lesson:
- Local logistics operations can be represented through event histories, locations, incidents and corrective-action workflows.
- Avoid treating international product patterns as automatically transferable to Argentina.

### UPS / Happy Returns Return Vision
Public reporting describes a returns-oriented tool using photos and other signals to flag potentially irregular returns, with human review.
Potential lesson:
- Returns intelligence should produce review candidates, not automatic fraud verdicts.
- Evidence capture and human adjudication are important.
- This belongs in a secondary module, not the core damage-prevention MVP.

### Computer vision research
Research literature describes object/packaging attribute detection and damage recognition using object-detection architectures.
Potential lesson:
- Image-based damage detection is a plausible future extension.
- It requires representative images, clear damage labels, annotation guidance and a separate evaluation protocol.
- It is not part of MVP because this PoC has no genuine operational image corpus.

## Capability matrix

| Capability | MVP? | Reason |
|---|---:|---|
| Shipment event timeline | Yes | Core operational context. |
| Damage KPI monitoring | Yes | Core problem measurement. |
| Facility/carrier/stage comparisons | Yes | Helps locate concentrations. |
| Statistical alerting | Yes | Explainable starting point. |
| Alert queue and investigation workflow | Yes | Converts analytics into work. |
| Unsupervised anomaly score | Yes, after baseline | Test whether it adds value over rules/statistics. |
| Returns anomaly monitoring | Limited extension | Secondary objective, no fraud verdicts. |
| Computer vision | No | Requires image data and labels. |
| Real-time streaming / Kafka | No | No demonstrated latency or scale requirement. |
| Enterprise orchestration | No | Start with reproducible batch pipeline. |

## Product differentiation for this PoC

The goal is not to recreate a full transport-management or visibility platform. The demonstrable value is a coherent, explainable workflow:

1. Monitor normalized damage rates.
2. Detect unusual group-level patterns.
3. Prioritize candidate investigations.
4. Drill down to shipment event histories.
5. Record human review outcomes.
6. Evaluate detection quality against known synthetic scenarios.

## Benchmark caveats

- Vendor capability pages are marketing material; do not treat them as independent performance evidence.
- Public reports do not disclose comparable package-damage rates for these vendors.
- Do not create a league table or claim that one vendor is more accurate than another.
- Before publishing, verify the latest vendor documentation and source dates.
