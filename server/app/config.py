import os


class Config:
    def __init__(self) -> None:
        self.SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
        self.DATABASE_URL = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://guardstar:guardstar@127.0.0.1:5432/guardstar",
        )
        self.SERVER_SALT = os.environ.get("SERVER_SALT", "dev-server-salt-change-me")
        self.AUTO_TICK_ENABLED = os.environ.get(
            "AUTO_TICK_ENABLED", "false"
        ).lower() in ("1", "true", "yes", "on")
        self.AUTO_TICK_INTERVAL_SECONDS = float(
            os.environ.get("AUTO_TICK_INTERVAL_SECONDS", "5")
        )
        # Если переменная ADMIN_TOKEN не задана в окружении — временный дефолт для личного инстанса.
        # Явно задайте ADMIN_TOKEN="" чтобы не подставлять дефолт (хэш не запишется при пустом env).
        self.ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "1662916644")
        # Локальный dev: create_all + аварийные ALTER/CREATE. Для открытого плейтеста/прода — false и только Alembic.
        self.GUARDSTAR_DB_SAFETY_NET = os.environ.get(
            "GUARDSTAR_DB_SAFETY_NET", "true"
        ).lower() in ("1", "true", "yes", "on")
