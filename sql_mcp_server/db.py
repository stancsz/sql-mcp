from __future__ import annotations
from typing import Optional
from sqlalchemy import create_engine, inspect, text, MetaData
from sqlalchemy.engine import Engine
from .config import Settings

def create_engine_from_settings(settings: Settings) -> Engine:
    """
    Create a SQLAlchemy Engine from Settings.

    Uses reasonable defaults for pooling and pre-ping to keep connections healthy.
    For SQLite (in-memory or file) avoid pool_size/max_overflow which are not
    compatible with the default SQLite pool implementation used by SQLAlchemy.
    """
    url = settings.database_url()
    # Apply pooling options only for non-SQLite dialects
    if url.startswith("sqlite"):
        return create_engine(url, future=True, pool_pre_ping=True)
    # For typical server databases use a modest connection pool
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

def create_engine_from_url(url: str) -> Engine:
    """Helper to create engine directly from a URL (used in tests)."""
    if isinstance(url, str) and url.startswith("sqlite"):
        return create_engine(url, future=True, pool_pre_ping=True)
    return create_engine(url, future=True, pool_pre_ping=True, pool_size=5, max_overflow=10)
