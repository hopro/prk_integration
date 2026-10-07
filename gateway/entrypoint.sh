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

# База может ещё дорабатывать инициализацию, даже если она уже принимает
# соединения. Раньше миграция падала, контейнер уходил в перезапуск, а
# `docker compose up` возвращал ошибку — хотя система поднималась через
# несколько секунд сама. Теперь ждём базу сами и не пугаем администратора.
attempt=1
max_attempts=30
until alembic upgrade head; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "ОШИБКА: база данных не ответила за $((max_attempts * 2)) с." >&2
    echo "Проверьте docker compose logs gateway-postgres" >&2
    echo "и что GATEWAY_DB_PASSWORD в .env совпадает с паролем базы." >&2
    exit 1
  fi
  echo "База данных ещё не готова, попытка $attempt из $max_attempts…" >&2
  attempt=$((attempt + 1))
  sleep 2
done

exec uvicorn app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8010}
