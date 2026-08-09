"""Durable, profile-local state for recent searches.

This database deliberately has no dependency on the disposable cache or the
Trakt sync database.  It is safe for the plug-in and background service to use
at the same time because each operation opens a short-lived SQLite connection.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import sqlite3
import threading
import time
from typing import Iterator, Optional

SCHEMA_VERSION = 2
DEFAULT_HISTORY_LIMIT = 20
DATABASE_FILENAME = 'user_state.db'


class UserStateError(RuntimeError):
    """Raised when durable user state cannot be read or written safely."""


def _log(level, message):
    """Log in Kodi when available without making this module Kodi-dependent."""
    try:
        import xbmc
        xbmc.log('[AIOStreams UserState] {}'.format(message), level)
    except ImportError:
        pass


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _search_scope(content_type):
    value = (_text(content_type) or 'all').lower()
    aliases = {
        'all': 'all', 'both': 'all',
        'movie': 'movies', 'movies': 'movies',
        'series': 'shows', 'show': 'shows', 'shows': 'shows',
        'tvshow': 'shows', 'tvshows': 'shows',
    }
    try:
        return aliases[value]
    except KeyError:
        raise ValueError('Unsupported search scope: {}'.format(content_type))


def _normalized_query(query):
    query = _text(query)
    return ' '.join(query.split()).casefold() if query else None


def default_database_path():
    """Resolve the add-on profile database location only when Kodi is present."""
    import xbmcaddon
    import xbmcvfs

    profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    return os.path.join(profile_path, DATABASE_FILENAME)


class ProfileDatabase:
    """Shared, durable SQLite connection helper for profile-local state.

    Search history and playback history intentionally live in the same file but
    keep their schemas and domain APIs separate.  Short-lived connections plus
    WAL make the plug-in and login service safe concurrent users.
    """

    _initialized_paths = set()
    _initialization_lock = threading.Lock()

    def __init__(
        self,
        database_path: Optional[str] = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        clock=None,
        busy_timeout_ms: int = 5000,
    ):
        if history_limit < 1:
            raise ValueError('history_limit must be at least one')
        self.database_path = os.path.abspath(database_path or default_database_path())
        self.history_limit = history_limit
        self._clock = clock or time.time
        self._busy_timeout_ms = busy_timeout_ms
        self._last_timestamp = 0

    def _timestamp(self):
        """Return increasing millisecond timestamps for deterministic ordering."""
        timestamp = int(self._clock() * 1000)
        self._last_timestamp = max(timestamp, self._last_timestamp + 1)
        return self._last_timestamp

    def _connect(self):
        try:
            connection = sqlite3.connect(
                self.database_path,
                timeout=self._busy_timeout_ms / 1000.0,
            )
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA busy_timeout = {}'.format(self._busy_timeout_ms))
            return connection
        except (OSError, sqlite3.Error) as error:
            self._raise_database_error('open', error)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._ensure_initialized()
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            self._raise_database_error('access', error)
        finally:
            connection.close()

    def _ensure_initialized(self):
        if self.database_path in self._initialized_paths:
            return
        with self._initialization_lock:
            if self.database_path in self._initialized_paths:
                return
            directory = os.path.dirname(self.database_path)
            try:
                if directory:
                    os.makedirs(directory, exist_ok=True)
                connection = self._connect()
                try:
                    try:
                        # WAL permits a reader to coexist with a writer.  Some
                        # Kodi SQLite builds cannot enable it, so retaining the
                        # default journal mode is an intentional fallback.
                        connection.execute('PRAGMA journal_mode = WAL')
                    except sqlite3.DatabaseError:
                        _log(2, 'WAL unavailable; using SQLite default journal mode')
                    connection.execute('BEGIN IMMEDIATE')
                    self._initialize_schema(connection)
                    connection.commit()
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as error:
                self._raise_database_error('initialize', error)
            self._initialized_paths.add(self.database_path)

    def initialize(self):
        """Ensure the recent-search schema exists without writing search data."""
        self._ensure_initialized()

    @staticmethod
    def _initialize_schema(connection):
        """Create and migrate durable profile-local tables."""
        connection.execute(
            'CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)'
        )
        row = connection.execute('SELECT version FROM schema_version LIMIT 1').fetchone()
        connection.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                normalized_query TEXT NOT NULL,
                query TEXT NOT NULL,
                content_type TEXT NOT NULL,
                last_used_at INTEGER NOT NULL,
                PRIMARY KEY(normalized_query, content_type)
            )
        ''')
        # History rows use a provider-neutral canonical key.  Do not store
        # Python objects here: these tables are intended to remain inspectable
        # and migratable independently of any remote provider.
        connection.execute('''
            CREATE TABLE IF NOT EXISTS history_items (
                history_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                imdb_id TEXT,
                tmdb_id TEXT,
                show_imdb_id TEXT,
                show_tmdb_id TEXT,
                season INTEGER,
                episode INTEGER,
                metadata_id TEXT,
                origin_fingerprint TEXT,
                title TEXT NOT NULL DEFAULT '',
                show_title TEXT,
                watched INTEGER NOT NULL DEFAULT 0,
                play_count INTEGER NOT NULL DEFAULT 0,
                resume_time REAL NOT NULL DEFAULT 0,
                duration REAL NOT NULL DEFAULT 0,
                percent_played REAL NOT NULL DEFAULT 0,
                first_watched_at INTEGER,
                last_watched_at INTEGER,
                last_played_at INTEGER,
                updated_at INTEGER NOT NULL
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS history_series (
                show_key TEXT PRIMARY KEY,
                imdb_id TEXT,
                tmdb_id TEXT,
                metadata_id TEXT,
                origin_fingerprint TEXT,
                title TEXT NOT NULL DEFAULT '',
                hidden_from_next_up INTEGER NOT NULL DEFAULT 0,
                last_played_at INTEGER,
                metadata_refreshed_at INTEGER,
                updated_at INTEGER NOT NULL
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS history_episode_catalog (
                show_key TEXT NOT NULL,
                season INTEGER NOT NULL,
                episode INTEGER NOT NULL,
                imdb_id TEXT,
                tmdb_id TEXT,
                metadata_id TEXT,
                title TEXT NOT NULL DEFAULT '',
                air_date TEXT,
                metadata_json TEXT,
                last_seen_at INTEGER NOT NULL,
                PRIMARY KEY(show_key, season, episode)
            )
        ''')
        connection.execute(
            'CREATE INDEX IF NOT EXISTS history_items_show_index '
            'ON history_items(show_imdb_id, show_tmdb_id, season, episode)'
        )
        connection.execute(
            'CREATE INDEX IF NOT EXISTS history_catalog_show_index '
            'ON history_episode_catalog(show_key, season, episode)'
        )
        if row:
            connection.execute('UPDATE schema_version SET version = ?', (SCHEMA_VERSION,))
        else:
            connection.execute('INSERT INTO schema_version(version) VALUES (?)', (SCHEMA_VERSION,))

    def _raise_database_error(self, operation, error):
        _log(3, '{} failed: {}'.format(operation, type(error).__name__))
        raise UserStateError(
            'Could not {} the local user-state database'.format(operation)
        ) from error

class UserState(ProfileDatabase):
    """SQLite-backed recent searches."""

    def record_search(self, query, content_type='all'):
        """Record a submitted query, deduplicating it within its search scope."""
        normalized = _normalized_query(query)
        if not normalized:
            return False
        scope = _search_scope(content_type)
        display_query = ' '.join(str(query).strip().split())
        with self._connection() as connection:
            connection.execute('''
                INSERT INTO search_history(normalized_query, query, content_type, last_used_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(normalized_query, content_type) DO UPDATE SET
                    query = excluded.query, last_used_at = excluded.last_used_at
            ''', (normalized, display_query, scope, self._timestamp()))
            connection.execute('''
                DELETE FROM search_history WHERE rowid IN (
                    SELECT rowid FROM search_history
                    ORDER BY last_used_at DESC, rowid DESC LIMIT -1 OFFSET ?
                )
            ''', (self.history_limit,))
        return True

    def list_searches(self, limit=None):
        if limit is not None and limit < 0:
            raise ValueError('limit cannot be negative')
        query = ('SELECT normalized_query, query, content_type, last_used_at '
                 'FROM search_history ORDER BY last_used_at DESC, rowid DESC')
        arguments = ()
        if limit is not None:
            query += ' LIMIT ?'
            arguments = (limit,)
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(query, arguments)]

    def remove_search(self, query, content_type='all'):
        normalized = _normalized_query(query)
        if not normalized:
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                'DELETE FROM search_history WHERE normalized_query = ? AND content_type = ?',
                (normalized, _search_scope(content_type)),
            )
            return cursor.rowcount > 0

    def clear_searches(self):
        with self._connection() as connection:
            connection.execute('DELETE FROM search_history')
