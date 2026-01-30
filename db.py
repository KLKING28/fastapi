import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

def _normalize_database_url(url: str) -> str:
    # Railway bywa postgres://..., a SQLAlchemy woli postgresql+psycopg2://...
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

ENGINE = create_engine(_normalize_database_url(DATABASE_URL), pool_pre_ping=True)

SessionLocal = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass
