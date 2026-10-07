"""
RESIL-04: Tests for WAL mode and asyncio.Lock write serialization.

These tests import from app.core.database which does not yet exist —
intentional RED gate for Wave 1 TDD.
"""

import asyncio
import pytest
from sqlalchemy import text


async def test_wal_mode_active(db_session):
    """
    RESIL-04: After engine initialization with PRAGMA journal_mode=WAL,
    the active journal mode for the in-memory database must be 'wal'.

    Covers: WAL mode PRAGMA correctly set via event.listens_for(engine.sync_engine, "connect").
    """
    result = await db_session.execute(text("PRAGMA journal_mode"))
    mode = result.scalar()
    assert mode == "wal", (
        f"Expected journal_mode='wal' but got '{mode}'. "
        "Check that PRAGMA journal_mode=WAL is set via event.listens_for(engine.sync_engine, 'connect')."
    )


async def test_write_lock_exists():
    """
    RESIL-04: The module-level _write_lock in app.core.database must be an asyncio.Lock.

    This lock serializes all write coroutines within the single-worker process,
    preventing lost updates under concurrent write contention.
    """
    from app.core.database import _write_lock  # noqa: F401 — RED gate import

    assert isinstance(_write_lock, asyncio.Lock), (
        f"Expected _write_lock to be asyncio.Lock, got {type(_write_lock)}. "
        "Declare '_write_lock = asyncio.Lock()' at module level in app/core/database.py."
    )
