import os
import sys
import tempfile
import unittest
from collections import OrderedDict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'plugin.video.aiostreams'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from resources.lib.history.local import LocalHistoryProvider
from resources.lib.history.manager import HistoryManager
from resources.lib.history.models import (HistoryMediaRef, PlaybackEvent,
                                          PlaybackEventType, ProviderResult,
                                          ProviderResultCode)
from resources.lib.history.storage import LocalHistoryStorage


class LocalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = LocalHistoryProvider(LocalHistoryStorage(
            database_path=os.path.join(self.temp.name, 'user_state.db')
        ), watched_threshold=90)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def movie():
        return HistoryMediaRef('movie', imdb_id='tt0133093', title='The Matrix')

    @staticmethod
    def episode(number=1):
        return HistoryMediaRef('episode', show_imdb_id='tt0903747', season=1, episode=number,
                               title='Pilot', show_title='Breaking Bad')

    def test_progress_is_resumable_then_completion_clears_it(self):
        media = self.movie()
        self.provider.handle_playback(PlaybackEvent(PlaybackEventType.START, media))
        self.provider.handle_playback(PlaybackEvent(PlaybackEventType.PAUSE, media, 120, 1000))
        resume = self.provider.get_resume(media)
        self.assertIsNotNone(resume)
        self.assertEqual(120, resume.position)

        self.provider.handle_playback(PlaybackEvent(PlaybackEventType.ENDED, media, 1000, 1000))
        state = self.provider.get_state(media)
        self.assertTrue(state.watched)
        self.assertEqual(0, state.resume_time)
        self.assertIsNone(self.provider.get_resume(media))

    def test_next_up_prefers_resume_and_honors_hidden(self):
        show = HistoryMediaRef('episode', show_imdb_id='tt0903747', show_title='Breaking Bad')
        self.provider.ingest_episode_catalog(show, [
            {'season': 0, 'episode': 1, 'title': 'Special'},
            {'season': 1, 'episode': 1, 'title': 'Pilot', 'released': '2008-01-20'},
            {'season': 1, 'episode': 2, 'title': 'Cat', 'released': '2008-01-27'},
        ])
        self.provider.handle_playback(PlaybackEvent(PlaybackEventType.PAUSE, self.episode(2), 120, 1000))
        entries = self.provider.list_next_up()
        self.assertEqual(1, len(entries))
        self.assertEqual(2, entries[0].media.episode)

        self.provider.set_next_up_hidden(show, True)
        self.assertEqual([], self.provider.list_next_up())
        self.provider.set_next_up_hidden(show, False)
        self.assertEqual(2, self.provider.list_next_up()[0].media.episode)

    def test_identity_is_stable_across_origins_when_imdb_exists(self):
        first = HistoryMediaRef('movie', imdb_id='tt0133093', metadata_id='backend-a', origin_fingerprint='a')
        second = HistoryMediaRef('movie', imdb_id='tt0133093', metadata_id='backend-b', origin_fingerprint='b')
        self.provider.mark_watched(first, True)
        self.assertTrue(self.provider.get_state(second).watched)

    def test_local_provider_exposes_ordered_read_only_status(self):
        config = self.provider.get_config()
        self.assertIsInstance(config, OrderedDict)
        self.assertEqual([
            'local_history_database_path', 'local_history_tracked_items',
            'local_history_watched_items', 'local_history_resume_points',
        ],
                         list(config))
        self.assertEqual('0', config['local_history_tracked_items'])


class _UnavailableProvider:
    provider_id = 'trakt_legacy'
    def status(self):
        from resources.lib.history.models import ProviderStatus
        return ProviderStatus('trakt_legacy', True, False, authenticated=False)
    def get_state(self, media): raise AssertionError('unavailable reads should not be called')
    def get_resume(self, media): raise AssertionError('unavailable reads should not be called')
    def handle_playback(self, event): return ProviderResult(ProviderResultCode.AUTHENTICATION_UNAVAILABLE, 'trakt_legacy')
    def mark_watched(self, media, watched): return ProviderResult(ProviderResultCode.AUTHENTICATION_UNAVAILABLE, 'trakt_legacy')
    def clear_progress(self, media): return ProviderResult(ProviderResultCode.AUTHENTICATION_UNAVAILABLE, 'trakt_legacy')
    def list_next_up(self, limit=None): return []
    def set_next_up_hidden(self, show, hidden): return ProviderResult(ProviderResultCode.AUTHENTICATION_UNAVAILABLE, 'trakt_legacy')
    def sync(self, force=False): return ProviderResult(ProviderResultCode.AUTHENTICATION_UNAVAILABLE, 'trakt_legacy')


class HistoryManagerTests(unittest.TestCase):
    def test_remote_availability_failure_uses_local_fallback(self):
        with tempfile.TemporaryDirectory() as path:
            local = LocalHistoryProvider(LocalHistoryStorage(os.path.join(path, 'user_state.db')))
            settings = {'history_provider': 'trakt_legacy', 'history_fallback_provider': 'local'}
            manager = HistoryManager(lambda name, default='': settings.get(name, default),
                                     {'trakt_legacy': _UnavailableProvider(), 'local': local})
            media = HistoryMediaRef('movie', imdb_id='tt0133093')
            result = manager.mark_watched(media, True)
            self.assertTrue(result.succeeded)
            self.assertEqual('local', result.provider_id)
            self.assertTrue(local.get_state(media).watched)

    def test_manager_projects_provider_config_to_read_only_settings(self):
        class Addon:
            def __init__(self, values):
                self.values = values

            def setSetting(self, name, value):
                self.values[name] = value

        with tempfile.TemporaryDirectory() as path:
            local = LocalHistoryProvider(LocalHistoryStorage(os.path.join(path, 'user_state.db')))
            settings = {'history_provider': 'local'}
            manager = HistoryManager(lambda name, default='': settings.get(name, default),
                                     {'local': local})
            addon = Addon(settings)
            config = manager.refresh_settings_status(addon)
            self.assertEqual('0', config['local_history_tracked_items'])
            self.assertEqual('Local History', addon.values['history_provider_display'])
            self.assertEqual('0', addon.values['local_history_tracked_items'])

            result = manager.select_provider(addon, 'none')
            self.assertTrue(result.succeeded)
            self.assertEqual('none', settings['history_provider'])
            self.assertEqual('Disabled', settings['history_provider_display'])
            self.assertEqual('', settings['local_history_tracked_items'])
            self.assertTrue(settings['disabled_history_status'])
