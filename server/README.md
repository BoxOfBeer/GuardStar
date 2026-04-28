# GuardStar (MVP)

## Что умеет сейчас
- Регистрация **без персональных данных**: создаёте пилота и получаете 32‑символьный код доступа.
- Вход/восстановление по коду доступа.
- Стартовый мир: 1 планета + стартовые ресурсы и базовые юниты.
- Web (Jinja) + JSON API.

## Локальный запуск (Windows)

### 1) Поднять PostgreSQL

В папке `server/`:

```bash
docker compose up -d
```

Если Docker недоступен, можно поставить PostgreSQL локально и указать `DATABASE_URL` в `.env` (формат уже в `.env.example`).

### 2) Установить зависимости

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

### 3) Настроить env

Скопируйте `.env.example` → `.env` и при желании измените значения.

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

