# 01 — Project Context & Problem Research

## 1. Project positioning

Working name: **MELI Loss Intelligence**  
Suggested public-facing name if brand-risk avoidance is preferred: **Last-Mile Loss Intelligence PoC**.

Subtitle: *Operational Analytics & Loss Prevention for Last-Mile Logistics.*

This is an independent portfolio proof of concept inspired by publicly described last-mile loss-prevention responsibilities. It is not a Mercado Libre product, does not integrate with Mercado Libre systems, and uses no private Mercado Libre data.

## 2. Problem statement

Last-mile logistics operations need to identify where package-damage incidents concentrate, understand the shipment/event patterns associated with those incidents, and prioritize cases for human investigation.

The project explores this question:

> How can shipment traceability events, shipment characteristics and incident history be used to identify unusual concentrations of confirmed package damage, prioritize operational investigations, and support loss-prevention decisions?

The product must do more than count incidents. It should connect:
1. Monitoring: what is happening and where?
2. Detection: which groups or individual shipments are unusual?
3. Investigation: what evidence and event sequence are associated with the signal?
4. Prioritization: which cases should an analyst review first?
5. Learning: what did the investigation conclude, and did follow-up actions change the measured pattern?

## 3. Publicly grounded motivation (research baseline: 2026-11-19)

The research conducted for this project identified the following public context:

- A Mercado Envíos job posting described responsibilities including monitoring/auditing last-mile centers, reducing package-damage losses, detecting/preventing irregularities in reverse logistics, analyzing BI/database data, and using AI to identify anomalies and potential causes.
- Mercado Libre public financial disclosures describe buyer-protection reimbursements when items arrive damaged or otherwise fail to meet policy conditions, and mention potential recovery from carriers in certain circumstances. These disclosures do **not** provide a damage-specific loss rate.
- CACE reported 181.5 million Argentine e-commerce purchase orders and 248 million units sold in the first half of 2026. These figures describe market scale, not package damage.
- DHL E-Commerce Trends 2026 reported that 49% of surveyed Argentine shoppers who return goods selected “goods lost/damaged in transit” as a reason. This is a survey response among people who return goods, not a percentage of all shipments or all shoppers; multiple reasons may be selected.
- Andreani's 2025 sustainability report describes a digital delivery-management system with shipment-stage monitoring, GPS, incident records, alerts and analysis by zone, route and driver.
- UPS/Happy Returns Return Vision was reported as using signals and photos to identify potentially irregular returns, with human review. This is a reference for a future returns module, not evidence about Mercado Libre.

The research source references from the original research session are retained in the project conversation, not embedded as clickable citations in these Markdown files. Before external publication, independently re-open and verify source documents, publication dates and exact wording.

## 4. Evidence vs inference vs hypothesis

### Publicly supported facts
- The job description explicitly identifies package-damage loss prevention as a role responsibility.
- Public e-commerce and logistics reports describe a high-volume operating context and existing industry use of tracking, alerts and incident workflows.
- Public disclosures indicate that damaged deliveries can create customer-protection and reimbursement exposure.

### Reasonable design inferences
- Event histories and shipment attributes are useful inputs for operational investigation.
- Rates normalized by processed shipment volume are more informative than raw incident counts when comparing groups.
- Human review and traceable case outcomes are necessary for operational decisions.

### Hypotheses to test in synthetic scenarios (not claims about Mercado Libre)
- H1: confirmed damage incidents may cluster around particular journey stages or event sequences.
- H2: some facilities may show unusual damage rates relative to a suitable baseline.
- H3: carrier-level differences may remain after controlling for product mix, route/zone and volume.
- H4: some product/packaging profiles may have higher damage incidence.
- H5: event patterns may provide early warning signals before an incident is confirmed.
- H6: prioritizing alerts by risk and potential impact may make a fixed investigation capacity more productive.

## 5. Core analytical principles

- Compare rates, not only counts.
- Use appropriate denominators and minimum-volume thresholds.
- Separate correlation from causation.
- Account for product mix, shipment characteristics, geography, time and operational stage where possible.
- Treat missing or delayed event data as a data-quality issue, not automatically as suspicious behavior.
- Keep anomaly scores distinct from damage probabilities.
- Keep suspected irregularity distinct from confirmed fraud.
- Preserve event chronology and auditability.

## 6. Target users

- Loss-prevention analyst: triages alerts and investigates shipments.
- Operations manager: monitors facilities, stages and operational patterns.
- Carrier-performance analyst: investigates adjusted differences and recurring exceptions.
- Continuous-improvement team: tracks interventions and subsequent changes.

## 7. Scope boundaries

In scope:
- Synthetic shipment and event data.
- Operational data model and repeatable pipeline.
- Damage KPI monitoring.
- Statistical anomaly detection.
- Experimental unsupervised anomaly scoring.
- Alert triage and investigation workflow.
- Experimental returns-pattern monitoring, clearly secondary.
- Reproducible evaluation on held-out synthetic scenarios.

Out of scope:
- Real Mercado Libre data or internal system access.
- GRID integration or claims of GRID compatibility.
- Actual fraud decisions.
- Carrier fault attribution.
- Supervised damage prediction trained on invented labels.
- Production computer vision.
- Claims of real savings or real-world model performance.
