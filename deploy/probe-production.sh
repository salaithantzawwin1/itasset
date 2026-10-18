#!/usr/bin/env bash
# Post-deploy probe gate for 192.168.100.142:80 — the §7.3 checklist of
# docs/new/ITAM_Gap_Analysis_Report_v1.0.md, asserted as code.
#
#   bash deploy/probe-production.sh                        # default: http://192.168.100.142
#   SKIP_THROTTLE=1 bash deploy/probe-production.sh        # skip the 11-bad-logins probe
#   PROBE_USER=tech PROBE_PASS=... bash deploy/probe-production.sh   # + authed phase (me,
#                                      # org, create 201, idempotent replay, stale 409, cleanup)
#
# Exit code 0 = every check passed. The throttle probe burns THIS machine's
# /accounts/login/ budget for LOGIN_THROTTLE_WINDOW (300 s) — set
# SKIP_THROTTLE=1 if you need to log in right after. Read-only otherwise;
# with credentials it creates one PROBE-* asset and tries to delete it again.
set -uo pipefail

BASE="${1:-http://192.168.100.142}"
PASS_N=0
FAIL_N=0
WARN_N=0

check() { # name want got
  if [[ "$3" == "$2" ]]; then
    printf 'ok    %-58s (%s)\n' "$1" "$3"
    PASS_N=$((PASS_N + 1))
  else
    printf 'FAIL  %-58s want=%s got=%s\n' "$1" "$2" "$3"
    FAIL_N=$((FAIL_N + 1))
  fi
}
check_one_of() { # name "want1|want2" got
  if [[ "|$2|" == *"|$3|"* ]]; then
    printf 'ok    %-58s (%s)\n' "$1" "$3"
    PASS_N=$((PASS_N + 1))
  else
    printf 'FAIL  %-58s want=%s got=%s\n' "$1" "$2" "$3"
    FAIL_N=$((FAIL_N + 1))
  fi
}
warn() {
  printf 'WARN  %s\n' "$1"
  WARN_N=$((WARN_N + 1))
}
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }
body() { curl -s --max-time 20 "$@"; }
headers() { curl -sI --max-time 20 "$@"; }

echo "== phase 1: anonymous probes against $BASE =="

check "/healthz" 200 "$(http_code "$BASE/healthz")"
if body "$BASE/healthz" | grep -qE '"db":[[:space:]]*"ok"'; then
  echo "ok    /healthz db ok"; PASS_N=$((PASS_N + 1))
else
  echo "FAIL  /healthz db ok missing"; FAIL_N=$((FAIL_N + 1))
fi
check "GET /" 200 "$(http_code "$BASE/")"
check "GET /admin/login/" 200 "$(http_code "$BASE/admin/login/")"
check "unknown path → generic 404" 404 "$(http_code "$BASE/definitely-not-a-route/")"

