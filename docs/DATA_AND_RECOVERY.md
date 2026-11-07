# Data persistence, database availability and backup

[Docs index](README.md) / [data lineage](architecture/COMPONENTS.md#persistent-lineage) /
[operations](OPERATIONS.md) / [Terraform recovery](TERRAFORM_STATE.md)

## What survives what

| Data / execution | Location and lifetime |
| --- | --- |
| Environments and accepted provider scope | PostgreSQL; persisted lifecycle is not live VM/model health. |
| Model/inference configurations and deployment revisions | PostgreSQL versioned records. Saves do not change traffic; referenced configurations cannot be deleted. |
| Run inputs, status, cancellation requests and result reports | PostgreSQL; accepted definitions/configurations are copied into immutable snapshots. |
| Saved comparisons | PostgreSQL report/revision lineage and comparison data. |
| Interactive Exercise history | Browser session only; clears on refresh/close. Not a database archive or backup. |
| API executor futures | Process memory. A restart can leave persisted nonterminal runs/locks; automatic restart recovery is not certified. |
| Terraform state, attempt capabilities and leases | Private state Blob/local worker protocol; separate from database records. Never public artifacts. |
| Functions history/package | Private host storage and verified ZIP; versioned orchestration history is distinct from API runs. |
| Model weights/cache and vLLM process | GPU VM disk/runtime or local Ollama. Not authoritative for report/configuration retention. |

API run submission creates `RetentionClass.PERSISTED` reports. Public reads
exclude session-ephemeral runs and project only safe fields. DB retention does
not mean immutable storage or a tested recovery point.

## Database availability

The control plane uses **Azure Database for PostgreSQL Flexible Server**, with
private network access, not Azure SQL serverless. There is no repository
`autoPauseDelay` or idle-auto-pause configuration and no runtime database stop
automation in the checked-in application. Flexible Server supports explicit
management-plane **stop/start**; the service's stop limit can also restart a
stopped server. That is distinct from Azure SQL idle auto-pause and from external
subscription/demo shutdown automation.

The existing demo database was observed Ready with persisted reports intact on
**2026-11-07**. Its earlier unavailability was traced to an administrative stop
from an external scheduler, not application idle pause. A permanent always-on
exemption has not been established for the managed demo. A supported temporary
resource-scoped exemption was applied and verified; its expiry is managed
privately. These docs do **not** claim indefinite availability or permanently
disabled shutdown scheduling.

When availability is required, inspect the exact server's Activity Log for stop,
start and management actions and identify the owning shutdown schedule/policy.
Use a subscription-owner-approved always-on setup or supported exemption for the
exact database scope, and verify any exemption's expiry. Do not invent a
PostgreSQL auto-pause property, disable tenant protection,
revoke another system's identity or create an endless “start server” loop.
Keep external policy state and reviewed Terraform/operator inputs aligned.

`/healthz` only answers API liveness. `/readyz` performs a bounded real database
probe and returns 503 on failure/timeout; it does not distinguish stopped from
DNS/network/auth failures and cannot prove migrations or model warmth.
Alert on database availability and verify an approved restart with readiness
before traffic. An “always available” claim additionally needs verification that
the external stop automation no longer targets the server.

## Schema and reference data

[`backend/docker-entrypoint.sh`](../backend/docker-entrypoint.sh) runs
`alembic upgrade head`, then all four stable-ID seed commands before Uvicorn.
Startup fails if migration/seeding fails. This ordering does not make concurrent
schema upgrades/restarts a safe release; review database compatibility first.

Seeds are upserts, not backup restores: they can reapply checked-in catalog,
golden/benchmark and performance definitions. Do not use seeding to recover user
configurations/reports or assume edits to a seeded definition will survive a
restart. Accepted run snapshots protect already accepted input semantics.

## Private backup and restore checklist

[`infra/control/main.tf`](../infra/control/main.tf) declares **seven days**
PostgreSQL backup retention and **no geo-redundant backup**. This is a source
default, not verification of live retention, point-in-time recoverability or a
restore test. Confirm actual backup settings/recovery window for the chosen
server privately.

Before a release or recovery, retain an encrypted, access-controlled backup of
database data plus the migration revision, reviewed source SHA, image digests,
Functions ZIP hash, private operator inputs and state checkpoints. Preserve
configuration, revision, run, report and comparison relationships together.
Keep a second independent private state checkpoint; GPU disk snapshots alone
cannot recover control-plane data. Do not put dumps, plans, tfvars, logs, lease
IDs or tokens in Git/CI artifacts/chat.

Test restore into an **isolated approved** database, never over the serving
database. Verify schema revision, foreign-key relationships, sampled immutable
snapshots/report counts, operator ownership and public redaction before calling
the backup usable. Select recovery-point/time objectives explicitly; the repo
does not certify them or provide an automated general database restore command.
Preserve prior backups until the new recovery path is verified.

An app rollback is not a schema downgrade. Restore/rollback must preserve
compatibility, avoid changing saved history and use the normal approved operator
path. Failed Terraform state persistence additionally needs
[owner-safe lease recovery](TERRAFORM_STATE.md#persistence-failure-response);
database restoration does not release its lease.

Sources: [`entities`](../backend/src/domain),
[`run acceptance`](../backend/src/api/routes/runs.py),
[`readiness`](../backend/src/persistence/db.py),
[`configuration deletion`](../backend/src/api/routes/configurations.py),
[`control database`](../infra/control/main.tf).
