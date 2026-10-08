#!/bin/sh
# Writes the PgBouncer auth file from PostgreSQL's own SCRAM verifier, so no plaintext password is stored and nothing is typed.
# Run from deploy/homelab with the stack's Postgres up:   ./pgbouncer/make-userlist.sh
# Output: .env.pgbouncer-userlist (mode 0600, gitignored by .env.*). Re-run after any change to the database password.
set -eu
umask 077
USER_NAME="${POSTGRES_USER:-reachy}"
VERIFIER=$(docker compose -p reachy-homelab --env-file .env exec -T postgres psql -U "$USER_NAME" -d postgres -Atc "select rolpassword from pg_authid where rolname='$USER_NAME'")
case "$VERIFIER" in SCRAM-SHA-256\$*) ;; *) echo "unexpected password format for $USER_NAME (not SCRAM-SHA-256); stopping" >&2; exit 1;; esac
printf '"%s" "%s"\n' "$USER_NAME" "$VERIFIER" > .env.pgbouncer-userlist
echo "wrote .env.pgbouncer-userlist ($(wc -c < .env.pgbouncer-userlist) bytes)"
