"""
Test infrastructure: temp-file SQLite engine with NullPool + WAL PRAGMAs,
db_session, client (with X-API-Key), and client_no_auth fixtures.

The client fixture patches app.runs.executor.AsyncSessionLocal so the background
executor uses the test DB instead of the production engine.
"""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base, get_db
from app.main import app

TEST_API_KEY = "test-api-key"


@pytest.fixture
async def test_engine():
    """Shared async engine backed by a temp SQLite file. Exposed so fixtures can build session factories from it."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite+aiosqlite:///{tmp.name}"

    engine = create_async_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    os.unlink(tmp.name)


@pytest.fixture
async def db_session(test_engine):
    """Yields an AsyncSession for the test DB."""
    TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client(test_engine, db_session):
    """
    AsyncClient with X-API-Key header.

    Patches two things:
    1. app.dependency_overrides[get_db] — routes the request-scoped session to the test DB
    2. app.runs.executor.AsyncSessionLocal — routes the background executor's session to the test DB
    """
    import app.runs.executor as executor_module

    TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    original_factory = getattr(executor_module, "AsyncSessionLocal", None)
    executor_module.AsyncSessionLocal = TestSession

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    if original_factory is not None:
        executor_module.AsyncSessionLocal = original_factory


@pytest.fixture
async def client_no_auth(test_engine, db_session):
    """AsyncClient without X-API-Key header — for testing 401 responses."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
