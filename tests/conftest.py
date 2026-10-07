"""
Test infrastructure: in-memory SQLite engine with StaticPool, db_session,
client (with X-API-Key header), and client_no_auth fixtures.

These fixtures import from app.* which does not yet exist — intentional RED gate.
ImportError on collection is the expected Wave 1 state.
"""

import os
import tempfile

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db, Base

TEST_API_KEY = "test-api-key"


@pytest.fixture
async def db_session():
    """
    Create a temp-file SQLite engine with NullPool so WAL mode is honoured.

    SQLite in-memory databases always report journal_mode='memory' and ignore
    the PRAGMA journal_mode=WAL directive — WAL requires a file.  Using a
    NamedTemporaryFile gives us a real on-disk database for the test session
    while keeping it isolated (the file is deleted in cleanup).

    PRAGMAs are registered via event.listens_for(engine.sync_engine, "connect")
    — the same pattern as production.
    """
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

    TestSession = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with TestSession() as session:
        yield session

    await engine.dispose()
    os.unlink(tmp.name)


@pytest.fixture
async def client(db_session: AsyncSession):
    """
    AsyncClient with X-API-Key header set to TEST_API_KEY.
    Overrides the get_db dependency with the test session.
    """
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


@pytest.fixture
async def client_no_auth(db_session: AsyncSession):
    """
    AsyncClient without X-API-Key header — for testing 401 responses.
    Overrides the get_db dependency with the test session.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
