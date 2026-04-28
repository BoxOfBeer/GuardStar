from __future__ import annotations

from datetime import datetime, timezone

# Перезапуск сервера меняет BUILD_ID — удобно, чтобы понять, в какой процесс попали запросы.
BUILD_ID = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

