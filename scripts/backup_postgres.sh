#!/bin/sh
set -eu

backup_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="/backups/thermoform-${backup_timestamp}.dump"
pg_dump --format=custom --compress=9 --file="${backup_path}"
pg_restore --list "${backup_path}" >/dev/null
sha256sum "${backup_path}" >"${backup_path}.sha256"
printf '%s\n' "Verified PostgreSQL backup: ${backup_path}"
