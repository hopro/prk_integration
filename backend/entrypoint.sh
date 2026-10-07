#!/bin/sh
set -e

# Те же проверки, что и в шлюзе: незаполненный .env должен останавливать
# развёртывание с внятным сообщением, а не поднимать систему с дефолтами.
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

check_filled "${GATEWAY_PASSWORD:-}" "GATEWAY_PASSWORD"

# Адрес шлюза по умолчанию — имя сервиса в сети compose. Если в .env попал
# адрес самой машины или localhost, backend так и не достучится до шлюза.
case "${MIS_GATEWAY_URL:-}" in
  *localhost*|127.0.0.1|*"10."*|"")
    if [ -n "${MIS_GATEWAY_URL:-}" ]; then
      echo "ВНИМАНИЕ: MIS_GATEWAY_URL=$MIS_GATEWAY_URL" >&2
      echo "Похоже, это не адрес шлюза в сети compose. Обычно значение не нужно:" >&2
      echo " compose сам подставит http://gateway:${GATEWAY_PORT:-8010}." >&2
      echo "Проверьте адрес: curl -s http://127.0.0.1:${APP_PORT:-3001}/api/v1/auth/gateway-health" >&2
    fi
    ;;
esac

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
