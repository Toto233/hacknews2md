# -*- coding: utf-8 -*-
"""Tests for unified database connection factory."""

import os
import sqlite3
import tempfile
import pytest
from pathlib import Path

from src.db.connection import Database, get_db, backup_db, check_integrity


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def temp_db(temp_db_path):
    """Create a temporary database with sample tables."""
    db = Database(temp_db_path)
    conn = db.get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value TEXT
        )
    """)
    conn.execute(
        "INSERT INTO test_table (name, value) VALUES (?, ?)",
        ("test_name", "test_value")
    )
    conn.commit()
    conn.close()
    return db


class TestDatabase:
    """Tests for the Database class."""

    def test_init_creates_directory(self, tmp_path):
        """Database init should create the directory if it doesn't exist."""
        db_path = str(tmp_path / "subdir" / "test.db")
        db = Database(db_path)
        assert os.path.exists(os.path.dirname(db_path))

    def test_get_connection_returns_connection(self, temp_db):
        """get_connection should return a sqlite3.Connection."""
        conn = temp_db.get_connection()
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode_enabled(self, temp_db):
        """Connection should have WAL mode enabled."""
        conn = temp_db.get_connection()
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
        conn.close()

    def test_busy_timeout_set(self, temp_db):
        """Connection should have busy_timeout set."""
        conn = temp_db.get_connection()
        result = conn.execute("PRAGMA busy_timeout").fetchone()
        assert result[0] == 5000
        conn.close()

    def test_foreign_keys_enabled(self, temp_db):
        """Connection should have foreign_keys enabled."""
        conn = temp_db.get_connection()
        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1
        conn.close()

    def test_can_read_and_write(self, temp_db):
        """Should be able to read and write data."""
        conn = temp_db.get_connection()
        cursor = conn.cursor()

        # Read existing data
        cursor.execute("SELECT name, value FROM test_table WHERE id = 1")
        row = cursor.fetchone()
        assert row == ("test_name", "test_value")

        # Write new data
        cursor.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ("new_name", "new_value")
        )
        conn.commit()

        # Verify
        cursor.execute("SELECT COUNT(*) FROM test_table")
        assert cursor.fetchone()[0] == 2

        conn.close()

    def test_singleton_instance(self, temp_db_path):
        """get_instance should return the same instance for the same path."""
        db1 = Database.get_instance(temp_db_path)
        db2 = Database.get_instance(temp_db_path)
        assert db1 is db2

    def test_singleton_different_path(self, tmp_path):
        """get_instance should return different instances for different paths."""
        db1 = Database.get_instance(str(tmp_path / "db1.db"))
        db2 = Database.get_instance(str(tmp_path / "db2.db"))
        assert db1 is not db2


class TestBackup:
    """Tests for database backup functionality."""

    def test_backup_creates_file(self, temp_db):
        """backup should create a backup file."""
        backup_path = temp_db.backup()
        assert os.path.exists(backup_path)
        assert backup_path.endswith(".db")

    def test_backup_custom_path(self, temp_db, tmp_path):
        """backup should use custom path if provided."""
        custom_path = str(tmp_path / "custom_backup.db")
        result = temp_db.backup(custom_path)
        assert result == custom_path
        assert os.path.exists(custom_path)

    def test_backup_contains_data(self, temp_db):
        """Backup should contain the same data as the original."""
        backup_path = temp_db.backup()

        # Read backup
        conn = sqlite3.connect(backup_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, value FROM test_table WHERE id = 1")
        row = cursor.fetchone()
        assert row == ("test_name", "test_value")
        conn.close()

    def test_backup_max_backups(self, temp_db, tmp_path):
        """Should respect max_backups limit."""
        backup_dir = str(tmp_path / "backups")

        # Create 5 backups
        for i in range(5):
            temp_db.backup(max_backups=3)

        # Count backups
        backups = [
            f for f in os.listdir(backup_dir)
            if f.endswith(".db") and f.startswith("hacknews_")
        ]
        assert len(backups) <= 3


class TestIntegrityCheck:
    """Tests for database integrity checking."""

    def test_integrity_check_ok(self, temp_db):
        """integrity_check should return True for a healthy database."""
        ok, msg = temp_db.integrity_check()
        assert ok is True
        assert msg == "ok"

    def test_integrity_check_corrupted(self, tmp_path):
        """integrity_check should detect corruption."""
        db_path = str(tmp_path / "corrupt.db")

        # Create a corrupt database file
        with open(db_path, "wb") as f:
            f.write(b"not a valid database")

        db = Database(db_path)
        ok, msg = db.integrity_check()
        assert ok is False


class TestGetTableInfo:
    """Tests for schema information retrieval."""

    def test_get_table_info(self, temp_db):
        """get_table_info should return table schema."""
        info = temp_db.get_table_info()
        assert "test_table" in info
        columns = info["test_table"]
        column_names = [col["name"] for col in columns]
        assert "id" in column_names
        assert "name" in column_names
        assert "value" in column_names


class TestGetSize:
    """Tests for database size reporting."""

    def test_get_size_mb(self, temp_db):
        """get_size_mb should return a positive number."""
        size = temp_db.get_size_mb()
        assert size >= 0

    def test_get_size_mb_nonexistent(self, tmp_path):
        """get_size_mb should return 0 for nonexistent file."""
        db = Database(str(tmp_path / "nonexistent.db"))
        assert db.get_size_mb() == 0.0


class TestContextManager:
    """Tests for the get_db context manager."""

    def test_get_db_returns_connection(self, temp_db_path):
        """get_db should yield a connection."""
        with get_db(temp_db_path) as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_get_db_commits_on_success(self, temp_db_path):
        """get_db should commit on success."""
        # Create table first
        db = Database(temp_db_path)
        conn = db.get_connection()
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, val TEXT)")
        conn.close()

        with get_db(temp_db_path) as conn:
            conn.execute("INSERT INTO test (val) VALUES (?)", ("committed",))

        # Verify data was committed
        with get_db(temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM test WHERE val = ?", ("committed",))
            assert cursor.fetchone() is not None

    def test_get_db_rollbacks_on_error(self, temp_db_path):
        """get_db should rollback on error."""
        # Create table first
        db = Database(temp_db_path)
        conn = db.get_connection()
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, val TEXT)")
        conn.close()

        with pytest.raises(ValueError):
            with get_db(temp_db_path) as conn:
                conn.execute("INSERT INTO test (val) VALUES (?)", ("rolled_back",))
                raise ValueError("Test error")

        # Verify data was rolled back
        with get_db(temp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT val FROM test WHERE val = ?", ("rolled_back",))
            assert cursor.fetchone() is None
