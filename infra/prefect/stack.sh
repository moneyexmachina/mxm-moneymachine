#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/infra/prefect/compose.yml"

usage() {
  cat <<'EOF'
Usage:
  infra/prefect/stack.sh <dev|prod> up
  infra/prefect/stack.sh <dev|prod> down
  infra/prefect/stack.sh <dev|prod> reset
  infra/prefect/stack.sh <dev|prod> ps
  infra/prefect/stack.sh <dev|prod> logs
  infra/prefect/stack.sh <dev|prod> config
  infra/prefect/stack.sh <dev|prod> api-url

Secrets:
  The script reads the Prefect PostgreSQL password from gopass.

Default secret paths:
  dev:  mxm/green/dev/prefect/postgres/password
  prod: mxm/green/prod/prefect/postgres/password

Override with:
  MXM_PREFECT_POSTGRES_PASSWORD_SECRET_PATH=...

No .env file containing secrets is written.
EOF
}

environment="${1:-}"

case "${environment}" in
  dev|prod)
    shift
    ;;
  help|--help|-h|"")
    usage
    exit 0
    ;;
  *)
    echo "Unknown environment: ${environment}" >&2
    echo "Expected: dev or prod" >&2
    exit 1
    ;;
esac

case "${environment}" in
  dev)
    default_postgres_host_port=15432
    default_redis_host_port=16379
    default_server_host_port=4200
    ;;
  prod)
    default_postgres_host_port=15433
    default_redis_host_port=16380
    default_server_host_port=4201
    ;;
esac

: "${COMPOSE_PROJECT_NAME:=mxm-prefect-${environment}}"

: "${POSTGRES_IMAGE_TAG:=14}"
: "${REDIS_IMAGE_TAG:=7}"
: "${PREFECT_IMAGE_TAG:=3-latest}"

: "${PREFECT_POSTGRES_USER:=prefect}"
: "${PREFECT_POSTGRES_DB:=prefect}"

: "${PREFECT_POSTGRES_HOST_PORT:=${default_postgres_host_port}}"
: "${PREFECT_REDIS_HOST_PORT:=${default_redis_host_port}}"
: "${PREFECT_SERVER_HOST_PORT:=${default_server_host_port}}"

: "${PREFECT_SERVER_UI_API_URL:=http://localhost:${PREFECT_SERVER_HOST_PORT}/api}"
: "${PREFECT_API_URL:=http://localhost:${PREFECT_SERVER_HOST_PORT}/api}"
: "${PREFECT_INTERNAL_API_URL:=http://prefect-server:4200/api}"

: "${MXM_PREFECT_POSTGRES_PASSWORD_SECRET_PATH:=mxm/green/${environment}/prefect/postgres/password}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

load_secrets() {
  require_command docker
  require_command gopass

  PREFECT_POSTGRES_PASSWORD="$(
    gopass show -o "${MXM_PREFECT_POSTGRES_PASSWORD_SECRET_PATH}"
  )"

  export COMPOSE_PROJECT_NAME
  export POSTGRES_IMAGE_TAG
  export REDIS_IMAGE_TAG
  export PREFECT_IMAGE_TAG
  export PREFECT_POSTGRES_USER
  export PREFECT_POSTGRES_DB
  export PREFECT_POSTGRES_HOST_PORT
  export PREFECT_REDIS_HOST_PORT
  export PREFECT_SERVER_HOST_PORT
  export PREFECT_SERVER_UI_API_URL
  export PREFECT_API_URL
  export PREFECT_INTERNAL_API_URL
  export PREFECT_POSTGRES_PASSWORD
}

compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

cmd="${1:-help}"
shift || true

case "${cmd}" in
  up)
    load_secrets
    compose up -d "$@"
    ;;

  down)
    compose down "$@"
    ;;

  reset)
    compose down -v "$@"
    ;;

  ps)
    compose ps "$@"
    ;;

  logs)
    compose logs -f "$@"
    ;;

  config)
    load_secrets
    compose config "$@"
    ;;

  api-url)
    echo "${PREFECT_API_URL}"
    ;;

  help|--help|-h)
    usage
    ;;

  *)
    echo "Unknown command: ${cmd}" >&2
    exit 1
    ;;
esac
