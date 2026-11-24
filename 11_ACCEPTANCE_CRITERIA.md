# 11 — Phase Gates & Acceptance Criteria

## Gate 0 — Design review
- [ ] Agent has read the complete context pack.
- [ ] Agent has inspected existing repository/environment.
- [ ] Agent has identified schema/architecture risks.
- [ ] Agent has proposed a phased plan.
- [ ] No code/data/dashboard generated before approval.

## Gate 1 — Foundation/database
- [ ] Fresh clone can start PostgreSQL using documented commands.
- [ ] Schema applies cleanly to an empty database.
- [ ] Constraints and foreign keys are tested.
- [ ] Environment variables documented; no secrets committed.
- [ ] Unit/integration tests pass.

## Gate 2 — Synthetic data/pipeline
- [ ] Same seed/config produces same logical data.
- [ ] All foreign keys resolve.
- [ ] Event sequence constraints pass.
- [ ] Confirmed incidents have required timestamps.
- [ ] Returns link to shipments.
- [ ] Truth labels isolated from operational data.
- [ ] No leakage fields in model feature tables.
- [ ] Generator supports reset/rebuild safely.

## Gate 3 — Analytics
- [ ] Damage rate counts distinct affected shipments.
- [ ] Denominators are documented and consistent.
- [ ] Low-volume groups are suppressed or flagged.
- [ ] Currency is handled correctly.
- [ ] Incident concentration is not confused with damage rate.
- [ ] KPI tests include edge cases.

## Gate 4 — Detection
- [ ] Statistical baseline implemented and explained.
- [ ] Alerts show observed and baseline numerator/denominator/rate.
- [ ] Minimum-volume and uncertainty logic tested.
- [ ] Isolation Forest adds measurable value or its lack of value is documented.
- [ ] Evaluation uses held-out synthetic scenarios.
- [ ] No truth leakage.

## Gate 5 — Dashboard
- [ ] Persistent synthetic-data disclaimer.
- [ ] Overview, hotspots, alerts, shipment explorer and investigation pages work.
- [ ] User can drill from alert to shipments/events.
- [ ] Investigation updates persist.
- [ ] KPI definitions and denominators visible.
- [ ] Returns page clearly says review signal, not fraud determination.
- [ ] UI has loading, empty and error states.

## Gate 6 — Delivery
- [ ] README supports fresh setup.
- [ ] Architecture and data dictionary are current.
- [ ] Demo walkthrough uses a reproducible seed.
- [ ] Screenshots come from actual running app.
- [ ] All tests and lint pass.
- [ ] Limitations and synthetic nature clearly disclosed.
