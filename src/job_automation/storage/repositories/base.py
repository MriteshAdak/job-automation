"""Base repository for SQLite storage."""

from __future__ import annotations

import sqlite3


class BaseRepository:
    """Base class for all typed SQLite repositories."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

