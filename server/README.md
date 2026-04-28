# GuardStar (MVP)

## Что умеет сейчас
- Регистрация **без персональных данных**: создаёте пилота и получаете 32‑символьный код доступа.
- Вход/восстановление по коду доступа.
- Стартовый мир: 1 планета + стартовые ресурсы и базовые юниты.
- Web (Jinja) + JSON API.

## Переменные окружения
Скопируйте `.env.example` в `.env` и при необходимости отредактируйте:

- `SECRET_KEY` — ключ сессии Flask.
- `SERVER_SALT` — соль/seed для процедурной генерации и auth.
- `DATABASE_URL` — строка подключения к PostgreSQL.
- `TEST_DATABASE_URL` — отдельная БД для `pytest` (опционально).

## Локальный запуск

### 1) Поднять PostgreSQL
В папке `server/`:

```bash
docker compose up -d
```

### 2) Установить зависимости

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Настроить env

```bash
cp .env.example .env
```

### 4) Применить миграции

```bash
alembic upgrade head
```

### 5) Запустить сервер

```bash
python run.py
```

Открыть:
- Web: `http://127.0.0.1:5000/`
- API: `http://127.0.0.1:5000/api/me`

## Тесты

```bash
pytest -q
```

> Если тесты пропускаются, задайте `TEST_DATABASE_URL` или `DATABASE_URL` с доступной PostgreSQL.
