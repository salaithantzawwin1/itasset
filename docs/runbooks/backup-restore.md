# Runbook — Backup & Restore (Spec A §12.3, gap §3.7 / sequence step 8)

Status: **script + procedure in repo (2026-10-17); first production drill
PASSED 2026-10-19** (evidence below) — restores are now proven on this host.
The nightly systemd timer is not yet installed (needs admin `sudo`); until it
is, run `bash deploy/backup.sh` manually or via the user's own crontab.

## What is backed up

| Artifact | How | Frequency |
|---|---|---|
| PostgreSQL database (`itasset`) | `deploy/backup.sh` → `pg_dump --format=custom` | daily |
| Private attachments (`~/itasset/private_attachments`) | same script → `tar.gz` | daily |
| `.env` (secrets!), `staticfiles` | **not** in the script — copy them once into the backup target after first run; secrets go to the password manager, not only to disk | on change |

Target directory: `~/itasset-backups` on the app host (move it to another
machine/NAS weekly — a backup on the same disk as the source is not a backup).
Retention: newest **14** of each (`KEEP=…` overrides).

## Schedule (systemd, on the server)

```bash
sudo tee /etc/systemd/system/itasset-backup.service <<'EOF'
[Unit]
Description=IT Asset Manager backup (Spec A §12.3)
[Service]
Type=oneshot
User=glgadmin
ExecStart=/bin/bash /home/glgadmin/itasset/deploy/backup.sh
EOF
sudo tee /etc/systemd/system/itasset-backup.timer <<'EOF'
[Unit]
Description=Nightly IT Asset Manager backup
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF
sudo systemctl enable --now itasset-backup.timer
```

Verify: `systemctl list-timers itasset-backup.timer`; `journalctl -u itasset-backup.service -n 20`.

## Restore procedure (point-in-time, into a fresh database)

```bash
# 1. stop writers (avoid a torn state while restoring)
sudo systemctl --user stop itasset-gunicorn

# 2. restore the dump into a NEW database (never overwrite in place)
sudo -u postgres createdb itasset_restore
pg_restore --dbname=postgresql://itasset:itasset@127.0.0.1:5432/itasset_restore \
           --no-owner ~/itasset-backups/itasset-<STAMP>.dump

# 3. attachments back into the app's private store
tar -xzf ~/itasset-backups/attachments-<STAMP>.tar.gz -C /home/glgadmin/

# 4. point the app at the restored DB (swap DATABASE_URL in ~/itasset/.env),
#    apply any migrations newer than the dump, then:
systemctl --user start itasset-gunicorn
curl -fsS http://127.0.0.1:8001/healthz          # {"status":"ok","db":"ok"}
# 5. spot-check counts: assets, people, ActivityLog rows vs the expectation
```

Rollback = swap `DATABASE_URL` back and restart. Keep the old database until
the incident is closed.

## Drill checklist (run quarterly, or after any backup-related change)

- [x] `bash deploy/backup.sh` exits 0 and both artifacts exist
- [x] restore into `itasset_restore` completes without errors
- [x] `/healthz` ok on the restored instance; asset + user counts match
- [ ] a sampled attachment downloads through the app (authorized download view)
  — *N/A 2026-10-19: zero files in `private_attachments/`, nothing to sample;
  re-run this row once real attachments exist*
- [x] record date, operator and result here:

| Date | Operator | Result | Notes |
|---|---|---|---|
| 2026-10-19 | Buffy (Codebuff, automated deploy) | **PASS** (rows 1–3; row 4 N/A) | dump `itasset-20261019T041805Z.dump` + attachments tar produced (exit 0); restore into `itasset_restore` clean; counts match exactly (assets 51, users 3, people 5, assignments 1, activity 14); `/healthz` → `ok` on a throwaway instance pointed at the restored DB; `.env` copied to the backup target. Timer still owed (admin). |
