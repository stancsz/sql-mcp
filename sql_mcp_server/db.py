from __future__ import annotations
from typing import Optional
from sqlalchemy import create_engine, inspect, text, MetaData
from sqlalchemy.engine import Engine
from .config import Settings

def create_engine_from_settings(settings: Settings) -> Engine:
    """
    Create a SQLAlchemy Engine from Settings.

    Uses reasonable defaults for pooling and pre-ping to keep connections healthy.
    """
    url = settings.database_url()
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

def create_engine_from_url(url: str) -> Engine:
    """Helper to create engine directly from a URL (used in tests)."""
    return create_engine(url, future=True, pool_pre_ping=True)
