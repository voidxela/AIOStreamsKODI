"""Profile-local history provider."""
from collections import OrderedDict

from .models import (HistoryMediaRef, HistoryState, PlaybackEvent,
                     ProviderCapabilities, ProviderResult, ProviderResultCode,
                     ProviderStatus)
from .storage import LocalHistoryStorage


class LocalHistoryProvider:
    provider_id = 'local'

    def __init__(self, storage=None, watched_threshold=90):
        self.storage = storage or LocalHistoryStorage()
        self.watched_threshold = float(watched_threshold or 90)

    def status(self):
        try:
            self.storage.initialize()
            return ProviderStatus(self.provider_id, True, True,
                                  capabilities=ProviderCapabilities(progress=True, next_up=True))
        except Exception as error:
            return ProviderStatus(self.provider_id, True, False, message=type(error).__name__)

    def configure(self, addon):
        """Open the local provider's small, self-contained configuration wizard."""
        try:
            import xbmcgui
            self.storage.initialize()
            metrics = self.storage.statistics()
            message = (
                'Local History is ready. It does not require an account.\n\n'
                'Database: {}\n'
                'Tracked items: {}\n'
                'Watched items: {}\n'
                'Resume points: {}\n'
                'Series in progress: {}'
            ).format(
                self.storage.database.database_path, metrics['items'], metrics['watched'],
                metrics['resume'], metrics['series'],
            )
            xbmcgui.Dialog().ok('Local History', message)
            return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def get_config(self):
        status = self.status()
        values = OrderedDict()
        values['Status'] = 'Ready' if status.available else 'Unavailable ({})'.format(status.message or 'unknown error')
        values['Database'] = self.storage.database.database_path
        if status.available:
            try:
                metrics = self.storage.statistics()
                values['Tracked items'] = str(metrics['items'])
                values['Watched items'] = str(metrics['watched'])
                values['Resume points'] = str(metrics['resume'])
            except Exception:
                values['Metrics'] = 'Unavailable'
        return values

    def _result(self, operation):
        status = self.status()
        if not status.available:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, status.message)
        try:
            operation()
            return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id)
        except Exception as error:
            return ProviderResult(ProviderResultCode.TEMPORARY_FAILURE, self.provider_id, type(error).__name__)

    def get_state(self, media):
        if not self.status().available:
            return HistoryState()
        try:
            return self.storage.get_state(media)
        except Exception:
            return HistoryState()

    def get_resume(self, media):
        if not self.status().available:
            return None
        try:
            return self.storage.get_resume(media, self.watched_threshold)
        except Exception:
            return None

    def handle_playback(self, event):
        return self._result(lambda: self.storage.record_playback(
            event.media, event.event_type.value, event.position, event.duration,
            event.percent_played, self.watched_threshold,
            count_play=event.event_type.value == 'ended' or event.percent_played >= self.watched_threshold,
        ))

    def mark_watched(self, media, watched):
        return self._result(lambda: self.storage.mark_watched(media, watched))

    def clear_progress(self, media):
        return self._result(lambda: self.storage.clear_progress(media))

    def list_next_up(self, limit=None):
        if not self.status().available:
            return []
        try:
            return self.storage.list_next_up(limit, self.watched_threshold)
        except Exception:
            return []

    def set_next_up_hidden(self, show, hidden):
        return self._result(lambda: self.storage.set_hidden(show, hidden))

    def ingest_episode_catalog(self, show, episodes):
        return self._result(lambda: self.storage.ingest_episode_catalog(show, episodes))

    def clear(self):
        return self._result(self.storage.clear)

    def sync(self, force=False):
        return ProviderResult(ProviderResultCode.SUCCESS, self.provider_id)
