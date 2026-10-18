# Database

PostgreSQL 17, plain SQL: no ORM, no Alembic. `schema.sql` is the schema and
`seed.sql` is the catalog. Six tables hold the catalog: 15 **domains**, 10
**task types** with their build **steps**, 90 **projects**, and the
**technologies** each project lists.

```
domain ──< project >── task_type ──< task_step
             │
             └──< project_technology >── technology
```

Five more hold the accounts and what people do with the catalog: `app_user`
(email, bcrypt hash, role `user`/`admin`, `is_active`, `token_version`),
`refresh_session` (one signed-in device's rotating refresh token),
`workspace` and `workspace_member` (a team space and each member's
`viewer`/`operator`/`admin` role), `camera` (a source in a workspace, its
live pipeline and settings), `camera_event` (what a camera's pipeline raised,
and how it was handled), `user_project` (one user's status and notes on one
project), `ml_model` (Ultralytics weights someone uploaded), and
`inference_run` (one Vision Lab run, with its inputs, settings, progress and
results as JSONB).

```
app_user ──< user_project >── project
    │
    ├──< refresh_session
    ├──< workspace_member >── workspace ──< ml_model (shared, optional)
                                  └──< camera ──< camera_event ──< media_object (snapshot)
    ├──< ml_model ───────────── (project, optional)
    └──< inference_run ──────── (project, optional)
```

Ids are integers rather than UUIDs. The seeded projects keep the stable ids
1–90 that appear in URLs (`/projects/2/lab`) and in API responses.

## Layout

| Path | Runs when | Contents |
| --- | --- | --- |
| `schema.sql` | first boot, automatic | tables, constraints, indexes |
| `seed.sql` | first boot, automatic | the catalog (generated, do not edit) |
| `seed_data.json` | never, read by `generate_seed.py` | the catalog's source of truth, including each project's lab config |
| `generate_seed.py` | by hand | rewrites `seed.sql` from `seed_data.json` |
| `queries.sql` | never automatic | reference queries, annotated with the service and endpoint that issue them |

`docker-compose.yml` mounts `schema.sql` and `seed.sql` into
`/docker-entrypoint-initdb.d/` as `001_schema.sql` and `002_seed.sql`.
Postgres runs them **once**, in that order, on the first boot of an empty data
volume. Editing either file does nothing to a database that already exists; see
*Resetting* below. The whole folder is also mounted read-only at `/sql` in the
postgres container, for running files by hand.

Unlike lost-found, the seed *is* in initdb. lost-found seeds demo data, but
this seed is the catalog itself, and the app has nothing to show without it.

## Applying the schema

The compose stack does it for you:

```bash
docker compose up -d postgres
```

Against a database that already exists:

```bash
docker compose exec -T postgres psql -U atlas -d atlas < database/schema.sql
```

Every statement is `IF NOT EXISTS`, so re-applying is a no-op. A column added to
`schema.sql` later also has to be added to `SCHEMA_UPGRADES` in
`backend/app/core/database.py`. Those statements run on every API start, so
existing volumes get the column too.

## Seeding

To change the catalog, edit `seed_data.json` and regenerate:

```bash
python database/generate_seed.py      # writes seed.sql
docker compose exec -T postgres psql -U atlas -d atlas < database/seed.sql
```

Every insert is `ON CONFLICT DO NOTHING`, so loading the seed into an existing
database adds new rows and leaves edited ones alone. The admin account is not
seeded. The API creates it at startup from `ADMIN_EMAIL` / `ADMIN_PASSWORD`
(`backend/app/services/user_service.py:ensure_bootstrap_admin`).

## Resetting

Init scripts only run against an empty volume. To start over:

```bash
docker compose down -v      # drops pgdata (and atlas-data: weights, uploads, run outputs)
docker compose up -d --build
```

To drop only the database and keep downloaded models:
`docker compose down && docker volume rm vision-atlas_pgdata`.

## Connecting

| From | Host | Port | User / password | Database |
| --- | --- | --- | --- | --- |
| the host | `localhost` | 5432 | `atlas` / `atlas` | `atlas` |
| the api container | `postgres` | 5432 | `atlas` / `atlas` | `atlas` |

```bash
docker compose exec postgres psql -U atlas -d atlas
```

## Notes on the schema

- **Enums are `TEXT` + `CHECK`**, never Postgres `ENUM` types: `user_project.status`,
  `inference_run.status`, `app_user.role`, `ml_model.task`. The frontend's
  `src/utils/constants.js` mirrors them.
- **No triggers.** Services set `updated_at = NOW()` in their `UPDATE`s.
- **`project.lab` is JSONB.** It holds `{pipeline, support, params, samples,
  alternatives, note}`, and `NULL` means the project has no lab. Run `params`,
  `inputs` and `result` are JSONB too. The API's asyncpg pool decodes them to
  Python objects (see `_init_connection` in `core/database.py`).
- **Files are not in the database.** Run inputs and outputs live under
  `MEDIA_DIR/runs/<public_id>/`, and uploaded weights under `WEIGHTS_DIR/custom/`.
  The rows only hold paths and `/media` URLs.
- **`ON DELETE SET NULL`** on `inference_run.project_id` and `ml_model.project_id`:
  deleting a project from the catalog keeps people's run history and uploaded
  models.
