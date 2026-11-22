"""Database connection and session management for Customer Support Agent.

Uses modern SQLAlchemy 2.x engine and session factory with connection pooling.
Reads connection string from `DATABASE_URL` environment variable.
"""
import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from models import Base

# Automatically load .env if present
load_dotenv()

# Default database connection string (PostgreSQL)
DEFAULT_POSTGRES_URL = "postgresql+psycopg2://postgres:admin****@localhost:5432/customer-support-agent"


def get_database_url() -> str:
    """Return the database connection URL from the environment or default."""
    url = os.environ.get("DATABASE_URL", DEFAULT_POSTGRES_URL)
    # Fix standard Heroku / Docker postgres:// prefix to modern SQLAlchemy dialect
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def build_engine(url: str = None):
    """Build a SQLAlchemy engine with appropriate connection pool settings."""
    db_url = url or get_database_url()
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        return create_engine(db_url, connect_args=connect_args)

    return create_engine(
        db_url,
        pool_pre_ping=True,  # Check connection health before checkout
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,  # Recycle connections every 30 minutes
        connect_args=connect_args,
    )


# Global Engine and Sessionmaker
engine = build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db(session_factory=SessionLocal) -> Generator[Session, None, None]:
    """Provide a transactional database session scope with guaranteed cleanup."""
    session: Session = session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(target_engine=None) -> None:
    """Initialize all tables defined in models.py."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def check_db_health(target_engine=None) -> bool:
    """Check if the database is reachable and accepting queries."""
    eng = target_engine or engine
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
