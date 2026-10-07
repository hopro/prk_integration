#!/usr/bin/env bash
# Сборка комплекта для развёртывания на стороне заказчика.
#
#   ./deploy/make_bundle.sh [каталог]
#
# Скрипт копирует в каталог (по умолчанию ./dist/prk-deploy) исходники трёх
# компонентов, готовый docker-compose, пример .env и шаблоны справочников.
# Выходной каталог самодостаточен: его можно передать заказчику целиком.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# Исходники шлюза лежат в репозитории: ./gateway. Комплект собирается из
# одного клона, путь на машине разработчика не нужен.
GATEWAY_SRC="$ROOT/gateway"
OUT="${1:-$ROOT/dist/prk-deploy}"

if [[ ! -d "$GATEWAY_SRC/app" ]]; then
  echo "Не найден исходник шлюза: $GATEWAY_SRC" >&2
  echo "Ожидается каталог ./gateway с исходниками шлюза (app/, Dockerfile)." >&2
  exit 1
fi

echo "Сборка комплекта → $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"

# Исходники компонентов.
for pair in "backend:backend" "frontend:frontend" "gateway:$GATEWAY_SRC"; do
  name="${pair%%:*}"; src="${pair#*:}"
  echo "  копирую $name ← $src"
  mkdir -p "$OUT/$name"
  tar -C "$src" \
      --exclude='./data' \
      --exclude='./dist' \
      --exclude='./node_modules' \
      --exclude='./.env' \
      --exclude='./.git' \
      --exclude='./__pycache__' \
      --exclude='*.pyc' \
      --exclude='./app/settings.db' \
      --exclude='./app/prk_history.db' \
      --exclude='./app/dictionaries.db' \
      --exclude='./tests' \
      --exclude='./.pytest_cache' \
      -cf - . | tar -C "$OUT/$name" -xf -
done

# Выгрузки ТФОМС: копируются, только если они лежат в ./tfoms.
mkdir -p "$OUT/tfoms"
tfoms_copied=0
for f in SPSMO.zip SPMO.zip SPDEPT.xml SPDEPT.zip SPSUBDEPT.xml SPSUBDEPT.zip; do
  if [[ -f "$ROOT/tfoms/$f" ]]; then
    cp "$ROOT/tfoms/$f" "$OUT/tfoms/$f"
    tfoms_copied=$((tfoms_copied + 1))
  fi
done
echo "  файлов справочников скопировано: $tfoms_copied"

# Развёртывание.
cp "$ROOT/docker-compose.yml" "$OUT/docker-compose.yml"
cp "$HERE/.env.example"       "$OUT/.env.example"
cp "$HERE/README.md"          "$OUT/README.md"
cp -r "$HERE/dictionaries"    "$OUT/dictionaries"
mkdir -p "$OUT/data"
echo "  каталог данных для SQLite создан: $OUT/data"

cat > "$OUT/data/.gitkeep" <<'EOF'
Здесь backend хранит settings.db (настройки и пароли), prk_history.db
(история запросов) и dictionaries.db (справочники).
Не удаляйте этот каталог: в нём рабочие данные системы.
EOF

# Сводка состава.
{
  echo "Комплект собран: $(date '+%Y-%m-%d %H:%M')"
  echo
  for name in backend frontend gateway; do
    echo "$name: $(find "$OUT/$name" -type f | wc -l) файлов"
  done
} > "$OUT/BUILD.txt"

echo
echo "Готово. Дальше:"
echo "  cd $OUT"
echo "  cp .env.example .env   # заполнить пароли и JWT_SECRET_KEY"
echo "  docker compose up -d --build"
echo "  # проверка: ls tfoms  — SPSMO.zip, SPMO.zip, SPDEPT.xml, SPSUBDEPT.xml"
echo "  #           SPDEPT.xml обязателен: без него нет кодов подразделений ИАС-4"