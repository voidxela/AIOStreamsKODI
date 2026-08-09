"""Selection and deterministic fallback for history providers."""
from collections import OrderedDict

from .legacy_trakt import LegacyTraktHistoryProvider
from .local import LocalHistoryProvider
from .models import (HistoryState, ProviderCapabilities, ProviderResult,
                     ProviderResultCode, ProviderStatus, HistoryMediaRef,
                     PlaybackEvent, PlaybackEventType)


class DisabledHistoryProvider:
    provider_id = 'none'
    config_setting_ids = ('disabled_history_status',)

    def status(self):
        return ProviderStatus(self.provider_id, False, False, authenticated=True,
                              capabilities=ProviderCapabilities(False, False, False), message='History is disabled')

    def configure(self, addon):
        return ProviderResult(ProviderResultCode.DISABLED, self.provider_id, 'History is disabled')

    def get_config(self):
        return OrderedDict((
            ('disabled_history_status', 'No watched state, resume points, or Next Up are stored'),
        ))

    def get_state(self, media): return HistoryState()
    def get_resume(self, media): return None
    def handle_playback(self, event): return ProviderResult(ProviderResultCode.DISABLED, self.provider_id)
    def mark_watched(self, media, watched): return ProviderResult(ProviderResultCode.DISABLED, self.provider_id)
    def clear_progress(self, media): return ProviderResult(ProviderResultCode.DISABLED, self.provider_id)
    def list_next_up(self, limit=None): return []
    def set_next_up_hidden(self, show, hidden): return ProviderResult(ProviderResultCode.DISABLED, self.provider_id)
    def sync(self, force=False): return ProviderResult(ProviderResultCode.DISABLED, self.provider_id)


