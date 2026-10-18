# Runbook — Incident Response (Spec A §16, gap step 8)

First rule: note the time and the `X-Correlation-ID` of any failing response —
since 2026-10-17 every API response carries one and every error body repeats
it (`correlationId`), so one id is enough to find the request in the logs.

## Symptom → first checks

| Symptom | Check | Action |
|---|---|---|
| Site down | `systemctl --user status itasset-gunicorn`; `systemctl status nginx`; `journalctl -u itasset-gunicorn -n 50` | restart gunicorn user unit; nginx via `sudo bash ~/itasset/deploy/install-nginx.sh` if config drifted |
| `/healthz` not ok | `db":"ok"` missing → Postgres down or `DATABASE_URL` wrong | `sudo systemctl status postgresql`; restore DB (backup-restore.md) |
| Logins suddenly 429 | throttle counters (per-IP, 10 fails / 5 min) | expected under attack — victims wait `Retry-After` seconds; raise `LOGIN_THROTTLE_ATTEMPTS` in `.env` only after checking the audit log for the source |
| Logins fail but no 429 | `ActivityLog` `login_failed` rows; LDAP server reachable (`LDAP_ENABLED=1`)? | break-glass: local account (ModelBackend) still works — it **emails the IT lead** and is audited (`login` event with `backend`) |
| Redis down | `redis-cli ping`; gunicorn logs show "login throttle: cache unavailable" | safe by design: throttle fails **open**; fix Redis; login stays available |
| Suspicious logins | `ActivityLog` `login` / `login_failed` with IP; break-glass emails | deactivate the account (session revoked next request), rotate password, revoke API tokens (`Token.objects` via admin) |
| 413 on uploads | nginx `client_max_body_size` (30m) vs app cap (25 MB) | re-run `deploy/install-nginx.sh`; do not raise the app cap casually |
| 5xx on one endpoint | the `correlationId` from the error body → grep gunicorn log | fix forward; asset data conflicts show as 409 (version conflict) — re-read and retry |
| Backup failed | `journalctl -u itasset-backup.service -n 50`; target disk space | fix before EOD; a missed day is not recoverable later |
| Suspected data loss | last good backup in `~/itasset-backups` | restore into a fresh DB (backup-restore.md) — never in place |

## Escalation notes

- **Do not delete audit rows.** `ActivityLog` is append-only evidence (§9.1);
  the monthly purge task is the only deleter.
- **Treat 409 storms as a client bug**, not an outage: since workstream 7 a
  stale `version` or an `Idempotency-Key` misuse answers 409 by design.
- Post-incident: add the correlation ids and timeline to
  `docs/itasset-docs/docs/PROGRESS.md` session notes.
