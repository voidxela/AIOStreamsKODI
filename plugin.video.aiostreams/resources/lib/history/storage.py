"""SQLite implementation details for the local history provider."""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Iterable, Optional

from resources.lib.user_state import ProfileDatabase

from .models import HistoryMediaRef, HistoryState, NextUpEntry, ResumePoint


class LocalHistoryStorage:
    """Keep provider-neutral history state in the shared profile database."""

    def __init__(self, database_path=None, clock=None, database=None):
        self._clock = clock or time.time
        self.database = database or ProfileDatabase(database_path=database_path, clock=self._clock)

    def initialize(self):
        self.database.initialize()

    def _timestamp(self):
        return self.database._timestamp()

    @staticmethod
    def _percent(position, duration, supplied=0):
        if duration and duration > 0:
            return max(0.0, min(100.0, (float(position) / float(duration)) * 100.0))
        return max(0.0, min(100.0, float(supplied or 0)))

    @staticmethod
    def _state(row):
        if not row:
            return HistoryState(available=True)
        return HistoryState(
            available=True,
            watched=bool(row['watched']),
            play_count=int(row['play_count'] or 0),
            percent_played=float(row['percent_played'] or 0),
            resume_time=float(row['resume_time'] or 0),
        )

    def _touch_series(self, connection, media, timestamp):
        if media.kind != 'episode' or not media.show_key:
            return
        connection.execute('''
            INSERT INTO history_series(
                show_key, imdb_id, tmdb_id, metadata_id, origin_fingerprint,
                title, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(show_key) DO UPDATE SET
                imdb_id=COALESCE(excluded.imdb_id, history_series.imdb_id),
                tmdb_id=COALESCE(excluded.tmdb_id, history_series.tmdb_id),
                metadata_id=COALESCE(excluded.metadata_id, history_series.metadata_id),
                origin_fingerprint=COALESCE(excluded.origin_fingerprint, history_series.origin_fingerprint),
                title=CASE WHEN excluded.title != '' THEN excluded.title ELSE history_series.title END,
                updated_at=excluded.updated_at
        ''', (
            media.show_key, media.show_imdb_id, media.show_tmdb_id, media.metadata_id,
            media.origin_fingerprint, media.show_title or '', timestamp,
        ))

    def _ensure_item(self, connection, media, timestamp):
        if not media.canonical_key:
            return False
        connection.execute('''
            INSERT INTO history_items(
                history_key, kind, imdb_id, tmdb_id, show_imdb_id, show_tmdb_id,
                season, episode, metadata_id, origin_fingerprint, title, show_title,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(history_key) DO UPDATE SET
                imdb_id=COALESCE(excluded.imdb_id, history_items.imdb_id),
                tmdb_id=COALESCE(excluded.tmdb_id, history_items.tmdb_id),
                title=CASE WHEN excluded.title != '' THEN excluded.title ELSE history_items.title END,
                show_title=COALESCE(excluded.show_title, history_items.show_title),
                updated_at=excluded.updated_at
        ''', (
            media.canonical_key, media.kind, media.imdb_id, media.tmdb_id,
            media.show_imdb_id, media.show_tmdb_id, media.season, media.episode,
            media.metadata_id, media.origin_fingerprint, media.title, media.show_title,
            timestamp,
        ))
        self._touch_series(connection, media, timestamp)
        return True

    def get_state(self, media):
        if not media.canonical_key:
            return HistoryState(available=True)
        with self.database._connection() as connection:
            row = connection.execute(
                'SELECT watched, play_count, percent_played, resume_time '
                'FROM history_items WHERE history_key=?', (media.canonical_key,)
            ).fetchone()
            return self._state(row)

    def get_resume(self, media, threshold=90):
        state = self.get_state(media)
        if state.watched or state.resume_time < 15 or state.percent_played >= threshold:
            return None
        with self.database._connection() as connection:
            row = connection.execute(
                'SELECT resume_time, duration, percent_played FROM history_items WHERE history_key=?',
                (media.canonical_key,),
            ).fetchone()
        if not row:
            return None
        return ResumePoint(float(row['resume_time']), float(row['duration'] or 0), float(row['percent_played'] or 0))

    def record_playback(self, media, event_type, position=0, duration=0, percent_played=0,
                        threshold=90, count_play=False):
        if not media.canonical_key:
            return False
        timestamp = self._timestamp()
        percent = self._percent(position, duration, percent_played)
        watched = event_type == 'ended' or percent >= threshold
        with self.database._connection() as connection:
            self._ensure_item(connection, media, timestamp)
            if media.kind == 'episode' and media.show_key:
                connection.execute(
                    'UPDATE history_series SET last_played_at=?, updated_at=? WHERE show_key=?',
                    (timestamp, timestamp, media.show_key),
                )
            if watched:
                connection.execute('''
                    UPDATE history_items SET watched=1,
                        play_count=play_count + ?, resume_time=0, duration=?,
                        percent_played=100, first_watched_at=COALESCE(first_watched_at, ?),
                        last_watched_at=?, last_played_at=?, updated_at=?
                    WHERE history_key=?
                ''', (1 if count_play else 0, duration or 0, timestamp, timestamp, timestamp,
                      timestamp, media.canonical_key))
            elif event_type != 'start':
                connection.execute('''
                    UPDATE history_items SET resume_time=?, duration=?, percent_played=?,
                        last_played_at=?, updated_at=? WHERE history_key=?
                ''', (max(0, float(position or 0)), max(0, float(duration or 0)), percent,
                      timestamp, timestamp, media.canonical_key))
        return True

    def mark_watched(self, media, watched, count_play=False):
        if not media.canonical_key:
            return False
        timestamp = self._timestamp()
        with self.database._connection() as connection:
            self._ensure_item(connection, media, timestamp)
            if watched:
                connection.execute('''
                    UPDATE history_items SET watched=1, play_count=play_count + ?,
                        resume_time=0, percent_played=100,
                        first_watched_at=COALESCE(first_watched_at, ?), last_watched_at=?,
                        last_played_at=?, updated_at=? WHERE history_key=?
                ''', (1 if count_play else 0, timestamp, timestamp, timestamp, timestamp,
                      media.canonical_key))
            else:
                connection.execute('''
                    UPDATE history_items SET watched=0, resume_time=0, percent_played=0,
                        updated_at=? WHERE history_key=?
                ''', (timestamp, media.canonical_key))
        return True

    def clear_progress(self, media):
        if not media.canonical_key:
            return False
        with self.database._connection() as connection:
            cursor = connection.execute('''
                UPDATE history_items SET resume_time=0, percent_played=0, updated_at=?
                WHERE history_key=?
            ''', (self._timestamp(), media.canonical_key))
            return cursor.rowcount > 0

    def set_hidden(self, show, hidden):
        if not show.show_key:
            return False
        timestamp = self._timestamp()
        with self.database._connection() as connection:
            self._touch_series(connection, show, timestamp)
            connection.execute('''
                UPDATE history_series SET hidden_from_next_up=?, updated_at=? WHERE show_key=?
            ''', (1 if hidden else 0, timestamp, show.show_key))
        return True

    def ingest_episode_catalog(self, show, episodes: Iterable[dict]):
        if not show.show_key:
            return 0
        timestamp = self._timestamp()
        written = 0
        with self.database._connection() as connection:
            self._touch_series(connection, show, timestamp)
            for item in episodes or ():
                try:
                    season, episode = int(item.get('season')), int(item.get('episode'))
                except (TypeError, ValueError, AttributeError):
                    continue
                metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else item
                connection.execute('''
                    INSERT INTO history_episode_catalog(
                        show_key, season, episode, imdb_id, tmdb_id, metadata_id,
                        title, air_date, metadata_json, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(show_key, season, episode) DO UPDATE SET
                        imdb_id=COALESCE(excluded.imdb_id, history_episode_catalog.imdb_id),
                        tmdb_id=COALESCE(excluded.tmdb_id, history_episode_catalog.tmdb_id),
                        metadata_id=COALESCE(excluded.metadata_id, history_episode_catalog.metadata_id),
                        title=CASE WHEN excluded.title != '' THEN excluded.title ELSE history_episode_catalog.title END,
                        air_date=COALESCE(excluded.air_date, history_episode_catalog.air_date),
                        metadata_json=COALESCE(excluded.metadata_json, history_episode_catalog.metadata_json),
                        last_seen_at=excluded.last_seen_at
                ''', (
                    show.show_key, season, episode, item.get('imdb_id') or item.get('imdb'),
                    item.get('tmdb_id') or item.get('tmdb'), item.get('id') or item.get('metadata_id'),
                    item.get('title') or item.get('name') or '', item.get('released') or item.get('air_date'),
                    json.dumps(metadata, separators=(',', ':'), sort_keys=True), timestamp,
                ))
                written += 1
            connection.execute('''
                UPDATE history_series SET metadata_refreshed_at=?, updated_at=? WHERE show_key=?
            ''', (timestamp, timestamp, show.show_key))
        return written

    def list_next_up(self, limit=None, threshold=90):
        today = date.today().isoformat()
        entries = []
        with self.database._connection() as connection:
            shows = connection.execute('''
                SELECT * FROM history_series
                WHERE hidden_from_next_up=0 AND last_played_at IS NOT NULL
                ORDER BY last_played_at DESC
            ''').fetchall()
            for show in shows:
                catalog = connection.execute('''
                    SELECT c.*, i.watched, i.play_count, i.resume_time, i.duration, i.percent_played
                    FROM history_episode_catalog c
                    LEFT JOIN history_items i ON i.history_key =
                        'episode:' || c.show_key || ':' || c.season || ':' || c.episode
                    WHERE c.show_key=? AND c.season > 0
                      AND (c.air_date IS NULL OR c.air_date='' OR c.air_date <= ?)
                    ORDER BY c.season, c.episode
                ''', (show['show_key'], today)).fetchall()
                if not catalog:
                    continue
                resume = next((row for row in catalog if not row['watched'] and
                               float(row['resume_time'] or 0) >= 15 and
                               float(row['percent_played'] or 0) < threshold), None)
                watched_positions = [index for index, row in enumerate(catalog) if row['watched']]
                chosen = resume
                if chosen is None:
                    start = watched_positions[-1] + 1 if watched_positions else 0
                    chosen = next((row for row in catalog[start:] if not row['watched']), None)
                if chosen is None:
                    continue
                media = HistoryMediaRef(
                    kind='episode', imdb_id=chosen['imdb_id'], tmdb_id=chosen['tmdb_id'],
                    show_imdb_id=show['imdb_id'], show_tmdb_id=show['tmdb_id'],
                    season=chosen['season'], episode=chosen['episode'],
                    metadata_id=chosen['metadata_id'] or show['metadata_id'],
                    origin_fingerprint=show['origin_fingerprint'], title=chosen['title'],
                    show_title=show['title'],
                )
                entries.append(NextUpEntry(media, self._state(chosen), chosen['air_date']))
                if limit is not None and len(entries) >= limit:
                    break
        return entries

    def clear(self):
        with self.database._connection() as connection:
            connection.execute('DELETE FROM history_items')
            connection.execute('DELETE FROM history_series')
            connection.execute('DELETE FROM history_episode_catalog')
