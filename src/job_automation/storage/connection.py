"""Database connection factory and transaction management for SQLite on Windows.

Configures WAL mode, busy timeout, foreign key enforcement, and explicit
transaction context management.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def open_connection(db_path: Path | str, timeout: float = 5.0) -> sqlite3.Connection:
    """Open and configure a SQLite connection with production PRAGMAs.

    - Creates parent directory if missing on connect (never on module import).
    - Enables foreign key enforcement (PRAGMA foreign_keys = ON).
    - Enables Write-Ahead Logging (PRAGMA journal_mode = WAL) for concurrency.
    - Sets busy timeout to prevent transient lock contention.
    - Sets row_factory to sqlite3.Row for dict-like column access.
    """
    path = Path(db_path).resolve()
    # Directory creation happens only upon explicit connection, not on module import
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), timeout=timeout)
    conn.row_factory = sqlite3.Row

    # Enforce foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON;")

    # WAL mode for native Windows concurrent reader/writer access
    conn.execute("PRAGMA journal_mode = WAL;")

    # Prevent transient database locked errors on rapid writes
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)};")

    # Safe synchronization in WAL mode
    conn.execute("PRAGMA synchronous = NORMAL;")

    return conn


_TRANSACTION_DEPTHS: dict[int, int] = {}


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for atomic database transactions.

    Executes operations within a transaction.
    Commits changes automatically upon successful block exit of the outermost transaction.
    Rolls back all changes if any exception is raised.
    Supports composable nested transaction blocks without premature inner commits.
    """
    conn_id = id(conn)
    depth = _TRANSACTION_DEPTHS.get(conn_id, 0)
    _TRANSACTION_DEPTHS[conn_id] = depth + 1
    try:
        if depth == 0:
            with conn:
                yield conn
        else:
            yield conn
    finally:
        _TRANSACTION_DEPTHS[conn_id] = depth
        if depth == 0 and conn_id in _TRANSACTION_DEPTHS:
            del _TRANSACTION_DEPTHS[conn_id]

