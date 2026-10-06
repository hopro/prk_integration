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

| Поле | Значение |
|------|----------|
| Логин | `adm_glinnik` |
| Пароль | `adm_local_pass` |

Учетные данные для авторизации во внешней МИС хранятся в БД и используются прозрачно при каждом запросе. Текущие:

| Поле | Значение |
|------|----------|
| MIS Логин | `adm_glinnik` |
| MIS Пароль | `Adm0893XIxi35126!1` |

При первом запуске администратор создается автоматически. Управление credentials для МИС через `PUT /api/v1/auth/mis-credentials`.

## Эндпониты

### Аутентификация

| Метод | Путь | Аутентификация | Описание |
|-------|------|---------------|----------|
| `POST` | `/api/v1/auth/login` | ❌ | Вход в систему. Принимает `{"login": "...", "password": "..."}`. Локальная проверка пароля, затем авторизация во внешней МИС с сохраненными MIS-учетными. Возвращает access + refresh токены. |
| `POST` | `/api/v1/auth/refresh` | ❌ | Обновление токенов. Принимает `{"refresh_token": "..."}`. Возвращает новую пару токенов. |
| `POST` | `/api/v1/auth/logout` | JWT | Завершение сессии: удаляет MIS-сессию из Redis и отзывает refresh-токены. |
| `PUT` | `/api/v1/auth/mis-credentials` | JWT | Обновление учетных данных для внешней МИС. Принимает `{"mis_login": "...", "mis_password": "..."}`, оба поля обязательны и непустые. Учетные данные сначала проверяются во внешней МИС: при отказе возвращается 502 и в базе ничего не меняется. После успеха сессия МИС создается заново. |
| `GET` | `/api/v1/auth/mis-credentials` | JWT | Текущее состояние учетных данных МИС: `{"mis_login": "...", "password_set": true, "updated_at": "..."}`. Пароль не возвращается. |

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
| `MIS_AUTH_FAILED` | 502 | Ошибка авторизации во внешней МИС. В том числе «Нет прав доступа» — у пользователя МИС нет группы «Пользователь API» |
| `MIS_SESSION_EXPIRED` | 502 | Внешняя МИС вернула HTML (страницу входа) даже после переавторизации. Сессия выбрасывается из Redis, следующий запрос попробует снова |
| `MIS_REQUEST_FAILED` | 502 | Ошибка при выполнении запроса к МИС |
| `TOKEN_EXPIRED` | 401 | Access-токен истек |
| `TOKEN_INVALID` | 401 | Невалидный или отозванный токен |
| `SESSION_NOT_FOUND` | 401 | Сессия МИС не найдена (требуется повторный вход) |

### Восстановление сессии МИС

Любой HTML-ответ от внешней МИС означает, что сессия недействительна (редирект на
страницу входа). В этом случае шлюз один раз выбрасывает сессию из Redis и
переавторизуется. Если переавторизация не удалась — сессия остается выброшенной,
поэтому следующий запрос попробует снова, а не будет повторно падать на закепленной
мёртвой сессии.

Диагностика: `journalctl CONTAINER_NAME=mis_integration-app-1 | grep 'app.mis'`.
Сообщения `MIS session: re-authenticated after ...` подтверждают успешное
восстановление. Логи SQL отключаются по умолчанию (`SQL_ECHO=false`).

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
| `ADMIN_PASSWORD` | `adm_local_pass` | Пароль администратора |
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
  -d '{"login": "adm_glinnik", "password": "adm_local_pass"}'

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
