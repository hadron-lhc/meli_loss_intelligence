# Deployment (low Cloudflare usage)

This project is a Streamlit application backed by PostgreSQL. For a low-traffic demo
with minimal Cloudflare consumption, the suggested starting point is Streamlit
Community Cloud for the app and Neon Free for PostgreSQL. Cloudflare can remain outside
the request path. Community Cloud assigns a `streamlit.app` URL; this setup does not
provide a custom domain through Cloudflare.

This is a demo setup, not a production availability commitment. Community Cloud can
sleep an inactive app and has shared resource limits. Neon Free currently includes
100 compute-hours and 1 GB of database storage per project, with usage limits that can
change. Check each provider's current usage page before importing the full dataset.

## App configuration

Community Cloud recognizes the repository's `uv.lock` for dependency installation.
Use `src/loss_intelligence/app/streamlit_app.py` as the app entrypoint and Python 3.13
to match `.python-version`.

In the app's Secrets settings, add root-level values (never commit these values):

```toml
APP_ENV = "production"
DATABASE_URL = "postgresql+psycopg://<user>:<password>@<host>/<database>?sslmode=require"
LOG_LEVEL = "INFO"
DB_ECHO = "false"
```

The Streamlit entrypoint copies scalar root-level secrets into the environment before
the application's Pydantic settings are loaded. Existing environment variables take
precedence. `APP_ENV=production` also enables the existing guard against destructive
database resets.

Set the app's visibility to private unless a public demo is intended. The app writes
investigation and alert triage changes, so anyone allowed into the app can persist
changes to the shared demo database.

## Database bootstrap

Create the Neon database, then apply migrations with the same `DATABASE_URL` configured
for the app:

```bash
APP_ENV=production DATABASE_URL='postgresql+psycopg://…?sslmode=require' \
  uv run python -m loss_intelligence.db.migrate --database main
```

For an empty demo database, generate and validate a synthetic dataset, then load it:

```bash
uv run python -m loss_intelligence.synthetic.cli --profile fixture --output-dir data/generated
uv run python -m loss_intelligence.ingestion.validation --data-dir data/generated
APP_ENV=production DATABASE_URL='postgresql+psycopg://…?sslmode=require' \
  uv run python -m loss_intelligence.ingestion.loader --data-dir data/generated --database main --no-reset
```

The loader normally truncates its target before loading. The command above uses
`--no-reset` against a newly created, empty demo database because production mode refuses
destructive resets. Migration `001` remains unchanged; schema changes continue through the
existing later migrations.

## Cloudflare cost boundary

Do not deploy the Streamlit process as an always-on Cloudflare Container to minimize
usage. The $5 Workers Paid plan includes finite container memory, disk, and CPU allotments;
an instance that remains active can exceed the included memory-hours. Cloudflare Workers
Paid is also separate from the zone/DNS plan. Keeping requests on the provider's
`streamlit.app` hostname avoids routing dashboard interactions through a Worker.

If a custom domain becomes a requirement, choose a hosting plan that supports it and
estimate its cost separately before changing DNS. A Cloudflare Tunnel requires a running
origin host and does not provide that host or PostgreSQL by itself.
