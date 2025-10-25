from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Configuration loaded from environment variables.

    Environment variables:
      - DB_TYPE: postgresql | mysql | mssql | sqlite
      - DB_HOST
      - DB_PORT
      - DB_USER
      - DB_PASS
      - DB_NAME
    """

    DB_TYPE: str = "sqlite"
    DB_HOST: Optional[str] = "localhost"
    DB_PORT: Optional[int] = None
    DB_USER: Optional[str] = None
    DB_PASS: Optional[str] = None
    DB_NAME: str = ":memory:"

    class Config:
        env_prefix = ""
        env_file = ".env"

    def database_url(self) -> str:
        """Construct a SQLAlchemy database URL based on settings."""
        db_type = self.DB_TYPE.lower()
        if db_type in ("sqlite",):
            # in-memory default
            if self.DB_NAME == ":memory:":
                return "sqlite+pysqlite:///:memory:"
            # file-based sqlite
            return f"sqlite+pysqlite:///{self.DB_NAME}"
        if db_type in ("postgresql", "postgres"):
            port = f":{self.DB_PORT}" if self.DB_PORT else ""
            user = self.DB_USER or ""
            password = self.DB_PASS or ""
            creds = f"{user}:{password}@" if user or password else ""
            return f"postgresql+psycopg2://{creds}{self.DB_HOST}{port}/{self.DB_NAME}"
        if db_type in ("mysql",):
            port = f":{self.DB_PORT}" if self.DB_PORT else ""
            user = self.DB_USER or ""
            password = self.DB_PASS or ""
            creds = f"{user}:{password}@" if user or password else ""
            return f"mysql+pymysql://{creds}{self.DB_HOST}{port}/{self.DB_NAME}"
        if db_type in ("mssql", "sqlserver"):
            # Uses pyodbc DSN style, user must ensure driver installed and connection works
            port = f":{self.DB_PORT}" if self.DB_PORT else ""
            user = self.DB_USER or ""
            password = self.DB_PASS or ""
            creds = f"{user}:{password}@" if user or password else ""
            driver = "ODBC+Driver+17+for+SQL+Server"
            return f"mssql+pyodbc://{creds}{self.DB_HOST}{port}/{self.DB_NAME}?driver={driver}"
        raise ValueError(f"Unsupported DB_TYPE: {self.DB_TYPE}")