class HistoryManager:
    """Single history facade used by playback, presentation, actions and service."""

    def __init__(self, get_setting=None, providers=None):
        self._get_setting = get_setting or (lambda name, default='': default)
        providers = providers or {}
        threshold = self._get_setting('auto_mark_watched_percent', '90')
        self.providers = {
            'local': providers.get('local') or LocalHistoryProvider(watched_threshold=threshold),
            'trakt_legacy': providers.get('trakt_legacy') or LegacyTraktHistoryProvider(self._get_setting),
            'none': providers.get('none') or DisabledHistoryProvider(),
        }

    def _configured_provider_id(self):
        configured = self._get_setting('history_provider', '').strip().lower()
        if configured in self.providers:
            return configured
        # Upgrade path: legacy authorized installations retain their history;
        # otherwise, including every new installation, begin with Local.
        try:
            return 'trakt_legacy' if self._get_setting('trakt_token', '') else 'local'
        except Exception:
            return 'local'

    @property
    def primary(self):
        return self.providers[self._configured_provider_id()]

    @property
    def fallback(self):
        if self.primary.provider_id == 'trakt_legacy':
            configured = self._get_setting('history_fallback_provider', 'local').strip().lower()
            return self.providers.get(configured, self.providers['local'])
        return self.providers['none']

    def status(self):
        return self.primary.status()

    @property
    def provider_label(self):
        return {
            'local': 'Local History',
            'trakt_legacy': 'Legacy Trakt History',
            'none': 'Disabled',
        }.get(self.primary.provider_id, self.primary.provider_id)

    def get_config(self):
        """Return the active provider's ordered, display-ready status values."""
        return self.primary.get_config()

    def refresh_settings_status(self, addon):
        """Project every provider's status into its named read-only settings.

        Kodi reevaluates ``visible`` conditions as a select setting changes,
        but it does not call into the add-on to populate the newly visible
        fields.  Keeping each provider's own fields populated lets switching
        the native History Provider control update the page immediately.
        """
        entries = OrderedDict()
        setting_ids = []
        for provider in self.providers.values():
            provider_setting_ids = getattr(provider, 'config_setting_ids', ())
            setting_ids.extend(provider_setting_ids)
            try:
                entries.update(provider.get_config())
            except Exception as error:
                for setting_id in provider_setting_ids:
                    entries[setting_id] = 'Unavailable ({})'.format(type(error).__name__)
        for setting_id in setting_ids:
            try:
                addon.setSetting(setting_id, str(entries.get(setting_id, '')))
            except Exception:
                pass
        return entries

    def select_provider(self, addon, provider_id):
        provider_id = (provider_id or '').strip().lower()
        if provider_id not in self.providers:
            return ProviderResult(ProviderResultCode.UNSUPPORTED, provider_id, 'Unknown history provider')
        try:
            addon.setSetting('history_provider', provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, provider_id, type(error).__name__)
        self.refresh_settings_status(addon)
        return ProviderResult(ProviderResultCode.SUCCESS, provider_id)

    def configure(self, addon):
        result = self.primary.configure(addon)
        self.refresh_settings_status(addon)
        return result

    @staticmethod
    def _can_read(provider):
        status = provider.status()
        return status.enabled and status.available and status.authenticated

    def _read_provider(self):
        primary = self.primary
        if self._can_read(primary):
            return primary
        fallback = self.fallback
        return fallback if self._can_read(fallback) else primary

    def get_state(self, media):
        return self._read_provider().get_state(media)

    def get_resume(self, media):
        return self._read_provider().get_resume(media)

    def _write(self, method, *args):
        provider = self.primary
        result = getattr(provider, method)(*args)
        if result.allows_fallback and self.fallback.provider_id != provider.provider_id:
            fallback_result = getattr(self.fallback, method)(*args)
            if fallback_result.succeeded:
                return ProviderResult(ProviderResultCode.SUCCESS, fallback_result.provider_id,
                                      fallback_provider_id=fallback_result.provider_id)
        return result

    def handle_playback(self, event): return self._write('handle_playback', event)
    def mark_watched(self, media, watched): return self._write('mark_watched', media, watched)
    def clear_progress(self, media): return self._write('clear_progress', media)
    def set_next_up_hidden(self, show, hidden): return self._write('set_next_up_hidden', show, hidden)
    def sync(self, force=False): return self._write('sync', force)

    def list_next_up(self, limit=None):
        return self._read_provider().list_next_up(limit)

    def ingest_episode_catalog(self, show, episodes):
        provider = self.primary
        ingest = getattr(provider, 'ingest_episode_catalog', None)
        if ingest:
            return ingest(show, episodes)
        fallback = self.fallback
        ingest = getattr(fallback, 'ingest_episode_catalog', None)
        if ingest:
            return ingest(show, episodes)
        return ProviderResult(ProviderResultCode.UNSUPPORTED, provider.provider_id)

    def clear_local_history(self):
        local = self.providers['local']
        clear = getattr(local, 'clear', None)
        return clear() if clear else ProviderResult(ProviderResultCode.UNSUPPORTED, 'local')

    def import_legacy_trakt_history(self):
        """Copy only stable watched/progress data from the legacy cache.

        This deliberately excludes watchlists, collections, ratings, and every
        unrelated Trakt hidden section.  Re-running it is safe because local
        keys are canonical and watched updates are idempotent.
        """
        local = self.providers['local']
        try:
            from resources.lib.database.trakt_sync import TraktSyncDatabase
            database = TraktSyncDatabase()
            for row in database.fetchall('SELECT imdb_id, tmdb_id, title, watched FROM movies WHERE imdb_id IS NOT NULL'):
                media = HistoryMediaRef('movie', imdb_id=row.get('imdb_id'), tmdb_id=row.get('tmdb_id'),
                                        title=row.get('title') or '')
                if row.get('watched'):
                    local.mark_watched(media, True)
            for row in database.fetchall('''
                SELECT e.imdb_id AS episode_imdb_id, e.tmdb_id AS episode_tmdb_id,
                       e.season, e.episode, e.watched, s.imdb_id AS show_imdb_id,
                       s.tmdb_id AS show_tmdb_id, s.title AS show_title
                FROM episodes e JOIN shows s ON s.trakt_id=e.show_trakt_id
                WHERE s.imdb_id IS NOT NULL
            '''):
                media = HistoryMediaRef('episode', imdb_id=row.get('episode_imdb_id'),
                    tmdb_id=row.get('episode_tmdb_id'), show_imdb_id=row.get('show_imdb_id'),
                    show_tmdb_id=row.get('show_tmdb_id'), season=row.get('season'), episode=row.get('episode'),
                    show_title=row.get('show_title') or '')
                if row.get('watched'):
                    local.mark_watched(media, True)
            for row in database.fetchall('SELECT imdb_id, tmdb_id, resume_time, percent_played FROM bookmarks WHERE imdb_id IS NOT NULL'):
                media = HistoryMediaRef('movie', imdb_id=row.get('imdb_id'), tmdb_id=row.get('tmdb_id'))
                if float(row.get('resume_time') or 0) >= 15:
                    local.handle_playback(PlaybackEvent(PlaybackEventType.PAUSE, media,
                        float(row.get('resume_time') or 0), 0, float(row.get('percent_played') or 0)))
            return ProviderResult(ProviderResultCode.SUCCESS, 'local')
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, 'local', type(error).__name__)
