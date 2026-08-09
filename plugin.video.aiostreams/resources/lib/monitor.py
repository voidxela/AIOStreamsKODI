# -*- coding: utf-8 -*-
"""Playback monitoring that emits provider-neutral history events."""
import json
import threading
import time
from dataclasses import asdict
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.history import (HistoryManager, HistoryMediaRef, PlaybackEvent,
                                   PlaybackEventType)

ADDON = xbmcaddon.Addon()


class AIOStreamsPlayer(xbmc.Player):
    """Persistent Kodi player that owns sampling, not provider-specific logic."""

    def __init__(self, history_manager=None):
        xbmc.Player.__init__(self)
        self.history_manager = history_manager
        self.media = None
        self.is_aiostreams = False
        self.started = False
        self.total_time = 0
        self.current_time = 0
        self.marked_watched = False
        self.progress_monitor_thread = None
        self.stop_monitoring = threading.Event()
        self._last_write_at = 0
        self._last_write_percent = 0

    def set_media_info(self, media, imdb_id=None, season=None, episode=None, history_manager=None):
        """Set a complete HistoryMediaRef (legacy positional form remains harmless)."""
        if not isinstance(media, HistoryMediaRef):
            media = HistoryMediaRef('movie' if media == 'movie' else 'episode',
                imdb_id=imdb_id if media == 'movie' else None,
                show_imdb_id=imdb_id if media != 'movie' else None,
                season=season, episode=episode)
        self.media = media
        if history_manager is not None:
            self.history_manager = history_manager
        self.is_aiostreams = media.is_identifiable
        self.started = False
        self.marked_watched = False
        self.total_time = 0
        self.current_time = 0
        self._last_write_at = 0
        self._last_write_percent = 0
        try:
            window = xbmcgui.Window(10000)
            window.setProperty('AIOStreams.Player.IsActive', 'true')
            window.setProperty('AIOStreams.Player.HistoryMedia', json.dumps(asdict(media)))
        except Exception as error:
            xbmc.log('[AIOStreams] Unable to persist player state: {}'.format(type(error).__name__), xbmc.LOGDEBUG)

    def _restore_media(self):
        if self.media:
            return
        try:
            window = xbmcgui.Window(10000)
            raw = window.getProperty('AIOStreams.Player.HistoryMedia')
            if raw:
                self.media = HistoryMediaRef(**json.loads(raw))
                self.is_aiostreams = self.media.is_identifiable
            if self.history_manager is None:
                self.history_manager = HistoryManager(lambda name, default='': ADDON.getSetting(name) or default)
        except Exception:
            return

    def clear_media_info(self):
        self._stop_progress_monitoring()
        self.media = None
        self.is_aiostreams = False
        self.started = False
        self.total_time = 0
        self.current_time = 0
        self.marked_watched = False
        try:
            window = xbmcgui.Window(10000)
            window.clearProperty('AIOStreams.Player.IsActive')
            window.clearProperty('AIOStreams.Player.HistoryMedia')
        except Exception:
            pass

    def _tracking_enabled(self):
        return (self.is_aiostreams and self.media and self.history_manager and
                ADDON.getSetting('track_playback_progress') != 'false')

    def _sample(self):
        try:
            self.current_time = max(0, float(self.getTime()))
            self.total_time = max(0, float(self.getTotalTime() or self.total_time))
        except Exception:
            pass
        percent = (self.current_time / self.total_time * 100) if self.total_time else 0
        return max(0, min(100, percent))

    def _emit(self, event_type, force=False):
        if not self._tracking_enabled() or (self.marked_watched and event_type != PlaybackEventType.START):
            return None
        percent = self._sample()
        threshold = float(ADDON.getSetting('auto_mark_watched_percent') or 90)
        now = time.time()
        if (event_type == PlaybackEventType.PROGRESS and not force and
                now - self._last_write_at < 15 and abs(percent - self._last_write_percent) < 5):
            return None
        if percent >= threshold:
            self.marked_watched = True
        result = self.history_manager.handle_playback(PlaybackEvent(
            event_type, self.media, self.current_time, self.total_time, percent,
        ))
        self._last_write_at, self._last_write_percent = now, percent
        if self.marked_watched and result and result.succeeded:
            xbmc.executebuiltin('Container.Refresh')
        return result

    def _monitor_progress(self):
        while not self.stop_monitoring.is_set():
            if not self.isPlaying():
                break
            self._emit(PlaybackEventType.PROGRESS)
            if self.stop_monitoring.wait(5):
                break

    def _start_progress_monitoring(self):
        if self.progress_monitor_thread and self.progress_monitor_thread.is_alive():
            return
        self.stop_monitoring.clear()
        self.progress_monitor_thread = threading.Thread(target=self._monitor_progress, name='AIOStreamsHistory')
        self.progress_monitor_thread.daemon = True
        self.progress_monitor_thread.start()

    def _stop_progress_monitoring(self):
        self.stop_monitoring.set()
        if self.progress_monitor_thread and self.progress_monitor_thread.is_alive():
            self.progress_monitor_thread.join(timeout=1)

    def onPlayBackStarted(self):
        self._restore_media()
        if not self._tracking_enabled():
            return
        self.started = True
        self._emit(PlaybackEventType.START, force=True)
        self._start_progress_monitoring()
        self._check_autoplay_start()

    def onPlayBackPaused(self):
        if self.started:
            self._emit(PlaybackEventType.PAUSE, force=True)

    def onPlayBackResumed(self):
        if self.started:
            self._emit(PlaybackEventType.RESUME, force=True)

    def onPlayBackSeek(self, seekTime, seekOffset):
        if self.started:
            self._emit(PlaybackEventType.SEEK, force=True)

    def onPlayBackStopped(self):
        if self.started:
            self._emit(PlaybackEventType.STOP, force=True)
        self._stop_progress_monitoring()
        self.clear_media_info()

    def onPlayBackEnded(self):
        if self.started:
            self.current_time = self.total_time or self.current_time
            self._emit(PlaybackEventType.ENDED, force=True)
        self._stop_progress_monitoring()
        self.clear_media_info()

    def _check_autoplay_start(self):
        """Keep UpNext integration independent of the selected history provider."""
        if not (self.media and self.media.kind == 'episode' and self.media.show_imdb_id and
                self.media.season is not None and self.media.episode is not None and
                ADDON.getSetting('autoplay_next_episode') == 'true'):
            return
        # The existing UpNext service only needs the plugin route.  It remains
        # intentionally separate from history's Next Up calculation.
        next_params = {
            'action': 'play', 'content_type': 'series', 'imdb_id': self.media.show_imdb_id,
            'season': self.media.season, 'episode': self.media.episode + 1,
            'force_autoplay': 'true',
        }
        xbmcgui.Window(10000).setProperty('AIOStreams.UpNext.PlayURL',
                                          'plugin://plugin.video.aiostreams/?' + urlencode(next_params))


# Plugin executions may use this instance; the login service replaces it with
# its persistent player so Kodi callbacks and action requests share state.
PLAYER = AIOStreamsPlayer()
