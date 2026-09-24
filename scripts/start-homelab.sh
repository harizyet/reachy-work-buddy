#!/usr/bin/env bash
# Start the homelab stack (Postgres, reachy-hub, companion-core, Caddy —
# plus reachy-embodiment and Mailpit only with --simulation). See
# docs/phase-22-23.md's "Bash launcher contract" and AGENTS.md's Dev setup
# section for the docker compose/buildx prerequisites this assumes.
#
# Usage: scripts/start-homelab.sh [--env-file PATH] [--no-browser] [--check]
#                                  [--project NAME] [--build] [--simulation]
#                                  [--help]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

COMPOSE_DIR="${SCRIPT_DIR}/../deploy/homelab"
DEFAULT_ENV_FILE="${COMPOSE_DIR}/.env"
PROJECT_NAME="reachy-homelab"
DO_BUILD=0
SIMULATION=0

print_help() {
    cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [options]

Starts the homelab Docker Compose stack (Postgres, reachy-hub,
companion-core, Caddy). Production mode (the default) does not start
reachy-embodiment or Mailpit — those are dev/simulation-only, see
deploy/homelab/docker-compose.yml's "simulation" profile comments.

Options:
  --project NAME    Compose project name (default: ${PROJECT_NAME}).
  --build           Rebuild images before starting (first-time install/
                     after a code change; routine restarts don't need it).
  --simulation      Also start reachy-embodiment (simulated) and Mailpit,
                     for local development without real hardware/SMTP.
EOF
    print_common_help
}

# --- parse args ---------------------------------------------------------
parse_common_args "$@"
REMAINING=("${COMMON_REMAINING_ARGS[@]}")
i=0
while [[ $i -lt ${#REMAINING[@]} ]]; do
    arg="${REMAINING[$i]}"
    case "$arg" in
        --project)
            i=$((i + 1))
            [[ $i -lt ${#REMAINING[@]} ]] || die "--project requires a name argument"
            PROJECT_NAME="${REMAINING[$i]}"
            ;;
        --project=*)
            PROJECT_NAME="${arg#--project=}"
            ;;
        --build)
            DO_BUILD=1
            ;;
        --simulation)
            SIMULATION=1
            ;;
        --help)
            print_help
            exit 0
            ;;
        *)
            die "unknown argument: $arg (see --help)"
            ;;
    esac
    i=$((i + 1))
done

ENV_FILE="${COMMON_ENV_FILE:-$DEFAULT_ENV_FILE}"

# --- prerequisites -------------------------------------------------------
require_cmd docker "Install Docker, then see AGENTS.md's Dev setup section for the compose/buildx plugins."
if ! docker compose version >/dev/null 2>&1; then
    die "docker compose (v2 plugin) not found. See AGENTS.md's Dev setup section for the no-root install snippet."
fi
if ! docker buildx version >/dev/null 2>&1; then
    die "docker buildx not found — every Dockerfile here needs BuildKit. See AGENTS.md's Dev setup section."
fi

if [[ ! -f "$ENV_FILE" ]]; then
    die "env file not found: $ENV_FILE (copy deploy/homelab/.env.example to .env and set a real POSTGRES_PASSWORD, or pass --env-file)"
fi
read_env_file "$ENV_FILE"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in $ENV_FILE}"

# Phase 24 cleanup: SEARXNG_SECRET_KEY is an internal deployment secret for
# the bundled SearXNG container, not a user credential — it should not be
# something an ordinary operator has to invent or paste into .env. If .env
# already sets one (e.g. a shared value across hosts), that wins; otherwise
# generate and persist one, gitignored (matches `.env.*` in .gitignore) next
# to the other per-deployment secret file (.env.secret-keys.json).
# Exported shell env vars take precedence over --env-file for compose's own
# ${VAR} interpolation, so this doesn't require writing into $ENV_FILE.
if [[ -z "${SEARXNG_SECRET_KEY:-}" ]]; then
    require_cmd openssl "Install openssl, or set SEARXNG_SECRET_KEY yourself in $ENV_FILE."
    if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
        # --check must stay read-only: never write the persisted secret
        # file here. A throwaway in-memory value only satisfies compose's
        # required-variable validation for this run.
        SEARXNG_SECRET_KEY="$(openssl rand -hex 32)"
    else
        SEARXNG_SECRET_FILE="${COMPOSE_DIR}/.env.searxng-secret"
        if [[ ! -f "$SEARXNG_SECRET_FILE" ]]; then
            log_info "generating a new SearXNG server secret (deploy/homelab/.env.searxng-secret)"
            ( umask 177 && openssl rand -hex 32 > "$SEARXNG_SECRET_FILE" )
        fi
        SEARXNG_SECRET_KEY="$(cat "$SEARXNG_SECRET_FILE")"
    fi
fi
export SEARXNG_SECRET_KEY

COMPOSE_ARGS=(-p "$PROJECT_NAME" --env-file "$ENV_FILE")
if [[ "$SIMULATION" -eq 1 ]]; then
    COMPOSE_ARGS+=(--profile simulation)
fi

cd "$COMPOSE_DIR"

# --- --check: validate only, start nothing --------------------------------
if [[ "$COMMON_CHECK_ONLY" -eq 1 ]]; then
    log_info "validating compose configuration (project: $PROJECT_NAME, simulation: $SIMULATION)"
    docker compose "${COMPOSE_ARGS[@]}" config --quiet || die "compose config is invalid"
    log_info "compose configuration is valid"
    if [[ "$SIMULATION" -eq 0 ]]; then
        if [[ -n "${ROBOT_TOKENS:-}" ]]; then
            log_info "ROBOT_TOKENS is set — a real robot can authenticate"
        else
            log_warn "ROBOT_TOKENS is unset — no robot will be able to connect until it's set (fine if you only need --simulation)"
        fi
        if [[ -n "${SMTP_HOST:-}" ]]; then
            log_info "SMTP_HOST is set — production email configured"
        else
            log_warn "SMTP_HOST is unset — email send will fail without --simulation (no Mailpit fallback)"
        fi
    fi
    log_info "--check complete, nothing was started"
    exit 0
fi

# --- start ---------------------------------------------------------------
# `docker compose up -d` is itself idempotent: running this twice recreates
# nothing that hasn't changed (phase-22-23.md: "Starting twice must be
# safe"). Existing volumes/env files are untouched; no `-v`/`down` here ever.
UP_ARGS=(up -d)
[[ "$DO_BUILD" -eq 1 ]] && UP_ARGS+=(--build)

log_info "starting homelab stack (project: $PROJECT_NAME, simulation: $SIMULATION, build: $DO_BUILD)"
docker compose "${COMPOSE_ARGS[@]}" "${UP_ARGS[@]}"

HUB_HEALTH_URL="http://localhost:8080/hub/health"
wait_for_http "$HUB_HEALTH_URL" 120 || die "hub did not become healthy — check: docker compose -p $PROJECT_NAME logs"
log_info "core/hub/GUI ready"

if [[ -n "${ROBOT_TOKENS:-}" ]]; then
    log_info "ROBOT_TOKENS is configured — a real robot launcher (scripts/start-reachy.sh or start-jetson.sh) can now connect"
else
    log_info "ROBOT_TOKENS is not set — no real robot can connect yet (expected if you only ran --simulation)"
fi

open_browser_or_print "http://localhost:8080/hub/ui/"
