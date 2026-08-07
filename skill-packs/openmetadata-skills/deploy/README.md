# Running OpenMetadata locally

No compose file is vendored here, deliberately — and none needs to be. OpenMetadata's
deployment is four moving parts (server, relational database, search backend, ingestion
scheduler) whose topology is upstream's to change between releases, and the
`external/OpenMetadata` submodule already holds upstream's own compose files at the
pinned SHA. A copy in this pack would be a second deployment definition that silently
disagrees with the server it is pinned to.

## The pinned release

Server `1.13.3-release` (`external/OpenMetadata`), matching
`openmetadata-ingestion==1.13.3.0`. These move together
(openmetadata-rules.md rule 14), and `scripts/sync_submodules.py --check` fails if the
submodule tag and `SERVER_PIN` in the bridge disagree. The wheel carries a fourth
component the server tag does not.

## Runbook

```bash
# 0. the submodule, if this is a fresh clone (403 MB shallow — see the integration doc)
python3 scripts/sync_submodules.py --init

# 1. bring up upstream's own compose, from the pinned checkout. Podman is this
#    machine's runtime; the VM needs ~8 GiB — the search backend alone wants 2 GiB and
#    the default podman machine is smaller than that.
podman-compose -f external/OpenMetadata/docker/development/docker-compose-postgres.yml up -d

# 2. the UI, and the API the bridge talks to
open http://localhost:8585
export OPENMETADATA_SERVER_URL=http://localhost:8585/api
```

Upstream ships several variants next to it — `docker-compose.yml` (MySQL),
`docker-compose-postgres.yml`, `.redis.yml`, `.multiserver.yml`. Read them in the
submodule rather than trusting a description here; they are upstream's and they change.

## The token

Create an ingestion bot token in the UI (**Settings → Bots → ingestion-bot → Token**)
and export it. It never goes in a file:

```bash
export OPENMETADATA_AUTH_TOKEN=<the JWT>
```

Nothing in this repository writes a token to disk — not a generator, not a config, not
an MCP registration (rule 17). Every generated file uses `${OPENMETADATA_AUTH_TOKEN}`.

## Register the warehouse before pushing anything

The bundle's FQNs all begin with the Database Service name declared in the use-case's
`openmetadata.yml` (`enhanza_bigquery`, `example_duckdb`). Create a Database Service
with **exactly that name** — otherwise every FQN in the bundle resolves to nothing and
the push 404s on every request. `OPENMETADATA_DB_SERVICE` overrides the declared name
for a deployment that already named it something else.

Then, in order:

```bash
# tables, descriptions, dbt tests, model-level lineage — upstream's connector
pip install 'openmetadata-ingestion[dbt]==1.13.3.0'
metadata ingest -c skill-packs/dbt-skills/use-cases/<slug>/openmetadata/ingestion/dbt.yaml

# the enrichment layer — column lineage, glossary, tags. Explicit confirmation first.
python3 scripts/openmetadata_sync.py --use-case <slug> --push --dry-run
python3 scripts/openmetadata_sync.py --use-case <slug> --push
```

The order matters and is not cosmetic: a lineage edge whose endpoint table does not
exist is rejected, and a tag label naming a classification that does not exist is
rejected. Both are the correct signal that the connector has not run yet — which is
why the bridge does not create tables to paper over it.
