# Dashboard

> Independent proof of concept. Synthetic data only. Not affiliated with or endorsed by Mercado Libre.

Phase 5 adds a Streamlit dashboard on top of the analytics and detection layers.
Every page keeps the synthetic-data notice visible and shows the denominator or
definition behind each metric.

## Run

```bash
make up
make migrate
make load
make detect-validation
make dashboard
```

Open `http://localhost:8501`. Use `DASHBOARD_PORT=...` to change the port.

The sidebar can switch between the `main` and `test` databases. The analysis
window, minimum-volume threshold, maturity horizon and confidence level are
shared across the operations pages.

## Pages

| Page | Purpose |
|---|---|
| Operations Overview | Processed shipments, confirmed incidents, damage rate, damages per 1,000, estimated loss by currency, open alerts, backlog, trend and data quality. |
| Damage Hotspots | Facility, carrier, carrier-zone, zone, category, packaging and stage rates with denominators, Wilson intervals, incident share, low-volume flags and optional previous-period comparison. |
| Alerts & Anomalies | Filters by status, priority, type and generated date; observed/baseline rates, explanation, evidence and shipment drill-down. |
| Shipment Explorer | Search by shipment code or ID, inspect characteristics, chronological events, incidents and associated alerts. |
| Investigation Workspace | Create an investigation from an alert, record status, outcome, notes and recommended action, and review the append-only audit trail. |
| Returns Intelligence | Return volume, declared reasons, inspection outcomes, repeat-return and discrepancy signals. Review signals only; not a fraud determination. |
| Model & Evaluation | Detection runs, held-out validation metrics and the documented absence of an Isolation Forest comparison. |

## Architecture

- `src/loss_intelligence/app/repository.py` contains the SQL and write logic.
- `src/loss_intelligence/app/cache.py` contains Streamlit cache wrappers. Read
  queries have a 60-second TTL; investigation writes clear the data cache.
- `src/loss_intelligence/app/views/` contains page renderers only.
- `src/loss_intelligence/app/components.py` contains the persistent disclaimer,
  sidebar controls and shared formatting helpers.
- `src/loss_intelligence/app/streamlit_app.py` is the entrypoint and navigation.

The dashboard never reads `evaluation.*` for operational pages. Only the Model &
Evaluation page uses held-out scenario truth, through the existing evaluation
module.

## Investigation writes

- Creating an investigation sets the alert to `investigating` and stores the
  reviewer as `demo_reviewer (synthetic)`.
- Closing or dismissing requires an outcome.
- The database triggers write status and outcome changes to
  `investigation_audit`; the UI does not maintain a separate audit log.
- Closing sets the alert to `resolved`; dismissing sets it to `dismissed`.

## Limitations

- All records are synthetic. No real Mercado Libre data, customers, carriers or
  loss claims are used.
- Alerts are review signals, not incident confirmations, fraud findings or
  carrier culpability conclusions.
- Isolation Forest is not implemented, so no incremental-value claim is made.
- Synthetic evaluation metrics do not establish real-world performance.
