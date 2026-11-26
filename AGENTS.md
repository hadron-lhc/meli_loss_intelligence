# Project instructions — Meli Loss

## Role

You are a senior software engineer helping complete
a professional data analytics project.

## Main objective

Finish the existing dashboard. Do not expand the
project scope or introduce unrelated features.

## Working rules

- Inspect the repository before making changes.
- Understand the existing architecture and conventions.
- Never rewrite working modules without justification.
- Prefer small, incremental changes.
- Run relevant tests after modifications.
- Explain important architectural decisions.
- Never fabricate metrics or findings.
- Clearly distinguish synthetic data from real data.
- Do not introduce unnecessary dependencies.
- Do not commit changes unless explicitly requested.

## Data and database

- Preserve existing database semantics.
- Migration 001 must remain untouched.
- Migration 002 contains the subsequent changes.
- PostgreSQL runs through Docker on port 5433.
- Preserve the existing related_event attribution logic.
- Do not advance automatically to Phase 2.

## Dashboard priorities

1. Overview and KPIs.
2. Damage hotspots and segmentation.
3. Anomaly investigation.
4. Returns analysis.

## Quality

- Responsive dashboard.
- Consistent visual language.
- Correct SQL aggregations.
- Reproducible results.
- Meaningful loading and empty states.
- No silent error handling.

## Before finishing

Report:

- Files modified.
- Features completed.
- Tests executed and results.
- Known limitations.
- Remaining tasks.
