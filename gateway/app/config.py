from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_host: str = "0.0.0.0"
    app_port: int = 8010
    app_debug: bool = True
    # Логировать каждый SQL-запрос. По умолчанию выключено: SQL-лог
    # заслоняет сообщения о сессиях ЕЦП, ради которых логи и нужны.
    sql_echo: bool = False

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "mis_gateway"
    postgres_user: str = "mis_gateway"
    postgres_password: str = "change_me"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7

    mis_base_url: str = "https://ecp.mis66.ru"
    mis_request_timeout: int = 30

    admin_login: str = "admin"
    admin_password: str = "admin123"
    admin_mis_login: str = ""
    admin_mis_password: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
