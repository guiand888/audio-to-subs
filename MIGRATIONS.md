# Manual database migrations

This document collects one-time manual SQL commands needed when the ORM model
changes but we deliberately do **not** ship an Alembic migration (e.g. for
homelab Docker/Podman deployments where recreating the database from scratch is
acceptable).

**Read this before deploying:** the application tolerates *extra nullable*
columns it no longer writes — but it does **not** tolerate a column it used to
write that is now `NOT NULL` with no default. If such a column lingers and the
app never writes it, every `INSERT` hits a `NOT NULL` violation. So these
commands are required, not optional, for the affected release — run them
**before** deploying the new code (or the new code will fail at runtime).

Run each command **once**, with the app/worker stopped so no process holds the
SQLite writer lock.

---

## Phase 2: drop the `progress_*` columns from `jobs` (REQUIRED)

Commit that removes these columns from the ORM: Phase 2 (Redis-only progress).
After this change the database no longer needs `progress_percent`,
`progress_message`, `progress_stage`, `progress_step_index`,
`progress_step_total`.

`progress_percent` is the dangerous one: in the legacy schema it is
`INTEGER NOT NULL` with **no `server_default`**. The ORM used to provide a
client-side `default=0`, but that default lives on the (now-removed) column, so
once the model stops writing the column, a lingering `NOT NULL` column makes
every job `INSERT` fail. The other four are `nullable=True` and are tolerated
if they linger, but drop them all for a clean schema.

**Deploy order:** run the DROP below *before* starting the new app/worker, or
recreate the database from scratch. (A NOT NULL violation during job creation
is deliberately surfaced as a real 500 by the API, not disguised as a 409, so
an un-migrated DB fails loudly rather than silently.)

**Prerequisites**

- SQLite ≥ 3.35 (required for `ALTER TABLE ... DROP COLUMN`). Check with
  `sqlite3 --version`.
- The app/worker containers are stopped.

**Database location**

In the compose setup the DB is at `/data/parolesub.db` inside the container,
mounted from a named volume (e.g. `parolesub_data`; see `docker-compose.yml`).

### Option A: on the host (if `sqlite3` is installed)

```bash
sqlite3 /data/parolesub.db <<'SQL'
ALTER TABLE jobs DROP COLUMN progress_percent;
ALTER TABLE jobs DROP COLUMN progress_message;
ALTER TABLE jobs DROP COLUMN progress_stage;
ALTER TABLE jobs DROP COLUMN progress_step_index;
ALTER TABLE jobs DROP COLUMN progress_step_total;
VACUUM;
SQL
```

### Option B: via a throwaway container (host has no `sqlite3`)

Use `--rm` so the container is removed automatically after it exits; the
volume (`parolesub_data`) is left untouched. Replace `parolesub_data` with the
actual volume name from `docker volume ls` if it differs.

```bash
docker run --rm \
  -v parolesub_data:/data \
  alpine:3.19 sh -c "apk add --no-cache sqlite && \
    sqlite3 /data/parolesub.db \
    'ALTER TABLE jobs DROP COLUMN progress_percent; \
     ALTER TABLE jobs DROP COLUMN progress_message; \
     ALTER TABLE jobs DROP COLUMN progress_stage; \
     ALTER TABLE jobs DROP COLUMN progress_step_index; \
     ALTER TABLE jobs DROP COLUMN progress_step_total; \
     VACUUM;'"
```

If you prefer not to pull `alpine`, any image shipping the `sqlite3` CLI works
the same way (mount the data volume, run the DROP statements, `--rm`).

### Verify

```bash
sqlite3 /data/parolesub.db "PRAGMA table_info(jobs);" | grep progress
# -> no output means the columns are gone
```

### Rollback

There is no down-migration file. To restore the columns, either recreate them
manually:

```sql
ALTER TABLE jobs ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN progress_message TEXT;
ALTER TABLE jobs ADD COLUMN progress_stage TEXT;
ALTER TABLE jobs ADD COLUMN progress_step_index INTEGER;
ALTER TABLE jobs ADD COLUMN progress_step_total INTEGER;
```

or restore a database backup taken before the drop.
