# Runbook — Break-Glass Login (Spec A §11.2, gap §3.6)

Break-glass = signing in with a **local** account when the normal path
(LDAP/AD) is unavailable or unusable. The system watches for it: with
`LDAP_ENABLED=1`, every local-backend sign-in writes an `ActivityLog` `login`
event (username, backend, IP — never the password) **and** emails the IT
lead (`templates/email/breakglass_login.txt`). This runbook is the
documented procedure, including the reason/incident capture.

> Note: production currently runs `LDAP_ENABLED=0`, where the local backend
> *is* the normal path — no alert fires and none should. This procedure
> applies whenever LDAP is (or is about to be) enabled.

## Procedure

1. **Confirm the trigger** — LDAP really is down/unusable (check the server
   and the gunicorn log), not just a wrong password.
2. **Get approval** — verbal or ticket approval from the IT lead *before*
   using the local account; if unreachable, proceed and notify immediately.
3. **Sign in** with the local account. The system then:
   - writes `ActivityLog` action=`login` with `backend=…ModelBackend` and the
     source IP (evidence, append-only — never edit it);
   - emails the IT lead "Break-glass login — local backend used".
4. **Capture the reason/incident** (this is the required record): within
   15 minutes create or append an incident entry containing
   - the ActivityLog event id + timestamp,
   - the `X-Correlation-ID` of the failing production requests that forced
     the break-glass (from the error body of the symptom),
   - **reason** (why the normal path was unusable) and **incident id** if one
     exists.
   The ActivityLog row is the *evidence*; the incident entry is the
   *reason capture* — both halves are required by §11.2.
5. **Restore the normal path** (fix LDAP / AD) and verify a normal login.
6. **Close the glass** — rotate the local credential and, if it exists only
   for emergencies, disable it again; note the rotation in the incident
   entry.
7. **Review** — at the incident review, confirm evidence: one `login` event,
   one alert email, one incident entry with reason.

## Evidence map

| What | Where | Written by |
|---|---|---|
| Login happened (who/when/backend/IP) | `ActivityLog` action=`login` | automatically |
| Alert that break-glass was used | email to `IT_LEAD_EMAIL` | automatically |
| Reason / incident reference | incident log (step 4) | **operator — required** |
| Credential rotation after use | incident log (step 6) | **operator — required** |

## Verifying with the authenticated probe (no echo)

The break-glass admin doubles as the probe account. Its credentials live
in `~/secrets/itasset-breakglass-admin.txt` **on the server only** (line 1
= username, line 2 = password) — never copy them into the repo, `.env`,
or a command line. Fetch them into the shell at the moment of use so they
appear in no command, shell history, or output:

```bash
PROBE_USER="$(ssh itasset-dev 'head -n1 ~/secrets/itasset-breakglass-admin.txt' | tr -d '\r\n')"
PROBE_PASS="$(ssh itasset-dev 'sed -n 2p ~/secrets/itasset-breakglass-admin.txt' | tr -d '\r\n')"
SKIP_THROTTLE=1 PROBE_USER="$PROBE_USER" PROBE_PASS="$PROBE_PASS" \
  bash deploy/probe-production.sh
```

`SKIP_THROTTLE=1` skips the probe's 11-bad-login phase so a run right
after the full gate does not burn this machine's login budget again
(the script prints which phase it skipped). Reference run
(2026-10-28): **27 ok / 0 failed** — token, `/me`, org sites, create
201, idempotent replay 201 + `Idempotency-Replayed: true`, stale 409,
cleanup 204.
