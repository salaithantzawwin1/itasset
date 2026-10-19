#!/usr/bin/env bash
# Backup for the IT Asset Manager (Spec A §12.3, gap §3.7 / sequence step 8).
# Runbook (schedule + restore + drill checklist): docs/runbooks/backup-restore.md
#
# Usage:
#   bash deploy/backup.sh                 # default target ~/itasset-backups
#   bash deploy/backup.sh /mnt/backups    # explicit target directory
#
# Produces, per run:
#   <target>/itasset-<UTCstamp>.dump          pg_dump --format=custom (DB)
#   <target>/attachments-<UTCstamp>.tar.gz    private attachment files
# and keeps the newest 14 of each. Needs pg_dump on PATH — or a running
# Docker Postgres (pg_dump resolves inside the container, which is how the
# LAN deployment runs its db) — and DATABASE_URL in the environment or in
# ~/itasset/.env (override with ENV_FILE=...).
set -euo pipefail

TARGET="${1:-$HOME/itasset-backups}"
ENV_FILE="${ENV_FILE:-$HOME/itasset/.env}"
KEEP="${KEEP:-14}"

if [[ -z "${DATABASE_URL:-}" && -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL not set and not found in $ENV_FILE" >&2
  exit 1
fi
PG_CONTAINER=""
if ! command -v pg_dump >/dev/null; then
  # No client tools on the host: dump through the Docker db container
  # (BACKUP_PG_CONTAINER overrides auto-detection).
  if command -v docker >/dev/null; then
    PG_CONTAINER="${BACKUP_PG_CONTAINER:-$(docker ps --filter 'ancestor=postgres' --format '{{.Names}}' | head -1)}"
  fi
fi
if ! command -v pg_dump >/dev/null && [[ -z "$PG_CONTAINER" ]]; then
  echo "error: pg_dump not on PATH and no Docker postgres container found" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$TARGET"

echo "-> pg_dump -> $TARGET/itasset-$STAMP.dump"
if command -v pg_dump >/dev/null; then
  pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner \
    --file="$TARGET/itasset-$STAMP.dump"
else
  PG_USER="$(sed -E 's#^postgresql://([^:/]+).*#\1#' <<<"$DATABASE_URL")"
  PG_DB="${DATABASE_URL##*/}"
  PG_DB="${PG_DB%%\?*}"
  echo "   (via docker container: $PG_CONTAINER)"
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" --format=custom --no-owner "$PG_DB" \
    > "$TARGET/itasset-$STAMP.dump"
fi

PRIV_DIR="${PRIVATE_MEDIA_ROOT:-$HOME/itasset/private_attachments}"
if [[ -d "$PRIV_DIR" ]]; then
  echo "-> tar     -> $TARGET/attachments-$STAMP.tar.gz"
  tar -czf "$TARGET/attachments-$STAMP.tar.gz" \
    -C "$(dirname "$PRIV_DIR")" "$(basename "$PRIV_DIR")"
else
  echo "warning: $PRIV_DIR missing - attachments NOT backed up" >&2
fi

echo "-> pruning (keep $KEEP newest of each)"
ls -1t "$TARGET"/itasset-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
ls -1t "$TARGET"/attachments-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "done - newest artifacts:"
ls -1t "$TARGET" | head -4
