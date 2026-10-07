#!/bin/sh
set -e

# Не даём развернуться с паролями из .env.example: иначе система поднимется
# с известными паролями, и это обнаружится только при попытке взлома.
check_filled() {
  value="$1"
  name="$2"
  case "$value" in
    ""|CHANGE_ME*)
      echo "ОШИБКА: переменная $name не заполнена в .env." >&2
      echo "Скопируйте .env.example в .env и задайте своё значение:" >&2
      echo "  $name=..." >&2
      exit 1
      ;;
  esac
}

check_filled "${POSTGRES_PASSWORD:-}" "GATEWAY_DB_PASSWORD"
check_filled "${JWT_SECRET_KEY:-}" "JWT_SECRET_KEY"
check_filled "${ADMIN_PASSWORD:-}" "GATEWAY_PASSWORD"

alembic upgrade head

exec uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8010}
