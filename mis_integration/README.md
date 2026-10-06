# MIS Integration Gateway

Сервис-шлюз для взаимодействия с внешней Медицинской Информационной Системой (МИС) через REST API. Проксирует запросы к МИС, обеспечивает авторизацию и единый формат ответов.

## Архитектура

```
Client → JWT Auth → MIS Gateway (FastAPI) → External MIS (ecp.mis66.ru)
                         ↕
                    PostgreSQL (users)
                         ↕
                    Redis (MIS sessions, refresh tokens)
```

## Стек

- **FastAPI** — веб-фреймворк
- **PostgreSQL 16** — хранение пользователей
- **Redis 7** — сессии МИС и refresh-токены
- **SQLAlchemy 2.0** (async) — ORM
- **Alembic** — миграции (автоматические при старте)
- **Docker Compose** — развертывание

## Быстрый старт

```bash
docker compose up -d
```

Сервис будет доступен на `http://localhost:8010`.

## Учетные данные администратора

Логин и пароль для входа в систему (локальная аутентификация, без обращений к МИС):

Учётные данные задаются переменными окружения и не хранятся в репозитории:

```bash
ADMIN_LOGIN=<логин администратора>
ADMIN_PASSWORD=<пароль администратора>
SECRET_KEY=<секрет для JWT>
```

Учётные данные для авторизации во внешней МИС хранятся в БД шлюза и
используются прозрачно при каждом запросе. Задаются через
`PUT /api/v1/auth/mis-credentials` (JWT) или переменными `MIS_LOGIN`/`MIS_PASSWORD`
при первом запуске. Пароль в репозитории не хранится.

При первом запуске администратор создается автоматически. Управление credentials для МИС через `PUT /api/v1/auth/mis-credentials`.

## Эндпониты

### Аутентификация

| Метод | Путь | Аутентификация | Описание |
|-------|------|---------------|----------|
| `POST` | `/api/v1/auth/login` | ❌ | Вход в систему. Принимает `{"login": "...", "password": "..."}`. Локальная проверка пароля, затем авторизация во внешней МИС с сохраненными MIS-учетными. Возвращает access + refresh токены. |
| `POST` | `/api/v1/auth/refresh` | ❌ | Обновление токенов. Принимает `{"refresh_token": "..."}`. Возвращает новую пару токенов. |
| `POST` | `/api/v1/auth/logout` | JWT | Завершение сессии: удаляет MIS-сессию из Redis и отзывает refresh-токены. |
| `PUT` | `/api/v1/auth/mis-credentials` | JWT | Обновление учетных данных для внешней МИС. Принимает `{"mis_login": "...", "mis_password": "..."}`. Инвалидирует текущую MIS-сессию. |

### Прокси к внешней МИС

| Метод | Путь | Аутентификация | Описание |
|-------|------|---------------|----------|
| `POST` | `/api/v1/mis/search-patients` | JWT | Поиск пациентов. Прокси к `/?c=Person&m=getPersonSearchGrid`. |
| `POST` | `/api/v1/mis/get-patient-info` | JWT | Получение информации о пациенте. Прокси к `/?c=EMK&m=getPersonInfo`. |
| `POST` | `/api/v1/mis/save-person-card` | JWT | Сохранение карты пациента. Прокси к `/?c=PersonCard&m=savePersonCard`. |

Все прокси-запросы на стороне сервера обогащаются заголовками (User-Agent, Referer, Cookie и т.д.) для корректной работы внешней МИС.

### Мониторинг

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Проверка состояния сервиса. |

## Формат ответов

Успех:
```json
{"success": true, "data": {...}, "error": null}
```

Ошибка:
```json
{"success": false, "data": null, "error": {"code": "ERR_CODE", "message": "Описание"}}
```

### Коды ошибок

| Код | HTTP статус | Описание |
|-----|-------------|----------|
| `INVALID_CREDENTIALS` | 401 | Неверный логин или пароль |
| `MIS_AUTH_FAILED` | 502 | Ошибка авторизации во внешней МИС |
| `MIS_HTML_ERROR` | 502 | Внешняя МИС вернула HTML-страницу (вместо JSON) |
| `MIS_REQUEST_FAILED` | 502 | Ошибка при выполнении запроса к МИС |
| `TOKEN_EXPIRED` | 401 | Access-токен истек |
| `TOKEN_INVALID` | 401 | Невалидный или отозванный токен |
| `SESSION_NOT_FOUND` | 401 | Сессия МИС не найдена (требуется повторный вход) |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `APP_PORT` | `8010` | Порт сервиса |
| `POSTGRES_DB` | `mis_gateway` | Название БД |
| `POSTGRES_USER` | `mis_gateway` | Пользователь БД |
| `POSTGRES_PASSWORD` | `change_me` | Пароль БД |
| `JWT_SECRET_KEY` | — | Секретный ключ для JWT |
| `JWT_ACCESS_EXPIRE_MINUTES` | `30` | Время жизни access-токена |
| `JWT_REFRESH_EXPIRE_DAYS` | `7` | Время жизни refresh-токена |
| `MIS_BASE_URL` | `https://ecp.mis66.ru` | URL внешней МИС |
| `ADMIN_LOGIN` | `adm_glinnik` | Логин администратора |
| `ADMIN_PASSWORD` | — | Пароль администратора (обязателен) |
| `ADMIN_MIS_LOGIN` | — | MIS-логин администратора |
| `ADMIN_MIS_PASSWORD` | — | MIS-пароль администратора |

## Тесты

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Примеры запросов

```bash
# Логин
curl -s -X POST http://localhost:8010/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login": "<логин>", "password": "<пароль>"}'

# Поиск пациентов
TOKEN="<access_token>"
curl -s -X POST http://localhost:8010/api/v1/mis/search-patients \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"PersonSurName_SurName": "ИВАНОВ", "page": 1, "start": 0, "limit": 100}'

# Обновление MIS-учетных
curl -s -X PUT http://localhost:8010/api/v1/auth/mis-credentials \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"mis_login": "new_login", "mis_password": "new_password"}'
```

## Запуск без Docker

```bash
cp .env .env.local   # настроить подключение к Postgres/Redis
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8010
```
