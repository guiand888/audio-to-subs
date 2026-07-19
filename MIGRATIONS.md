# Manual database migrations

This document collects one-time manual SQL commands needed when the ORM model
changes but we deliberately do **not** ship an Alembic migration (e.g. for
homelab Docker/Podman deployments where recreating the database from scratch is
acceptable). The application is written to tolerate "extra" columns it no
longer knows about, so you can deploy the new code first and run these
commands at your leisure.

Run each command **once**, with the app/worker stopped so no process holds the
SQLite writer lock.

---

## Phase 2: drop the `progress_*` columns from `jobs`

Commit that removes these columns from the ORM: Phase 2 (Redis-only progress).
After this change the database no longer needs `progress_percent`,
`progress_message`, `progress_stage`, `progress_step_index`,
`progress_step_total`. The app ignores them if they linger, but dropping them
keeps the schema clean.

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
