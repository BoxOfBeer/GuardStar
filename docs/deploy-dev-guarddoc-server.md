# Деплой GuardStar на `dev.guarddoc.ru` (рядом с school)

Цель: отдельная БД, отдельный порт приложения, отдельный nginx `server_name`, **не менять** файлы `school.guarddoc.ru` и порт **8000** (school).

## Текущее на сервере (зафиксировано)

- **school / портал**: `127.0.0.1:8000` (Python), nginx `school.guarddoc.ru` и `guarddoc-portal.conf` (guarddoc.ru, www, demo).
- **PostgreSQL**: `127.0.0.1:5432`, база school: **`guardschool`** (не трогать).
- **Сертификат Let’s Encrypt** (`school.guarddoc.ru`): SAN уже включает `guarddoc.ru`, `www`, `demo`, `school` — **`dev.guarddoc.ru` в SAN нет** (нужно расширить или выпустить отдельный cert — см. ниже).

## 0) Не сломать school

- Не править `/etc/nginx/sites-available/school.guarddoc.ru` и не отключать symlink в `sites-enabled`.
- Не трогать `guardschool` и учётные данные school в PostgreSQL.
- GuardStar слушает только **`127.0.0.1:8001`** (или другой свободный порт ≠ 8000).

## 1) Новая база PostgreSQL

Роль и БД только для игры (имена как в `.env.example`):

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE guardstar WITH LOGIN PASSWORD 'СГЕНЕРИРУЙТЕ_СИЛЬНЫЙ_ПАРОЛЬ';
CREATE DATABASE guardstar OWNER guardstar;
CREATE DATABASE guardstar_test OWNER guardstar;
SQL
```

Строки для `.env` на сервере:

```env
DATABASE_URL=postgresql+psycopg://guardstar:ПАРОЛЬ@127.0.0.1:5432/guardstar
TEST_DATABASE_URL=postgresql+psycopg://guardstar:ПАРОЛЬ@127.0.0.1:5432/guardstar_test
```

Прод: **`GUARDSTAR_DB_SAFETY_NET=false`** — только Alembic, без dev `create_all` на проде. Тогда схема должна полностью соответствовать миграциям до **`alembic upgrade head`** (часть полей раньше жила только в **`dev_schema_safety_net`** или в боковой ветке Alembic **`20260530_000012`**, например **`players.race_id`**, **`fleets.name`**, **`resources.fuel`/`food`/`water`**, таблицы **`fleet_ships`**, **`buildings`**, **`player_techs`**, колонки **`game_clock.auto_tick_*`**, **`admin_config`** — для этого в репозитории миграция **`20260517_000028`**).

## 2) DNS для `dev.guarddoc.ru`

У регистратора домена `guarddoc.ru` добавьте запись:

| Тип | Имя | Значение | TTL |
|-----|-----|----------|-----|
| **A** | `dev` | **публичный IPv4** сервера (тот же, что у `school.guarddoc.ru` / `guarddoc.ru`) | 300–3600 |

Если у вас включён IPv6 и хотите ходить по AAAA — отдельная **AAAA** на IPv6 сервера.

Проверка с ПК: `nslookup dev.guarddoc.ru` → должен резолвиться в нужный IP.

## 3) Сертификат (Let’s Encrypt)

После того как DNS **уже** отдаёт правильный IP:

**Вариант A — расширить существующий cert** (один fullchain для всех имён в SAN):

```bash
certbot certonly --nginx --cert-name school.guarddoc.ru \
  -d guarddoc.ru -d www.guarddoc.ru -d demo.guarddoc.ru -d school.guarddoc.ru -d dev.guarddoc.ru