# The app homepage inlines its CSS; the Django admin links real /static/ assets.
STATIC_HREF="$(body "$BASE/admin/login/" | grep -oE '(href|src)="[^"]*static[^"]*\.css[^"]*"' \
  | head -1 | sed -E 's/^(href|src)="//; s/"$//')"
if [[ -n "$STATIC_HREF" ]]; then
  case "$STATIC_HREF" in
    http*) STATIC_URL="$STATIC_HREF" ;;
    /*) STATIC_URL="$BASE$STATIC_HREF" ;;
    *) STATIC_URL="$BASE/$STATIC_HREF" ;;
  esac
  check "static asset from homepage" 200 "$(http_code "$STATIC_URL")"
else
  echo "FAIL  static asset from homepage — no static href found in homepage HTML"
  FAIL_N=$((FAIL_N + 1))
fi

for p in /api/v1/assets/ /api/v1/me/ /api/v1/org/sites/ /api/v1/transfers/; do
  check "anon $p → 401" 401 "$(http_code "$BASE$p")"
done
check_one_of "anon /api/v1/schema/ → 401|403 (was 200!)" "401|403" "$(http_code "$BASE/api/v1/schema/")"
check_one_of "anon /api/v1/docs/ → 401|403 (was 200!)" "401|403" "$(http_code "$BASE/api/v1/docs/")"

if headers "$BASE/accounts/login/" | grep -qi '^content-security-policy:'; then
  echo "ok    HTML carries Content-Security-Policy"; PASS_N=$((PASS_N + 1))
else
  echo "FAIL  HTML carries Content-Security-Policy"; FAIL_N=$((FAIL_N + 1))
fi
if headers "$BASE/accounts/login/" | grep -qi '^x-content-type-options: *nosniff'; then
  echo "ok    X-Content-Type-Options: nosniff"; PASS_N=$((PASS_N + 1))
else
  echo "FAIL  X-Content-Type-Options: nosniff"; FAIL_N=$((FAIL_N + 1))
fi
CID="$(headers "$BASE/" | grep -i '^x-correlation-id:' | tr -d '\r' | awk '{print $2}')"
if [[ -n "$CID" ]]; then
  echo "ok    X-Correlation-ID present ($CID)"; PASS_N=$((PASS_N + 1))
else
  echo "FAIL  X-Correlation-ID present"; FAIL_N=$((FAIL_N + 1))
fi
ME_BODY="$(body "$BASE/api/v1/me/")"
if grep -q '"code"' <<<"$ME_BODY" && grep -q '"correlationId"' <<<"$ME_BODY"; then
  echo "ok    401 error body carries code + correlationId"; PASS_N=$((PASS_N + 1))
else
  echo "FAIL  401 error body carries code + correlationId"; FAIL_N=$((FAIL_N + 1))
fi

# --- throttle: 11 bad credential POSTs must end in 429 + Retry-After -------
if [[ "${SKIP_THROTTLE:-0}" == "1" ]]; then
  warn "throttle probe skipped (SKIP_THROTTLE=1)"
else
  JAR="$(mktemp)"
  http_code -c "$JAR" "$BASE/accounts/login/" >/dev/null
  CSRF="$(grep -E 'csrftoken' "$JAR" | awk '{print $NF}' | tail -1)"
  LAST="000"
  for _ in $(seq 1 11); do
    LAST="$(http_code -b "$JAR" -c "$JAR" \
      -H "X-CSRFToken: $CSRF" -H "Referer: $BASE/accounts/login/" \
      --data-urlencode 'username=probe-nonexistent' \
      --data-urlencode 'password=wrong-password' \
      "$BASE/accounts/login/")"
  done
  check "11 bad logins → 429 (per-IP cap)" 429 "$LAST"
  RA="$(curl -s -D - -o /dev/null --max-time 20 -b "$JAR" -c "$JAR" -H "X-CSRFToken: $CSRF" -H "Referer: $BASE/accounts/login/" \
    --data-urlencode 'username=probe-nonexistent' --data-urlencode 'password=wrong' \
    "$BASE/accounts/login/" | grep -i '^retry-after:' | tr -d '\r' | awk '{print $2}')"
  if [[ -n "$RA" ]]; then
    echo "ok    Retry-After: $RA (this IP is capped ~${RA}s)"; PASS_N=$((PASS_N + 1))
  else
    echo "FAIL  Retry-After header on the throttled response"; FAIL_N=$((FAIL_N + 1))
  fi
  rm -f "$JAR"
fi

# --- authenticated phase (needs PROBE_USER + PROBE_PASS) --------------------
if [[ -n "${PROBE_USER:-}" && -n "${PROBE_PASS:-}" ]]; then
  echo "== phase 2: authenticated probes as $PROBE_USER =="
  TOKEN="$(body -H 'Content-Type: application/json' \
    -d "{\"username\":\"$PROBE_USER\",\"password\":\"$PROBE_PASS\"}" \
    "$BASE/api/v1/auth/token/" \
    | sed -E 's/.*"token":[[:space:]]*"([^"]+)".*/\1/')"
  if [[ -z "$TOKEN" ]]; then
    echo "FAIL  could not obtain API token"; FAIL_N=$((FAIL_N + 1))
  else
    AUTH=(-H "Authorization: Token $TOKEN")

    check "GET /api/v1/me/ with token" 200 "$(http_code "${AUTH[@]}" "$BASE/api/v1/me/")"
    check "GET /api/v1/org/sites/ with token" 200 "$(http_code "${AUTH[@]}" "$BASE/api/v1/org/sites/")"
    check "bad ?ordering= → 400" 400 "$(http_code "${AUTH[@]}" "$BASE/api/v1/assets/?ordering=evil")"

    CAT_ID="$(body "${AUTH[@]}" "$BASE/api/v1/assets/" | grep -o '"category":{[^}]*}' | head -1 \
      | grep -o '"id":[0-9]*' | grep -oE '[0-9]+')"
    SITE_ID="$(body "${AUTH[@]}" "$BASE/api/v1/org/sites/" | grep -o '"id":[0-9]*' | head -1 \
      | grep -oE '[0-9]+')"
    TAG="PROBE-$(date +%s)"
    if [[ -n "$CAT_ID" && -n "$SITE_ID" ]]; then
      KEY="probe-$TAG"
      CREATE_BODY="{\"asset_tag\":\"$TAG\",\"category_id\":$CAT_ID,\"site_id\":$SITE_ID}"
      CODE1="$(http_code "${AUTH[@]}" -H "Content-Type: application/json" \
        -H "Idempotency-Key: $KEY" -d "$CREATE_BODY" "$BASE/api/v1/assets/")"
      check "POST /api/v1/assets/ → 201 (was a 500)" 201 "$CODE1"

      HDRS="$(curl -s -D - -o /dev/null "${AUTH[@]}" -H 'Content-Type: application/json' \
        -H "Idempotency-Key: $KEY" -d "$CREATE_BODY" "$BASE/api/v1/assets/")"
      CODE2="$(grep -m1 -oE 'HTTP/[0-9.]+ [0-9]+' <<<"$HDRS" | awk '{print $2}')"
      check "Idempotency-Key replay → 201" 201 "$CODE2"
      if grep -qi '^Idempotency-Replayed: *true' <<<"$HDRS"; then
        echo "ok    Idempotency-Replayed: true header"; PASS_N=$((PASS_N + 1))
      else
        echo "FAIL  Idempotency-Replayed: true header"; FAIL_N=$((FAIL_N + 1))
      fi
      COUNT="$(body "${AUTH[@]}" "$BASE/api/v1/assets/?q=$TAG" | grep -o '"count":[0-9]*' \
        | grep -oE '[0-9]+')"
      check "replay did not duplicate the asset" 1 "${COUNT:-0}"

      V="$(body "${AUTH[@]}" "$BASE/api/v1/assets/$TAG/" | grep -o '"version":[0-9]*' \
        | grep -oE '[0-9]+' | head -1)"
      check "new asset starts at version 1" 1 "${V:-0}"
      check "PATCH with stale version → 409" 409 \
        "$(http_code -X PATCH "${AUTH[@]}" -H 'Content-Type: application/json' \
          -d "{\"model_name\":\"stale\",\"version\":999}" "$BASE/api/v1/assets/$TAG/")"
      check "PATCH with current version → 200" 200 \
        "$(http_code -X PATCH "${AUTH[@]}" -H 'Content-Type: application/json' \
          -d "{\"model_name\":\"probe ok\",\"version\":$V}" "$BASE/api/v1/assets/$TAG/")"

      CLEAN="$(http_code -X DELETE "${AUTH[@]}" "$BASE/api/v1/assets/$TAG/")"
      if [[ "$CLEAN" == "204" ]]; then
        echo "ok    probe asset cleaned up (204)"; PASS_N=$((PASS_N + 1))
      else
        warn "probe asset $TAG not deleted (HTTP $CLEAN) — remove it manually if unwanted"
      fi
    else
      warn "no category/site id discoverable — skipping create/replay/version probes"
    fi
  fi
else
  warn "PROBE_USER/PROBE_PASS unset — authenticated phase skipped"
fi

echo
echo "== result: $PASS_N ok, $FAIL_N failed, $WARN_N warnings =="
[[ $FAIL_N -eq 0 ]]
