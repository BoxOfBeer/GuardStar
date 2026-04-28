import os


class Config:
    def __init__(self) -> None:
        self.SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
        self.DATABASE_URL = os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://guardstar:guardstar@127.0.0.1:5432/guardstar"
        )
        self.SERVER_SALT = os.environ.get("SERVER_SALT", "dev-server-salt-change-me")

