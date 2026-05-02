# GuardStar

MVP браузерной игры с единым миром (Flask + PostgreSQL).

## Быстрый старт

Вся серверная часть находится в `server/`.

- Инструкции по запуску: `server/README.md`
- Переменные окружения: используйте `server/.env.example` (файл `server/.env` в репозиторий не добавляется)
- Плейтест для игроков: чеклист в `docs/PLAYTEST.md`

## Коротко по командам

```bash
cd server
cp .env.example .env
pip install -r requirements.txt
python -m alembic upgrade head
python run.py
```

Тесты:

```bash
cd server
pytest -q
```
