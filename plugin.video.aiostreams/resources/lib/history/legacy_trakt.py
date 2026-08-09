"""Compatibility adapter for existing user-configured Trakt history.

This is deliberately a thin wrapper.  New functionality belongs in a future
provider, not in the legacy user-credential integration.
"""
from collections import OrderedDict

from .models import (HistoryMediaRef, HistoryState, NextUpEntry, PlaybackEvent,
                     ProviderCapabilities, ProviderResult, ProviderResultCode,
                     ProviderStatus, ResumePoint)


class LegacyTraktHistoryProvider:
    provider_id = 'trakt_legacy'

    def __init__(self, get_setting=None):
        self._get_setting = get_setting or (lambda name, default='': default)

    def _trakt(self):
        from resources.lib import trakt
        return trakt

    def status(self):
        try:
            if not self._trakt().get_access_token():
                return ProviderStatus(self.provider_id, True, False, authenticated=False,
                                      capabilities=ProviderCapabilities(progress=True, next_up=True, synchronization=True),
                                      message='Trakt authorization is unavailable')
            return ProviderStatus(self.provider_id, True, True,
                                  capabilities=ProviderCapabilities(progress=True, next_up=True, synchronization=True))
        except Exception as error:
            return ProviderStatus(self.provider_id, True, False, authenticated=False, message=type(error).__name__)

    def configure(self, addon):
        """Configure user-supplied legacy credentials, then start device OAuth."""
        try:
            import xbmcgui
            action = xbmcgui.Dialog().select('Legacy Trakt History', [
                'Set client credentials', 'Authorize Trakt', 'Revoke authorization',
            ])
            if action < 0:
                return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id, 'Configuration cancelled')
            if action == 0:
                client_id = xbmcgui.Dialog().input(
                    'Legacy Trakt Client ID', defaultt=addon.getSetting('trakt_client_id'),
                    type=xbmcgui.INPUT_ALPHANUM,
                )
                if not client_id:
                    return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id, 'Configuration cancelled')
                client_secret = xbmcgui.Dialog().input(
                    'Legacy Trakt Client Secret', defaultt=addon.getSetting('trakt_client_secret'),
                    type=xbmcgui.INPUT_ALPHANUM,
                )
                if not client_secret:
                    return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id, 'Configuration cancelled')
                addon.setSetting('trakt_client_id', client_id)
                addon.setSetting('trakt_client_secret', client_secret)
                return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id)
            if action == 1:
                return ProviderResult(
                    ProviderResultCode.SUCCESS if self._trakt().authorize() else ProviderResultCode.TEMPORARY_FAILURE,
                    self.provider_id,
                )
            self._trakt().revoke_authorization()
            return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def get_config(self):
        status = self.status()
        values = OrderedDict()
        values['Status'] = 'Authorized' if status.available else 'Authorization required'
        try:
            username = self._trakt().get_trakt_username()
        except Exception:
            username = ''
        if username:
            values['Account'] = username
        client_id = self._get_setting('trakt_client_id', '')
        client_secret = self._get_setting('trakt_client_secret', '')
        values['Client credentials'] = 'Configured' if client_id and client_secret else 'Required'
        values['Background sync'] = 'Enabled' if self._get_setting('trakt_sync_auto', 'true') == 'true' else 'Disabled'
        return values

    def _unavailable(self):
        status = self.status()
        if status.available:
            return None
        code = ProviderResultCode.AUTHENTICATION_UNAVAILABLE if not status.authenticated else ProviderResultCode.TEMPORARY_FAILURE
        return ProviderResult(code, self.provider_id, status.message)

    def get_state(self, media):
        if not self.status().available:
            return HistoryState()
        try:
            trakt = self._trakt()
            if media.kind == 'movie':
                watched = trakt.is_watched('movie', media.imdb_id or media.metadata_id)
            else:
                watched = trakt.is_episode_watched(media.show_imdb_id or media.metadata_id, media.season, media.episode)
            bookmark = trakt.get_trakt_db().get_bookmark(imdb_id=media.imdb_id or media.show_imdb_id) or {}
            return HistoryState(True, bool(watched), 0, bookmark.get('percent_played', 0) or 0,
                                bookmark.get('resume_time', 0) or 0)
        except Exception:
            return HistoryState()

    def get_resume(self, media):
        state = self.get_state(media)
        if not state.available or state.watched or state.resume_time < 15:
            return None
        return ResumePoint(state.resume_time, 0, state.percent_played)

    def handle_playback(self, event):
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        try:
            media = event.media
            if event.event_type.value == 'ended' or event.percent_played >= 90:
                ok = self._trakt().mark_watched('movie' if media.kind == 'movie' else 'episode',
                                                 media.imdb_id or media.show_imdb_id,
                                                 media.season, media.episode)
            else:
                action = 'start' if event.event_type.value == 'resume' else event.event_type.value
                ok = self._trakt().scrobble(action, 'movie' if media.kind == 'movie' else 'episode',
                                             media.imdb_id or media.show_imdb_id, event.percent_played,
                                             media.season, media.episode)
            return ProviderResult(ProviderResultCode.SUCCESS if ok is not False else ProviderResultCode.TEMPORARY_FAILURE,
                                  self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def mark_watched(self, media, watched):
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        try:
            action = self._trakt().mark_watched if watched else self._trakt().mark_unwatched
            ok = action('movie' if media.kind == 'movie' else 'episode',
                        media.imdb_id or media.show_imdb_id, media.season, media.episode)
            return ProviderResult(ProviderResultCode.SUCCESS if ok else ProviderResultCode.TEMPORARY_FAILURE, self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def clear_progress(self, media):
        return ProviderResult(ProviderResultCode.UNSUPPORTED, self.provider_id,
                              'Legacy Trakt does not expose a stable playback id')

    def list_next_up(self, limit=None):
        if not self.status().available:
            return []
        try:
            rows = self._trakt().get_trakt_db().get_next_up_episodes()
            entries = []
            for row in rows[:limit] if limit else rows:
                media = HistoryMediaRef('episode', imdb_id=row.get('episode_imdb_id'),
                    tmdb_id=row.get('episode_tmdb_id'), show_imdb_id=row.get('show_imdb_id'),
                    show_tmdb_id=row.get('show_tmdb_id'), season=row.get('season'), episode=row.get('episode'),
                    title=row.get('title', ''), show_title=row.get('show_title'))
                entries.append(NextUpEntry(media, HistoryState(True, bool(row.get('watched')), 0,
                               row.get('percent_played', 0) or 0, row.get('resume_time', 0) or 0)))
            return entries
        except Exception:
            return []

    def set_next_up_hidden(self, show, hidden):
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        try:
            action = self._trakt().hide_from_progress if hidden else self._trakt().unhide_from_progress
            ok = action('series', show.show_imdb_id or show.imdb_id)
            return ProviderResult(ProviderResultCode.SUCCESS if ok else ProviderResultCode.TEMPORARY_FAILURE, self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def sync(self, force=False):
        unavailable = self._unavailable()
        if unavailable:
            return unavailable
        try:
            from resources.lib.database.trakt_sync.activities import TraktSyncDatabase
            ok = TraktSyncDatabase().sync_activities(silent=True, force=force)
            return ProviderResult(ProviderResultCode.SUCCESS if ok is not False else ProviderResultCode.TEMPORARY_FAILURE,
                                  self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)