```

Потом в vhost для `dev` указать те же пути, что и у portal/school:

`ssl_certificate /etc/letsencrypt/live/school.guarddoc.ru/fullchain.pem;`

**Вариант B — отдельный cert только на `dev`** (проще откатить, не трогает SAN старого):

```bash
certbot --nginx -d dev.guarddoc.ru
```

Certbot сам подставит `ssl_*` в server-блок `dev` (если используете плагин `--nginx`).

После любых правок: `nginx -t && systemctl reload nginx`.

## 4) Git и развёртывание

1. Закоммитьте и запушьте в `origin` (например `https://github.com/BoxOfBeer/GuardStar.git`) всё нужное для сборки.
2. На сервере:

```bash
sudo mkdir -p /opt && cd /opt
sudo git clone https://github.com/BoxOfBeer/GuardStar.git guardstar
cd /opt/guardstar/server
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt gunicorn
cp .env.example .env
# отредактировать .env: DATABASE_URL, TEST_DATABASE_URL, SECRET_KEY, SERVER_SALT, ADMIN_TOKEN, GUARDSTAR_DB_SAFETY_NET=false
python -m alembic upgrade head
```

3. **systemd** (пример; один worker — автотик в коде рассчитан на один процесс):

`/etc/systemd/system/guardstar.service`:

```ini
[Unit]
Description=GuardStar (gunicorn)
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/opt/guardstar/server
EnvironmentFile=/opt/guardstar/server/.env
Environment=GUARDSTAR_NO_RELOADER=1
ExecStart=/opt/guardstar/server/.venv/bin/gunicorn --bind 127.0.0.1:8001 --workers 1 --timeout 120 run:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now guardstar
```

4. **Nginx** для HTTP/HTTPS на `dev.guarddoc.ru` — `proxy_pass http://127.0.0.1:8001;` и те же заголовки, что у school (`Host`, `X-Forwarded-For`, `X-Forwarded-Proto`).

Файл лучше отдельный, например `/etc/nginx/sites-available/dev.guarddoc.ru` → symlink в `sites-enabled/`.

## 5) Тесты на сервере

Из `/opt/guardstar/server` с активированным venv и **PYTHONPATH** (иначе `ModuleNotFoundError: app`):

```bash
cd /opt/guardstar/server
export PYTHONPATH=/opt/guardstar/server
set -a && . ./.env && set +a   # подхватить DATABASE_URL / TEST_DATABASE_URL / SECRET_KEY / …
.venv/bin/pytest -q tests/test_balance.py
.venv/bin/pytest -q
```

Полный набор с `client` требует **`TEST_DATABASE_URL`** в `.env` (см. `server/tests/conftest.py`). Код на сервере должен совпадать с веткой, под которую писались тесты: после **`git pull`** перезапуск **`systemctl restart guardstar`**.

## Что уже сделано на хосте (черновик 2026-05-03)

На **`195.208.2.62`** (не трогая `school.guarddoc.ru` и БД **`guardschool`**):

- Роль PostgreSQL **`guardstar`**, БД **`guardstar`** и **`guardstar_test`**.
- Клон **`/opt/guardstar`** с GitHub, venv, **`/opt/guardstar/server/.env`** (секреты только на сервере), **`alembic upgrade head`** до ревизии из клона.
- **Gunicorn** на **`127.0.0.1:8001`**, unit **`guardstar.service`**.
- Nginx: **`/etc/nginx/sites-available/dev.guarddoc.ru`** — HTTP **80** для `dev.guarddoc.ru` → прокси на **8001**.

Пока **нет записи DNS** на `dev`, снаружи сайт не откроется; локально: `curl http://127.0.0.1:8001/api/health`.

На клоне с GitHub была одна строка с **`WorldService._planet…`** в миксине (в актуальном дереве разработки уже **`self._`**); после **`git pull`** убедитесь, что серверный файл совпадает с репозиторием (без «ручного» sed).

## Проверка после деплоя

- `curl -sS http://127.0.0.1:8001/api/health`
- `curl -sS http://127.0.0.1:8001/api/version`
- С браузера: `https://dev.guarddoc.ru/` (после TLS).

## См. также

- `docs/deploy-guarddoc-subdomain.md` — общие принципы поддомена и изоляции БД.
